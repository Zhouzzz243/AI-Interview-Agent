"""
护栏模块（Guard Module）- 三层输出校验，防异常状态/幻觉

【Java 类比】
类似 Spring Validation 的 @Valid + ConstraintValidator 组合，
或者网关层的 Request Validation Filter。

【三层校验体系】
┌─────────────────────────────────────────────┐
│ Layer 1: 白名单校验（Must-Pass）             │
│   - 阶段转换必须符合预定义的状态机            │
│   - 不允许的阶段跳转直接拦截                  │
│   - 类似「只读工具白名单」                    │
├─────────────────────────────────────────────┤
│ Layer 2: 参数校验（Should-Pass）             │
│   - 评分必须在 0-100 范围                    │
│   - 必须有5个维度的分数                       │
│   - 追问决策必须包含必要字段                  │
│   - 不通过 → 记录 warning + 返回默认值        │
├─────────────────────────────────────────────┤
│ Layer 3: 降级策略（Fallback）                │
│   - 校验失败不阻断流程，返回安全默认值         │
│   - 预算耗尽时构建优雅的降级响应               │
│   - 类似「兜底结案模板」                      │
└─────────────────────────────────────────────┘

【设计决策】
为什么不硬阻断？
- 面试是实时交互场景，硬阻断会让用户看到错误页面
- Guard 的职责是「不要让错误数据污染系统」，不是「阻止用户使用」
- 降级策略: 校验失败 → 返回安全默认值 + 记录告警日志

【使用示例】
from app.harness.guard import InterviewGuard

guard = InterviewGuard()

# 校验阶段转换
if not guard.validate_phase_transition(current_phase, new_phase):
    new_phase = guard.get_safe_phase(current_phase)

# 校验评分结果
score = guard.sanitize_score(raw_score)  # 确保在0-100之间

# 校验追问决策
decision = guard.validate_followup_decision(raw_decision)
"""

from typing import Dict, Any, Optional, Tuple
from enum import Enum

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════
# 面试阶段定义（本地副本，避免循环导入）
# ══════════════════════════════════════════════

class GuardPhase(str, Enum):
    """Guard 层使用的面试阶段枚举"""
    SELF_INTRO = "self_introduction"
    INTERNSHIP_QA = "internship_qa"
    PROJECT_QA = "project_qa"
    EIGHT_PART_QA = "eight_part_qa"
    CHAT_MODE = "chat_mode"
    FINAL_SCORE = "final_score"
    END = "end"


class GuardDecision(str, Enum):
    """Guard 层使用的追问决策枚举"""
    FOLLOW_UP = "follow_up"
    INTEREST_FOLLOW_UP = "interest_follow_up"
    NEXT_QUESTION = "next_question"
    PHASE_SWITCH = "phase_switch"
    BUDGET_EXHAUSTED = "budget_exhausted"


# ══════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════

class GuardResult:
    """Guard 校验结果"""

    def __init__(self, passed: bool, reason: str = "", sanitized_value: Any = None):
        self.passed = passed
        self.reason = reason
        self.sanitized_value = sanitized_value

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "BLOCKED"
        return f"GuardResult({status}, reason='{self.reason}')"


# ══════════════════════════════════════════════
# 护栏管理器
# ══════════════════════════════════════════════

class InterviewGuard:
    """
    面试护栏管理器

    【核心职责】
    1. 阶段转换白名单校验（防非法状态跳转）
    2. 评分结果参数校验（防越界/缺失）
    3. 追问决策字段校验（防格式错误）
    4. 降级策略（校验失败时返回安全值）

    【设计哲学】
    - 白名单 > 黑名单: 预定义"什么可以"，未知的一律拦截
    - 降级 > 阻断: 校验失败时返回安全默认值而非抛异常
    - 日志 > 静默: 每次拦截都记录日志，方便排查
    """

    # ── 第一层：阶段转换白名单 ──

    ALLOWED_PHASE_TRANSITIONS: Dict[GuardPhase, Tuple[GuardPhase, ...]] = {
        # 自我介绍的下一阶段可以是 → 实习问答 或 闲聊（如果候选人没有实习经历）
        GuardPhase.SELF_INTRO: (
            GuardPhase.INTERNSHIP_QA,
            GuardPhase.PROJECT_QA,
            GuardPhase.CHAT_MODE,
            GuardPhase.FINAL_SCORE,
        ),
        # 实习问答可以 → 追问自己 或 进入项目问答 或 闲聊
        GuardPhase.INTERNSHIP_QA: (
            GuardPhase.INTERNSHIP_QA,   # 追问还在本阶段
            GuardPhase.PROJECT_QA,
            GuardPhase.CHAT_MODE,
            GuardPhase.FINAL_SCORE,
        ),
        # 项目问答可以 → 追问自己 或 进入八股文 或 闲聊
        GuardPhase.PROJECT_QA: (
            GuardPhase.PROJECT_QA,      # 追问还在本阶段
            GuardPhase.EIGHT_PART_QA,
            GuardPhase.CHAT_MODE,
            GuardPhase.FINAL_SCORE,
        ),
        # 八股文可以 → 追问自己 或 进入闲聊
        GuardPhase.EIGHT_PART_QA: (
            GuardPhase.EIGHT_PART_QA,   # 追问还在本阶段
            GuardPhase.CHAT_MODE,
            GuardPhase.FINAL_SCORE,
        ),
        # 闲聊 → 终评
        GuardPhase.CHAT_MODE: (
            GuardPhase.CHAT_MODE,       # 闲聊中可以继续闲聊
            GuardPhase.FINAL_SCORE,
        ),
        # 终评 → 结束（终评后不能回到其他阶段）
        GuardPhase.FINAL_SCORE: (
            GuardPhase.END,
        ),
        # 结束是终态，不能转到任何阶段
        GuardPhase.END: (),
    }

    # ── 第二层：评分参数约束 ──

    SCORE_MIN = 0
    SCORE_MAX = 100
    REQUIRED_SCORE_DIMENSIONS = {
        "practice_experience",
        "technical_knowledge",
        "communication",
        "potential",
        "attitude",
    }
    DEFAULT_SAFE_SCORE = 70

    # ── 第三层：追问决策约束 ──

    VALID_DECISIONS = {d.value for d in GuardDecision}
    VALID_DECISIONS.add("next_question")  # 兼容旧格式
    DEFAULT_SAFE_DECISION = "next_question"

    def __init__(self):
        logger.info("guard_initialized", phase_count=len(self.ALLOWED_PHASE_TRANSITIONS))

    # ── 公共 API ──

    def validate_phase_transition(
        self,
        current_phase: str,
        new_phase: str,
    ) -> GuardResult:
        """
        校验阶段转换是否合法

        【返回】
        - passed=True:  转换合法
        - passed=False: 转换非法，sanitized_value 为安全兜底阶段

        【示例】
        guard.validate_phase_transition("final_score", "self_intro")
        # → GuardResult(BLOCKED, reason="...", sanitized_value="final_score")
        """
        try:
            current = GuardPhase(current_phase)
            new = GuardPhase(new_phase)
        except ValueError as e:
            # 按优先级选安全兜底: 保留当前阶段 > 默认开场阶段
            safe = current_phase if current_phase in (p.value for p in GuardPhase) else "self_introduction"
            return GuardResult(
                passed=False,
                reason=f"无效的阶段值: {e}",
                sanitized_value=safe,
            )

        # 自转换永远合法（追问/同阶段出新题）
        if current == new:
            return GuardResult(passed=True, reason="self_transition_allowed")

        allowed = self.ALLOWED_PHASE_TRANSITIONS.get(current, ())

        if new in allowed:
            return GuardResult(passed=True, reason="transition_allowed")

        # 非法转换 → 返回安全的兜底阶段
        safe_phase = self._get_safe_next_phase(current)
        reason = (
            f"非法阶段转换: {current.value} → {new.value}，"
            f"允许转换到: {[p.value for p in allowed]}，"
            f"降级为: {safe_phase.value}"
        )

        logger.warning("guard_phase_blocked", reason=reason)
        return GuardResult(passed=False, reason=reason, sanitized_value=safe_phase.value)

    def sanitize_score(
        self,
        score: Any,
        default: int = DEFAULT_SAFE_SCORE,
    ) -> Tuple[int, bool]:
        """
        净化评分结果

        【校验规则】
        1. 必须是数值类型
        2. 必须在 [0, 100] 范围内

        【返回】(sanitized_score, is_valid)
        - is_valid=True:  原始值合法
        - is_valid=False: 已被修正，记录警告日志
        """
        try:
            score_val = float(score)
        except (TypeError, ValueError):
            logger.warning(
                "guard_score_invalid_type",
                raw_value=str(score),
                fallback=default,
            )
            return default, False

        if score_val < self.SCORE_MIN:
            logger.warning(
                "guard_score_too_low",
                raw_value=score_val,
                clamped_to=self.SCORE_MIN,
            )
            return self.SCORE_MIN, False

        if score_val > self.SCORE_MAX:
            logger.warning(
                "guard_score_too_high",
                raw_value=score_val,
                clamped_to=self.SCORE_MAX,
            )
            return self.SCORE_MAX, False

        return int(score_val), True

    def validate_followup_decision(
        self,
        decision_data: dict,
    ) -> dict:
        """
        校验追问决策结果

        【校验规则】
        1. decision 字段必须存在且在合法值集合中
        2. reason 字段缺失时补默认值
        3. confidence 字段缺失/越界时 clamp 到 [0, 1]

        【返回】净化后的 decision dict（不修改原对象）
        """
        if not isinstance(decision_data, dict):
            logger.warning(
                "guard_decision_invalid_type",
                raw_type=type(decision_data).__name__,
            )
            return self._default_decision("decision数据格式错误")

        cleaned = dict(decision_data)  # 不修改原对象
        modified = False

        # 校验 decision 字段
        raw_decision = cleaned.get("decision", "")
        if raw_decision not in self.VALID_DECISIONS:
            logger.warning(
                "guard_decision_invalid_value",
                raw_value=raw_decision,
                fallback=self.DEFAULT_SAFE_DECISION,
            )
            cleaned["decision"] = self.DEFAULT_SAFE_DECISION
            modified = True

        # 校验 reason 字段
        if not cleaned.get("reason"):
            cleaned["reason"] = "追问决策降级（原因为空）"
            modified = True

        # 校验 confidence 字段
        confidence = cleaned.get("confidence")
        if confidence is not None:
            try:
                conf_val = float(confidence)
                if conf_val < 0.0:
                    cleaned["confidence"] = 0.0
                    modified = True
                elif conf_val > 1.0:
                    cleaned["confidence"] = 1.0
                    modified = True
            except (TypeError, ValueError):
                cleaned["confidence"] = 0.5
                modified = True
        else:
            cleaned["confidence"] = 0.5
            modified = True

        if modified:
            logger.info(
                "guard_decision_sanitized",
                original=str(decision_data)[:200],
                cleaned=str(cleaned)[:200],
            )

        return cleaned

    def validate_scoring_dimensions(
        self,
        dimensions: dict,
    ) -> dict:
        """
        校验评分维度是否完整

        【校验规则】
        1. 必须有5个必需维度
        2. 每个维度的分数必须在 [0, 100]
        3. 缺失维度 → 补默认值 70

        【返回】净化后的 dimensions dict
        """
        if not isinstance(dimensions, dict):
            logger.warning("guard_dimensions_invalid_type")
            return {dim: self.DEFAULT_SAFE_SCORE for dim in self.REQUIRED_SCORE_DIMENSIONS}

        cleaned = {}
        missing_dims = []

        for dim in self.REQUIRED_SCORE_DIMENSIONS:
            if dim in dimensions:
                score, valid = self.sanitize_score(dimensions[dim])
                if not valid:
                    logger.info("guard_dimension_score_sanitized", dimension=dim)
                cleaned[dim] = score
            else:
                cleaned[dim] = self.DEFAULT_SAFE_SCORE
                missing_dims.append(dim)

        if missing_dims:
            logger.warning(
                "guard_dimensions_missing",
                missing=missing_dims,
                fallback_value=self.DEFAULT_SAFE_SCORE,
            )

        # 保留合法额外维度（如 chat_attitude）
        for key, value in dimensions.items():
            if key not in self.REQUIRED_SCORE_DIMENSIONS:
                score, _ = self.sanitize_score(value, self.DEFAULT_SAFE_SCORE)
                cleaned[key] = score

        return cleaned

    def validate_final_score_result(
        self,
        result: dict,
    ) -> dict:
        """
        校验最终评分结果

        【校验规则】
        1. final_score 在 [0, 100]
        2. dimension_scores 包含5个维度
        3. level 在 A/B/C/D 中
        4. 缺失字段 → 补安全默认值

        【返回】净化后的结果 dict
        """
        if not isinstance(result, dict):
            logger.warning("guard_final_score_invalid_type")
            return self._default_final_score()

        cleaned = dict(result)

        # 校验 final_score
        final_score, valid = self.sanitize_score(
            cleaned.get("final_score", 0), default=0
        )
        if not valid:
            logger.info("guard_final_score_sanitized")
        cleaned["final_score"] = final_score

        # 校验 level
        valid_levels = {"A", "B", "C", "D"}
        if cleaned.get("level", "") not in valid_levels:
            # 根据分数推算等级
            if final_score >= 85:
                cleaned["level"] = "A"
            elif final_score >= 70:
                cleaned["level"] = "B"
            elif final_score >= 60:
                cleaned["level"] = "C"
            else:
                cleaned["level"] = "D"
            logger.info(
                "guard_level_inferred",
                score=final_score,
                level=cleaned["level"],
            )

        # 校验 dimensions
        if "dimension_scores" in cleaned:
            cleaned["dimension_scores"] = self.validate_scoring_dimensions(
                cleaned["dimension_scores"]
            )
        else:
            cleaned["dimension_scores"] = self.validate_scoring_dimensions({})

        # 补缺失字段
        if "summary" not in cleaned:
            cleaned["summary"] = "面试已完成，请查看详细评分。"
        if "strengths" not in cleaned:
            cleaned["strengths"] = []
        if "weaknesses" not in cleaned:
            cleaned["weaknesses"] = []
        if "suggestions" not in cleaned:
            cleaned["suggestions"] = []

        return cleaned

    # ── 私有方法 ──

    def _get_safe_next_phase(self, current: GuardPhase) -> GuardPhase:
        """
        获取安全的下一阶段（兜底策略）

        【策略】
        优先选择阶段列表中的第一个合法下一阶段。
        如果当前是 END（终态），保持 END。
        """
        allowed = self.ALLOWED_PHASE_TRANSITIONS.get(current, ())
        if allowed:
            return allowed[0]
        return GuardPhase.END

    def _default_decision(self, reason: str = "") -> dict:
        """构建默认的追问决策"""
        return {
            "decision": self.DEFAULT_SAFE_DECISION,
            "reason": reason or "Guard校验降级",
            "confidence": 0.5,
        }

    def _default_final_score(self) -> dict:
        """构建默认的最终评分"""
        return {
            "final_score": 0,
            "level": "C",
            "summary": "评分数据异常，已使用默认值",
            "dimension_scores": {
                dim: self.DEFAULT_SAFE_SCORE
                for dim in self.REQUIRED_SCORE_DIMENSIONS
            },
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
        }

    # ── 便捷方法 ──

    def quick_check_score(self, raw_score: Any) -> int:
        """一行调用净化评分"""
        score, _ = self.sanitize_score(raw_score)
        return score

    def quick_check_decision(self, raw_decision: dict) -> dict:
        """一行调用净化决策"""
        return self.validate_followup_decision(raw_decision)


# ══════════════════════════════════════════════
# 单例工厂
# ══════════════════════════════════════════════

_guard_instance: Optional["InterviewGuard"] = None


def get_interview_guard() -> InterviewGuard:
    """获取全局 InterviewGuard 单例"""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = InterviewGuard()
    return _guard_instance


def reset_guard_instance():
    """重置单例（测试用）"""
    global _guard_instance
    _guard_instance = None
