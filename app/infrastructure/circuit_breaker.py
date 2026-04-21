"""
熔断器模块（Circuit Breaker Pattern）

【Java类比】
- 类似 Spring Cloud 的 @CircuitBreaker 注解或 Hystrix
- 或 Resilience4j 的 CircuitBreaker 组件
- 用于防止级联故障，保护系统稳定性

【设计模式说明】
熔断器模式（Circuit Breaker Pattern）:
1. CLOSED（关闭状态）: 正常调用，记录失败次数
2. OPEN（打开状态）: 熔断中，直接返回错误不调用后端
3. HALF_OPEN（半开状态）: 尝试恢复，允许少量请求通过

【状态转换】
CLOSED ──[失败次数达到阈值]──> OPEN
OPEN    ──[冷却时间到期]─────────> HALF_OPEN
HALF_OPEN──[成功]──────────────> CLOSED
HALF_OPEN──[失败]──────────────> OPEN

【使用示例】
from app.infrastructure.circuit_breaker import circuit_breaker

@circuit_breaker("llm_call")
async def call_llm(prompt: str) -> str:
    # 如果LLM连续失败5次，自动熔断30秒
    return await llm_client.chat(prompt)

【应用场景】
- LLM API 调用（防止API故障拖垮整个系统）
- OSS 文件上传/下载
- Redis 连接操作
- ChromaDB 向量检索
"""

import asyncio
import functools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """熔断器状态枚举"""
    CLOSED = "closed"        # 关闭状态：正常工作
    OPEN = "open"            # 打开状态：熔断中，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态：尝试恢复


@dataclass
class CircuitStats:
    """熔断器统计信息"""
    failure_count: int = 0           # 当前连续失败次数
    success_count: int = 0           # 半开状态下的成功次数
    last_failure_time: Optional[float] = None  # 上次失败时间戳
    total_calls: int = 0             # 总调用次数
    total_failures: int = 0          # 总失败次数
    total_successes: int = 0         # 总成功次数


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    name: str                              # 熔断器名称（用于日志和监控）
    failure_threshold: int = 5             # 触发熔断的失败次数阈值
    recovery_timeout: float = 30.0         # 熔断后的恢复等待时间（秒）
    half_open_max_calls: int = 3          # 半开状态下允许的最大试探调用数
    success_threshold: int = 2             # 半开状态下成功多少次才恢复正常


class CircuitBreaker:
    """
    熔断器实现类

    【核心方法】
    - can_execute(): 检查是否可以执行请求
    - record_success(): 记录成功调用
    - record_failure(): 记录失败调用
    - get_state(): 获取当前状态
    """

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.stats = CircuitStats()
        self._lock = asyncio.Lock()  # 异步锁，保证线程安全

    async def can_execute(self) -> bool:
        """
        检查当前是否允许执行请求

        【返回值】
        True: 允许执行（CLOSED或HALF_OPEN状态且未达上限）
        False: 拒绝执行（OPEN状态或HALF_OPEN已达上限）

        【使用场景】
        在执行外部调用前检查：
        if not await circuit_breaker.can_execute():
            raise LLMCallError("服务暂时不可用（熔断中）")
        """
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            elif self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.stats.success_count = 0
                    logger.warning(
                        "熔断器进入半开状态",
                        breaker_name=self.config.name,
                        recovery_timeout=self.config.recovery_timeout
                    )
                    return True
                else:
                    logger.warning(
                        "请求被熔断器拒绝",
                        breaker_name=self.config.name,
                        state="OPEN",
                        failure_count=self.stats.failure_count
                    )
                    return False

            elif self.state == CircuitState.HALF_OPEN:
                if self.stats.success_count >= self.config.half_open_max_calls:
                    return False
                return True

            return False

    async def record_success(self):
        """记录一次成功调用"""
        async with self._lock:
            self.stats.total_successes += 1
            self.stats.total_calls += 1

            if self.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                if self.stats.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.stats.failure_count = 0
                    logger.info(
                        "熔断器恢复正常",
                        breaker_name=self.config.name,
                        state="CLOSED"
                    )
            elif self.state == CircuitState.CLOSED:
                self.stats.failure_count = 0  # 重置失败计数

    async def record_failure(self, error: Optional[Exception] = None):
        """
        记录一次失败调用

        【参数】
        error: 可选的异常对象，用于日志记录
        """
        async with self._lock:
            self.stats.total_failures += 1
            self.stats.total_calls += 1
            self.stats.failure_count += 1
            self.stats.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                logger.error(
                    "熔断器半开状态探测失败，重新打开",
                    breaker_name=self.config.name,
                    error=str(error)
                )
            elif self.state == CircuitState.CLOSED:
                if self.stats.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.error(
                        "熔断器触发！达到失败阈值",
                        breaker_name=self.config.name,
                        failure_threshold=self.config.failure_threshold,
                        current_failures=self.stats.failure_count,
                        error=str(error)
                    )

    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试从OPEN状态恢复"""
        if self.stats.last_failure_time is None:
            return True
        elapsed = time.time() - self.stats.last_failure_time
        return elapsed >= self.config.recovery_timeout

    def get_state(self) -> CircuitState:
        """获取当前状态"""
        return self.state

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（用于监控面板展示）"""
        return {
            "name": self.config.name,
            "state": self.state.value,
            "failure_count": self.stats.failure_count,
            "total_calls": self.stats.total_calls,
            "success_rate": (
                round(self.stats.total_successes / max(self.stats.total_calls, 1) * 100, 2)
                if self.stats.total_calls > 0 else 0
            ),
            "last_failure_time": self.stats.last_failure_time
        }


# ========== 全局熔断器注册表 ==========
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_or_create_breaker(name: str, **config_kwargs) -> CircuitBreaker:
    """
    获取或创建熔断器实例（工厂方法）

    【参数】
    name: 熔断器唯一标识符
    **config_kwargs: 可选的配置参数覆盖默认值

    【返回】
    CircuitBreaker: 熔断器实例（单例，相同name返回同一实例）

    【预定义的熔断器】
    - "llm_call": LLM API调用（失败5次/恢复30秒）
    - "oss_operation": OSS文件操作（失败3次/恢复20秒）
    - "vector_db": 向量数据库操作（失败5次/恢复30秒）
    - "redis_operation": Redis操作（失败3次/恢复15秒）
    """
    if name not in _circuit_breakers:
        default_configs = {
            "llm_call": dict(failure_threshold=5, recovery_timeout=30.0),
            "oss_operation": dict(failure_threshold=3, recovery_timeout=20.0),
            "vector_db": dict(failure_threshold=5, recovery_timeout=30.0),
            "redis_operation": dict(failure_threshold=3, recovery_timeout=15.0),
        }

        base_config = default_configs.get(name, {})
        base_config.update(config_kwargs)
        base_config["name"] = name

        config = CircuitBreakerConfig(**base_config)
        _circuit_breakers[name] = CircuitBreaker(config)

    return _circuit_breakers[name]


def circuit_breaker(name: str, **config_kwargs):
    """
    熔断器装饰器（类似Spring的@CircuitBreaker注解）

    【用法】
    @circuit_breaker("llm_call", failure_threshold=3)
    async def call_external_api():
        # 这个函数会被熔断器保护
        ...

    【工作机制】
    1. 函数调用前：检查熔断器状态，如果OPEN则直接抛异常
    2. 函数执行成功：调用 record_success()
    3. 函数执行失败：调用 record_failure() 并重新抛出异常

    【参数】
    name: 熔断器名称
    **config_kwargs: 可选配置覆盖

    【返回】
    装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        breaker = get_or_create_breaker(name, **config_kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            if not await breaker.can_execute():
                from app.infrastructure.error_handler import LLMCallError
                raise LLMCallError(
                    f"服务暂时不可用（熔断器 {name} 处于打开状态）",
                    detail=f"Circuit breaker '{name}' is OPEN"
                )

            try:
                result = await func(*args, **kwargs)
                await breaker.record_success()
                return result
            except Exception as e:
                await breaker.record_failure(e)
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            import asyncio
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(async_wrapper(*args, **kwargs))

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
