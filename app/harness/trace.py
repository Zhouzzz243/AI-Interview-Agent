"""
链路追踪模块 — 请求级 Span/Trace 管理

【设计理念】
给每次请求打上 trace_id，关联所有子调用（LLM/Redis/HTTP），
出问题时可以串起来看完整调用链。

【核心概念】
- Trace: 一次完整请求的上下文（trace_id + 元数据）
- Span:  一次子调用（如一次 LLM 评分 / 一次 Redis 查询）
- Context: 请求级别的变量传递（无需显式传参）

【使用方式】
    from app.harness.trace import TraceContext, span

    trace = TraceContext("session_123", "chat")
    with span("scoring") as s:
        result = await scoring_skill.execute(...)
        s.set_tag("score", result.data.get("score"))

    print(trace.summary())  # 打印完整调用链
"""

import time
import inspect
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)

# ── ContextVar: 协程安全的当前 trace ──
_current_trace: ContextVar[Optional["TraceContext"]] = ContextVar(
    "current_trace", default=None
)


@dataclass
class SpanEntry:
    """一次子调用的记录"""
    name: str
    start_ms: float
    end_ms: float = 0.0
    tags: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        if self.end_ms > 0:
            return self.end_ms - self.start_ms
        return time.time() * 1000 - self.start_ms

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "tags": self.tags,
            **({"error": self.error} if self.error else {}),
        }


class TraceContext:
    """
    请求级链路追踪上下文

    【用途】
    - 自动生成 trace_id
    - 记录所有 span 开始/结束
    - 请求结束时输出 summary

    【Java 类比】
    MDC (Mapped Diagnostic Context) + Spring Cloud Sleuth
    """

    def __init__(self, trace_id: str, operation: str = "unknown"):
        self.trace_id = trace_id
        self.operation = operation
        self._spans: List[SpanEntry] = []
        self._start_ms = time.time() * 1000
        self._active_span: Optional[SpanEntry] = None

    def start_span(self, name: str) -> SpanEntry:
        """开始一个新的 span"""
        span = SpanEntry(name=name, start_ms=time.time() * 1000)
        self._spans.append(span)
        self._active_span = span
        return span

    def end_span(self, error: Optional[str] = None):
        """结束当前活跃的 span"""
        if self._active_span:
            self._active_span.end_ms = time.time() * 1000
            if error:
                self._active_span.error = error
            self._active_span = None

    def set_tag(self, key: str, value: Any):
        """给当前活跃 span 打标签"""
        if self._active_span:
            self._active_span.tags[key] = value

    def record_llm_call(
        self, model: str, tokens: int, latency_ms: float, success: bool = True
    ):
        """记录一次 LLM 调用（高层 API）"""
        self.start_span("llm_call")
        self.set_tag("model", model)
        self.set_tag("tokens", tokens)
        self.set_tag("latency_ms", round(latency_ms, 2))
        self.end_span(error=None if success else "llm_call_failed")

    def record_redis_call(self, operation: str, latency_ms: float, success: bool = True):
        """记录一次 Redis 操作"""
        self.start_span(f"redis:{operation}")
        self.set_tag("latency_ms", round(latency_ms, 2))
        self.end_span(error=None if success else "redis_failed")

    @property
    def total_duration_ms(self) -> float:
        return time.time() * 1000 - self._start_ms

    @property
    def span_count(self) -> int:
        return len(self._spans)

    def summary(self) -> dict:
        """生成摘要（用于日志输出）"""
        return {
            "trace_id": self.trace_id,
            "operation": self.operation,
            "total_ms": round(self.total_duration_ms, 2),
            "span_count": self.span_count,
            "spans": [s.to_dict() for s in self._spans],
        }


# ── 公共 API ──

def get_current_trace() -> Optional[TraceContext]:
    """获取当前协程的 trace 上下文"""
    return _current_trace.get()


def start_trace(trace_id: str, operation: str = "unknown") -> TraceContext:
    """开始一个新的 trace 并设为当前协程的活跃上下文"""
    trace = TraceContext(trace_id, operation)
    _current_trace.set(trace)
    return trace


def end_trace():
    """结束当前 trace"""
    trace = get_current_trace()
    if trace:
        logger.info(
            "trace_ended",
            trace_id=trace.trace_id,
            operation=trace.operation,
            total_ms=round(trace.total_duration_ms, 2),
            span_count=trace.span_count,
        )
        _current_trace.set(None)


class SpanContext:
    """
    Span 上下文管理器（推荐用法）

    with span("scoring") as s:
        result = await scoring_skill.execute(...)
        s.set_tag("score", 85)
    """

    def __init__(self, name: str):
        self.name = name
        self._span: Optional[SpanEntry] = None

    def __enter__(self) -> "SpanContext":
        trace = get_current_trace()
        if trace:
            self._span = trace.start_span(self.name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        trace = get_current_trace()
        if trace and self._span:
            error = str(exc_val) if exc_val else None
            trace.end_span(error=error)
        return False  # 不吞异常

    def set_tag(self, key: str, value: Any):
        """给当前 span 打标签"""
        if self._span:
            self._span.tags[key] = value


# 便捷别名
span = SpanContext


# ── 装饰器（快速为函数加上 span）──

def trace_span(name: Optional[str] = None):
    """
    为异步函数自动创建 span

    @trace_span("scoring")
    async def evaluate(self, answer: str) -> int:
        ...
    """
    span_name = name

    def decorator(func):
        async def wrapper(*args, **kwargs):
            effective_name = span_name or func.__name__
            with SpanContext(effective_name) as s:
                return await func(*args, **kwargs)
        return wrapper
    return decorator
