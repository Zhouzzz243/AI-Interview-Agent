"""
重试策略模块（Retry Policy）- 指数退避 + 错误分类 + 随机抖动

【Java 类比】
类似 Resilience4j 的 Retry 模块，或者 Spring Retry 的 @Retryable 注解。

【核心设计】
1. 错误分类：5xx/429/网络错误 → 可重试；4xx/业务错误 → 不重试
2. 指数退避：delay = base_delay * 2^retry_count
3. 随机抖动：delay *= (1 + random() * jitter)，避免惊群效应
4. 最大延迟上限：防止退避到天文数字
5. 总超时上限：防止重试总时间过长

【抖动公式详解】
delay = base_delay * 2^retry_count * (1 + random() * jitter)
- base_delay: 基础延迟（默认1秒）
- 2^retry_count: 指数增长
- jitter: 0~0.5（50%抖动），AWS SDK/gRPC 的经验值
  - 太小(0~10%): 惊群效应缓解有限
  - 太大(0~100%): 延迟方差过大，个别请求等很久
  - 50%: 错开大部分重试又不让单个请求延迟翻倍

【使用示例】
from app.harness.retry import RetryPolicy, retry

policy = RetryPolicy(max_retries=3, base_delay=1.0)

# 方式1：上下文管理器
result = await policy.execute(lambda: llm_client.chat("hello"))

# 方式2：装饰器（如果异步装饰器场景）
@retry(max_retries=3)
async def call_llm(prompt: str):
    return await llm_client.chat(prompt)
"""

import asyncio
import functools
import random
import time
from typing import Callable, TypeVar, Optional, Any, Set
from enum import Enum

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ══════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════

class ErrorCategory(str, Enum):
    """错误分类"""
    RETRYABLE = "retryable"         # 可重试（5xx/429/网络错误）
    NON_RETRYABLE = "non_retryable" # 不重试（4xx/业务错误）
    UNKNOWN = "unknown"             # 未知（保守策略：重试1次）


class RetryExhaustedError(Exception):
    """重试耗尽错误"""
    def __init__(self, original_error: Exception, attempts: int, total_time_ms: float):
        self.original_error = original_error
        self.attempts = attempts
        self.total_time_ms = total_time_ms
        super().__init__(
            f"重试耗尽（{attempts}次，耗时{total_time_ms:.0f}ms），"
            f"最后错误: {type(original_error).__name__}: {original_error}"
        )


# ══════════════════════════════════════════════
# 错误分类器
# ══════════════════════════════════════════════

class ErrorClassifier:
    """
    错误分类器

    【分类原则】
    - 5xx/429/网络错误 → RETRYABLE（服务端问题，会恢复）
    - 4xx → NON_RETRYABLE（客户端问题，重试也没用）
    - 其他 → UNKNOWN（保守策略：重试1次）
    """

    # 可重试的错误类型名 / 关键词
    RETRYABLE_ERROR_NAMES: Set[str] = {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectionError",
        "TimeoutError",
        "ServiceUnavailableError",
        "RateLimitError",
        "InternalServerError",
    }

    RETRYABLE_HTTP_STATUS: Set[int] = {
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    }

    @classmethod
    def classify(cls, error: Exception) -> ErrorCategory:
        """
        分类一个异常

        【分类逻辑】
        1. 按 error 类型名精确匹配
        2. 按 error message 关键词模糊匹配
        3. 提取 HTTP status code 判断
        4. 兜底：UNKNOWN（重试1次）
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()

        # 1. 精确类型匹配
        if error_type in cls.RETRYABLE_ERROR_NAMES:
            return ErrorCategory.RETRYABLE

        # 2. 消息关键词匹配
        retryable_keywords = [
            "connection error",
            "timeout",
            "too many requests",
            "rate limit",
            "service unavailable",
            "internal server error",
            "bad gateway",
        ]
        for keyword in retryable_keywords:
            if keyword in error_msg:
                return ErrorCategory.RETRYABLE

        # 3. HTTP status code 检查
        if "status code: 4" in error_msg.replace(" ", "").replace("：", ":"):
            return ErrorCategory.NON_RETRYABLE

        # 4. 提取 http 状态码
        import re
        status_match = re.search(r'(?:status[=:]\s*)(\d{3})', error_msg)
        if status_match:
            status_code = int(status_match.group(1))
            if status_code in cls.RETRYABLE_HTTP_STATUS:
                return ErrorCategory.RETRYABLE
            if 400 <= status_code < 500:
                return ErrorCategory.NON_RETRYABLE

        # 5. 错误码1113（余额不足）→ 不重试
        if "1113" in error_msg or "余额不足" in error_msg:
            return ErrorCategory.NON_RETRYABLE

        # 6. 兜底
        return ErrorCategory.UNKNOWN

    @classmethod
    def should_retry(cls, error: Exception, attempt: int) -> bool:
        """
        判断是否应该重试

        【规则】
        - RETRYABLE: 始终重试（直到 max_retries）
        - NON_RETRYABLE: 不重试
        - UNKNOWN: 仅重试1次（保守策略）
        """
        category = cls.classify(error)

        if category == ErrorCategory.RETRYABLE:
            return True
        if category == ErrorCategory.NON_RETRYABLE:
            return False
        # UNKNOWN: 仅重试1次
        return attempt <= 1


# ══════════════════════════════════════════════
# 重试策略
# ══════════════════════════════════════════════

class RetryPolicy:
    """
    重试策略管理器

    【核心配置】
    - max_retries: 最大重试次数（不含首次调用）
    - base_delay: 基础延迟（秒）
    - max_delay: 最大单次延迟上限（秒），防退避到天文数字
    - jitter: 随机抖动系数（0~1），推荐 0.5
    - total_timeout: 总超时（秒），超时后不再重试

    【重试时间线示例】
    首次调用 → 失败(429)
      → 等待 1.0*(1+0.3)=1.3s → 第2次 → 失败(503)
      → 等待 2.0*(1+0.2)=2.4s → 第3次 → 成功 ✅
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: float = 0.5,
        total_timeout: float = 60.0,
    ):
        """
        初始化重试策略

        【参数】
        - max_retries: 最大重试次数（默认3）
        - base_delay: 基础延迟秒数（默认1.0）
        - max_delay: 最大延迟上限秒数（默认30）
        - jitter: 抖动系数（默认0.5 = 50%）
        - total_timeout: 总超时秒数（默认60）
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.total_timeout = total_timeout

        logger.info(
            "retry_policy_initialized",
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
            total_timeout=total_timeout,
        )

    async def execute(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs,
    ) -> T:
        """
        执行函数，失败时自动重试

        【参数】
        - func: 待执行的异步函数
        - *args, **kwargs: 传递给 func 的参数

        【返回】func 的成功返回值

        【抛出】RetryExhaustedError: 所有重试耗尽

        【示例】
        result = await policy.execute(
            llm_client.chat,
            prompt="hello",
            temperature=0.7
        )
        """
        last_error: Optional[Exception] = None
        start_time = time.time()

        for attempt in range(self.max_retries + 1):  # 0 = 首次调用
            try:
                # 检查总超时
                elapsed = time.time() - start_time
                if elapsed > self.total_timeout:
                    raise RetryExhaustedError(
                        original_error=last_error or Exception("total_timeout"),
                        attempts=attempt,
                        total_time_ms=elapsed * 1000,
                    )

                # 执行
                result = await func(*args, **kwargs)

                # 成功了
                if attempt > 0:
                    logger.info(
                        "retry_succeeded",
                        attempt=attempt,
                        total_attempts=attempt + 1,
                        elapsed_ms=(time.time() - start_time) * 1000,
                    )
                return result

            except Exception as e:
                last_error = e
                elapsed_ms = (time.time() - start_time) * 1000

                # 最后一次尝试，不重试
                if attempt >= self.max_retries:
                    logger.error(
                        "retry_exhausted",
                        attempts=attempt + 1,
                        total_time_ms=elapsed_ms,
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200],
                    )
                    raise RetryExhaustedError(
                        original_error=e,
                        attempts=attempt + 1,
                        total_time_ms=elapsed_ms,
                    )

                # 判断是否可重试
                category = ErrorClassifier.classify(e)

                if category == ErrorCategory.NON_RETRYABLE:
                    logger.warning(
                        "retry_skipped_non_retryable",
                        attempt=attempt,
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200],
                    )
                    raise  # 不重试，直接抛出

                # 计算延迟
                delay = self._calc_delay(attempt)
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    delay_ms=delay * 1000,
                    category=category.value,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                )

                await asyncio.sleep(delay)

        # 理论上不会到达这里
        raise RetryExhaustedError(
            original_error=last_error or Exception("unknown"),
            attempts=self.max_retries + 1,
            total_time_ms=(time.time() - start_time) * 1000,
        )

    def _calc_delay(self, attempt: int) -> float:
        """
        计算第 attempt 次重试的延迟

        【公式】delay = base_delay * 2^attempt * (1 + random() * jitter)

        【示例】
        base=1s, jitter=0.5:
        attempt=0: 1*1*(1+0.3)   = 1.3s
        attempt=1: 1*2*(1+0.4)   = 2.8s
        attempt=2: 1*4*(1+0.2)   = 4.8s
        """
        exponential = self.base_delay * (2 ** attempt)
        jitter_amount = exponential * self.jitter * random.random()
        delay = exponential + jitter_amount
        return min(delay, self.max_delay)


# ══════════════════════════════════════════════
# 便捷函数 & 装饰器
# ══════════════════════════════════════════════

def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.5,
):
    """
    重试装饰器（用于异步函数）

    【使用示例】
    @retry(max_retries=3, base_delay=1.0)
    async def call_llm(prompt: str):
        return await llm_client.chat(prompt)
    """
    policy = RetryPolicy(
        max_retries=max_retries,
        base_delay=base_delay,
        jitter=jitter,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await policy.execute(func, *args, **kwargs)
        return wrapper
    return decorator


# ══════════════════════════════════════════════
# 预配置实例（常用场景）
# ══════════════════════════════════════════════

class RetryPresets:
    """预配置的重试策略"""

    @staticmethod
    def llm_call() -> RetryPolicy:
        """LLM 调用重试（快速失败）"""
        return RetryPolicy(
            max_retries=3,
            base_delay=1.0,
            max_delay=10.0,
            jitter=0.5,
            total_timeout=30.0,
        )

    @staticmethod
    def external_api() -> RetryPolicy:
        """外部 API 调用重试（更耐心）"""
        return RetryPolicy(
            max_retries=5,
            base_delay=2.0,
            max_delay=30.0,
            jitter=0.5,
            total_timeout=60.0,
        )

    @staticmethod
    def quick() -> RetryPolicy:
        """快速重试（最多2次）"""
        return RetryPolicy(
            max_retries=2,
            base_delay=0.5,
            max_delay=5.0,
            jitter=0.3,
            total_timeout=10.0,
        )


# ══════════════════════════════════════════════
# 单例工厂
# ══════════════════════════════════════════════

_default_policy: Optional[RetryPolicy] = None


def get_retry_policy() -> RetryPolicy:
    """获取默认重试策略单例"""
    global _default_policy
    if _default_policy is None:
        _default_policy = RetryPresets.llm_call()
    return _default_policy
