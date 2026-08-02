"""
预算管理器（Budget Manager）- 三层预算控制，防烧钱/死循环

【Java 类比】
类似 Resilience4j 的 RateLimiter + Bulkhead 组合，或者
Spring Cloud Gateway 的 RequestSizeGatewayFilter。

【三层预算设计】
┌─────────────────────────────────────────────┐
│ Layer 3: SessionBudget（会话预算）           │
│   - 控制：整个面试的总 token 和总轮次         │
│   - 耗尽：优雅降级，返回结案响应              │
│   - 粒度：用户级                              │
├─────────────────────────────────────────────┤
│ Layer 2: TurnBudget（轮次预算）              │
│   - 控制：一次 chat() 调用中的 LLM 调用次数   │
│   - 耗尽：跳过后续 Skill，直接出下一题        │
│   - 粒度：请求级                              │
├─────────────────────────────────────────────┤
│ Layer 1: RoundBudget（单轮预算）             │
│   - 控制：单次 LLM 调用的 token 上限          │
│   - 耗尽：截断返回内容                        │
│   - 粒度：调用级                              │
└─────────────────────────────────────────────┘

【设计决策】
为什么三层而不是两层/四层？
- Round  控单次调用（防单次爆炸）
- Turn   控单次请求（防单轮烧钱）
- 两层不够：Round 和 Turn 是不同的控制目标
- 四层没必要：再加"Phase"层是过度设计，当前业务无阶段级预算需求

【使用示例】
from app.harness.budget import InterviewBudget

budget = InterviewBudget()

# 每次 chat() 前检查
if not budget.can_continue(session_id):
    return budget.build_degraded_response()

# 每次 LLM 调用后记账
budget.track_llm_call(session_id, tokens_used=1500)

# 检查当前预算状态
status = budget.get_status(session_id)
print(status.summary())  # "已用: 3200/50000 tokens, 3/15 题"
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from enum import Enum

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════

class BudgetExhaustedReason(str, Enum):
    """预算耗尽原因"""
    ROUND_TOKENS = "round_tokens"       # 单轮 token 超限
    TURN_LLM_CALLS = "turn_llm_calls"   # 单轮 LLM 调用次数超限
    SESSION_TOKENS = "session_tokens"   # 会话总 token 超限
    SESSION_QUESTIONS = "session_questions"  # 会话题目数超限


@dataclass
class BudgetStatus:
    """预算状态快照"""
    session_id: str
    # Round 级
    round_tokens_used: int = 0
    round_max_tokens: int = 4000
    # Turn 级
    turn_llm_calls: int = 0
    turn_max_llm_calls: int = 5
    # Session 级
    session_tokens_used: int = 0
    session_max_tokens: int = 50000
    questions_asked: int = 0
    max_questions: int = 15
    # 元信息
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    exhausted_reason: Optional[BudgetExhaustedReason] = None

    @property
    def is_exhausted(self) -> bool:
        """任意一层预算耗尽即为 exhausted"""
        return self.exhausted_reason is not None

    @property
    def session_token_pct(self) -> float:
        """会话 token 使用百分比"""
        return self.session_tokens_used / self.session_max_tokens * 100 if self.session_max_tokens > 0 else 0

    @property
    def question_pct(self) -> float:
        """题目使用百分比"""
        return self.questions_asked / self.max_questions * 100 if self.max_questions > 0 else 0

    def summary(self) -> str:
        """可读摘要"""
        parts = [
            f"session_tokens={self.session_tokens_used}/{self.session_max_tokens}",
            f"questions={self.questions_asked}/{self.max_questions}",
            f"turn_llm_calls={self.turn_llm_calls}/{self.turn_max_llm_calls}",
        ]
        if self.exhausted_reason:
            parts.append(f"EXHAUSTED({self.exhausted_reason.value})")
        return " | ".join(parts)


# ══════════════════════════════════════════════
# 预算管理器
# ══════════════════════════════════════════════

class InterviewBudget:
    """
    面试预算管理器

    【核心职责】
    1. 三层预算追踪（Round/Turn/Session）
    2. 预算耗尽时触发降级策略
    3. 每轮自动重置 Turn 级计数器

    【并发安全】
    当前实现依赖 asyncio 单线程协作式调度保证安全。
    - get_or_create 的 if-not-in-then-create 是非原子操作
    - 但在 asyncio 无 await 的场景下是安全的
    - 如果将来加了 await（如异步读配置），需加 asyncio.Lock

    【已知脆弱点】
    - track_llm_call 和 save_snapshot 不在同一事务
    - 极端崩溃时可能丢一次记账
    - 影响：最多多花一轮预算，不造成资损，可接受
    """

    # ── 默认值（可被 InterviewSettings 覆盖）──
    DEFAULT_ROUND_MAX_TOKENS = 4000
    DEFAULT_TURN_MAX_LLM_CALLS = 5
    DEFAULT_SESSION_MAX_TOKENS = 50000
    DEFAULT_MAX_QUESTIONS = 15

    def __init__(
        self,
        round_max_tokens: int = DEFAULT_ROUND_MAX_TOKENS,
        turn_max_llm_calls: int = DEFAULT_TURN_MAX_LLM_CALLS,
        session_max_tokens: int = DEFAULT_SESSION_MAX_TOKENS,
        max_questions: int = DEFAULT_MAX_QUESTIONS,
    ):
        """
        初始化预算管理器

        【参数】
        - round_max_tokens:   单次 LLM 调用最大 token
        - turn_max_llm_calls: 单次 chat() 最多 LLM 调用次数
        - session_max_tokens: 整个面试最大 token
        - max_questions:      最多出题数
        """
        self._round_max_tokens = round_max_tokens
        self._turn_max_llm_calls = turn_max_llm_calls
        self._session_max_tokens = session_max_tokens
        self._max_questions = max_questions

        # 内存存储（非持久化，重启丢失——但面试场景可接受）
        self._budgets: Dict[str, BudgetStatus] = {}

        logger.info(
            "budget_initialized",
            round_max_tokens=round_max_tokens,
            turn_max_llm_calls=turn_max_llm_calls,
            session_max_tokens=session_max_tokens,
            max_questions=max_questions,
        )

    # ── 公共 API ──

    def get_or_create(self, session_id: str) -> BudgetStatus:
        """
        获取或创建会话的预算状态

        【并发注意】
        if-not-in-then-create 在 asyncio 单线程下安全，
        但如果加了 await 需改为 setdefault 模式或加锁。
        """
        if session_id not in self._budgets:
            self._budgets[session_id] = BudgetStatus(
                session_id=session_id,
                round_max_tokens=self._round_max_tokens,
                turn_max_llm_calls=self._turn_max_llm_calls,
                session_max_tokens=self._session_max_tokens,
                max_questions=self._max_questions,
            )
            logger.debug("budget_created", session_id=session_id)
        return self._budgets[session_id]

    def get_status(self, session_id: str) -> Optional[BudgetStatus]:
        """获取预算状态（可能为 None）"""
        return self._budgets.get(session_id)

    def can_continue(self, session_id: str) -> bool:
        """
        检查是否可以继续执行

        【检查顺序】
        1. Session 级：总 token / 总题目数
        2. Turn 级：本轮 LLM 调用次数
        3. Round 级：在 track_llm_call 时检查
        """
        budget = self.get_or_create(session_id)

        # Session 级检查
        if budget.session_tokens_used >= budget.session_max_tokens:
            budget.exhausted_reason = BudgetExhaustedReason.SESSION_TOKENS
            logger.warning(
                "budget_exhausted_session_tokens",
                session_id=session_id,
                used=budget.session_tokens_used,
                max=budget.session_max_tokens,
            )
            return False

        if budget.questions_asked >= budget.max_questions:
            budget.exhausted_reason = BudgetExhaustedReason.SESSION_QUESTIONS
            logger.warning(
                "budget_exhausted_session_questions",
                session_id=session_id,
                asked=budget.questions_asked,
                max=budget.max_questions,
            )
            return False

        # Turn 级检查
        if budget.round_tokens_used >= budget.round_max_tokens:
            budget.exhausted_reason = BudgetExhaustedReason.ROUND_TOKENS
            logger.warning(
                "budget_exhausted_round_tokens",
                session_id=session_id,
                used=budget.round_tokens_used,
                max=budget.round_max_tokens,
            )
            return False

        # Turn 级检查
        if budget.turn_llm_calls >= budget.turn_max_llm_calls:
            budget.exhausted_reason = BudgetExhaustedReason.TURN_LLM_CALLS
            logger.warning(
                "budget_exhausted_turn_llm_calls",
                session_id=session_id,
                calls=budget.turn_llm_calls,
                max=budget.turn_max_llm_calls,
            )
            return False

        return True

    def track_llm_call(
        self,
        session_id: str,
        tokens_used: int = 0,
        increment_question: bool = False,
    ) -> BudgetStatus:
        """
        记录一次 LLM 调用

        【参数】
        - tokens_used: 本次调用消耗的 token 数
        - increment_question: 是否是新题（非追问则 +1）

        【返回值】更新后的 BudgetStatus

        【副作用】
        - round_tokens_used 重置
        - turn_llm_calls +1
        - session_tokens_used += tokens_used
        - questions_asked 可能 +1
        """
        budget = self.get_or_create(session_id)

        # Round 级：检查单次调用是否超限
        budget.round_tokens_used = tokens_used
        if tokens_used > budget.round_max_tokens:
            logger.warning(
                "budget_round_exceeded",
                session_id=session_id,
                tokens_used=tokens_used,
                round_max=budget.round_max_tokens,
                hint="单次LLM调用超过Round预算上限",
            )
            budget.exhausted_reason = BudgetExhaustedReason.ROUND_TOKENS

        # Turn 级
        budget.turn_llm_calls += 1

        # Session 级
        budget.session_tokens_used += tokens_used
        if increment_question:
            budget.questions_asked += 1

        budget.last_updated = time.time()

        logger.debug(
            "budget_tracked_llm_call",
            session_id=session_id,
            tokens_used=tokens_used,
            turn_calls=budget.turn_llm_calls,
            session_tokens=budget.session_tokens_used,
            questions=budget.questions_asked,
        )

        # 调用后重新检查是否耗尽
        if budget.session_tokens_used >= budget.session_max_tokens:
            budget.exhausted_reason = BudgetExhaustedReason.SESSION_TOKENS
        elif budget.turn_llm_calls >= budget.turn_max_llm_calls:
            budget.exhausted_reason = BudgetExhaustedReason.TURN_LLM_CALLS

        return budget

    def reset_turn(self, session_id: str):
        """
        重置 Turn 级计数器（每次 chat() 开始时调用）

        【注意】不重置 Session 级计数器
        """
        if session_id in self._budgets:
            budget = self._budgets[session_id]
            budget.turn_llm_calls = 0
            budget.exhausted_reason = None
            budget.last_updated = time.time()
            logger.debug("budget_turn_reset", session_id=session_id)

    def cleanup(self, session_id: str):
        """清理会话预算（面试结束后调用）"""
        if session_id in self._budgets:
            budget = self._budgets.pop(session_id)
            logger.info(
                "budget_cleaned_up",
                session_id=session_id,
                final_summary=budget.summary(),
            )
        else:
            logger.debug("budget_cleanup_skip_not_found", session_id=session_id)

    def cleanup_stale(self, idle_timeout_seconds: int = 7200) -> int:
        """
        清理超时的预算记录（定期调用，防止内存泄漏）

        【参数】
        - idle_timeout_seconds: 空闲超时（默认 2 小时）

        【返回】清理的记录数
        """
        now = time.time()
        stale_ids = [
            sid for sid, budget in self._budgets.items()
            if now - budget.last_updated > idle_timeout_seconds
        ]
        for sid in stale_ids:
            self._budgets.pop(sid, None)
        if stale_ids:
            logger.info(
                "budget_cleanup_stale",
                cleaned_count=len(stale_ids),
                remaining=len(self._budgets),
            )
        return len(stale_ids)

    def build_degraded_response(
        self,
        session_id: str,
        last_score: int = 70,
        last_feedback: str = "面试已结束",
    ) -> Dict[str, Any]:
        """
        构建预算耗尽时的降级响应

        【设计理念】
        不硬截断——返回优雅的降级响应，让前端能正常展示。
        比直接抛异常好，比再调 LLM 便宜（预算已耗尽）。

        【返回格式】与 chat() 的返回格式对齐
        """
        budget = self.get_or_create(session_id)
        reason = budget.exhausted_reason.value if budget.exhausted_reason else "unknown"

        logger.info(
            "budget_degraded_response_built",
            session_id=session_id,
            reason=reason,
            summary=budget.summary(),
        )

        return {
            "code": 200,
            "data": {
                "score": last_score,
                "feedback": f"[预算耗尽: {reason}] {last_feedback}",
                "nextQuestion": "",
                "phase": "final_score",
                "isFollowUp": False,
                "questionCount": budget.questions_asked,
                "remainingQuestions": 0,
                "decision": {
                    "decision": "budget_exhausted",
                    "reason": f"预算耗尽（{reason}），面试自动结束",
                    "confidence": 1.0,
                },
            },
        }

    # ── 便捷方法 ──

    def estimate_tokens(self, text: str) -> int:
        """
        快速估算 token 数

        【简化规则】中文: ~1.5 字符/token, 英文: ~4 字符/token
        实际项目应使用 tiktoken cl100k_base 精确计算
        """
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    @property
    def active_sessions(self) -> int:
        """当前活跃会话数"""
        return len(self._budgets)


# ══════════════════════════════════════════════
# 单例工厂
# ══════════════════════════════════════════════

_budget_instance: Optional[InterviewBudget] = None


def get_interview_budget() -> InterviewBudget:
    """获取全局 InterviewBudget 单例"""
    global _budget_instance
    if _budget_instance is None:
        _budget_instance = InterviewBudget()
    return _budget_instance


def reset_budget_instance():
    """重置单例（测试用）"""
    global _budget_instance
    _budget_instance = None
