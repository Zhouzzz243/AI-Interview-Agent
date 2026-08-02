"""
断点恢复模块 — 面试状态持久化与恢复

【设计理念】
候选人刷新页面或断网后，Redis 中的 SessionState 不会丢失。
Checkpoint 层提供：
1. 检查某个 session 是否可以恢复
2. 恢复 session 时校验完整性
3. 超时 session 自动标记为过期

【核心场景】
- 用户刷新页面 → 前端请求 /resume → 从 Redis 恢复状态
- 面试中断超过 30 分钟 → 标记为 expired
- 状态不完整的 session → 返回安全默认值

【Java 类比】
类似 Spring Session + Redis 的 session 持久化机制。
"""

import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CheckpointState:
    """可恢复的面试状态快照"""
    session_id: str
    phase: str
    question_count: int = 0
    follow_up_budget: int = 5
    last_active: float = 0.0
    is_complete: bool = False
    is_expired: bool = False

    @property
    def idle_seconds(self) -> float:
        """距上次活动的秒数"""
        if self.last_active > 0:
            return time.time() - self.last_active
        return 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "question_count": self.question_count,
            "follow_up_budget": self.follow_up_budget,
            "idle_seconds": round(self.idle_seconds, 0),
            "is_complete": self.is_complete,
            "is_expired": self.is_expired,
        }

    def to_resume_response(self) -> dict:
        """
        构建前端恢复面试需要的响应数据

        【用途】前端调用 /resume 时返回此结构
        """
        if self.is_expired or self.is_complete:
            return {
                "can_resume": False,
                "reason": "expired" if self.is_expired else "completed",
                "session_id": self.session_id,
            }

        return {
            "can_resume": True,
            "session_id": self.session_id,
            "phase": self.phase,
            "question_count": self.question_count,
            "remaining_questions": max(0, 15 - self.question_count),
            "idle_seconds": round(self.idle_seconds, 0),
        }


class CheckpointManager:
    """
    断点恢复管理器

    【职责】
    1. 从 Redis SessionState 构建可恢复的状态快照
    2. 判断会话是否可恢复（未过期、未完成）
    3. 处理恢复失败的降级逻辑

    【超时策略】
    - 默认 30 分钟无活动 → 标记为过期
    - 过期后清理 budget 并保留历史记录
    """

    DEFAULT_IDLE_TIMEOUT = 1800  # 30 分钟

    def __init__(self, idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT):
        self._idle_timeout = idle_timeout_seconds

    def build_checkpoint(
        self,
        session_id: str,
        session_state: dict,
    ) -> CheckpointState:
        """
        从 Redis session 数据构建快照

        【参数】
        - session_id: 会话 ID
        - session_state: 从 Redis 获取的原始 session 数据

        【返回】CheckpointState（总是成功，缺失字段用默认值）
        """
        if not session_state:
            return CheckpointState(
                session_id=session_id,
                phase="unknown",
                is_expired=True,
            )

        # 解析时间戳
        last_active = 0.0
        raw_last_active = session_state.get("last_active", "")
        if raw_last_active:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(raw_last_active)
                last_active = dt.timestamp()
            except (ValueError, TypeError):
                pass

        # 检查是否完成
        status = session_state.get("status", "active")
        is_complete = status in ("completed", "ended")

        # 检查是否过期
        phase = session_state.get("phase", "self_introduction")
        is_expired = False
        if last_active > 0:
            idle = time.time() - last_active
            if idle > self._idle_timeout:
                is_expired = True
                logger.info(
                    "checkpoint_session_expired",
                    session_id=session_id,
                    idle_seconds=round(idle),
                    timeout=self._idle_timeout,
                )

        return CheckpointState(
            session_id=session_id,
            phase=phase,
            question_count=session_state.get("question_count", 0),
            follow_up_budget=session_state.get("follow_up_budget", 5),
            last_active=last_active,
            is_complete=is_complete,
            is_expired=is_expired,
        )

    def can_resume(self, checkpoint: CheckpointState) -> bool:
        """判断是否可以恢复"""
        return not checkpoint.is_expired and not checkpoint.is_complete

    def validate_recovery(
        self,
        checkpoint: CheckpointState,
        expected_phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        校验恢复请求的合法性

        【返回】
        {
            "valid": bool,
            "reason": str,       # 不合法时的原因
            "checkpoint": dict,  # 当前快照
        }
        """
        if checkpoint.is_expired:
            return {
                "valid": False,
                "reason": f"会话已过期（空闲 {round(checkpoint.idle_seconds)} 秒）",
                "checkpoint": checkpoint.to_dict(),
            }

        if checkpoint.is_complete:
            return {
                "valid": False,
                "reason": "会话已完成",
                "checkpoint": checkpoint.to_dict(),
            }

        if expected_phase and checkpoint.phase != expected_phase:
            logger.warning(
                "checkpoint_phase_mismatch",
                expected=expected_phase,
                actual=checkpoint.phase,
            )

        return {
            "valid": True,
            "reason": "ok",
            "checkpoint": checkpoint.to_dict(),
        }


# ── 全局单例 ──

_checkpoint_instance: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    global _checkpoint_instance
    if _checkpoint_instance is None:
        _checkpoint_instance = CheckpointManager()
    return _checkpoint_instance
