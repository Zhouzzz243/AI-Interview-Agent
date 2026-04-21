"""
闲聊模式处理器 Skill（Step 9 补充）

【职责】
面试过程中的"放松/鼓励"环节，在以下场景触发：
1. 候选人表现优秀(score持续>80) → 奖励放松
2. 候选人表现较差(score持续<60) → 鼓励安慰
3. 接近尾声(question_count接近上限) → 转入收尾闲聊
4. 面试官主动切换到闲聊模式

【与正式评分的区别】
- 闲聊回答不记入正式成绩（不影响最终总分）
- 但会影响 attitude(积极态度) 维度的启发式评估
- 目的是让候选人放松、展现真实性格、收集额外信息

【调用时机】
由 Orchestrator 的 chat() 方法或自动触发逻辑调用
"""

import random
from typing import Any, Dict, List, Optional

from app.skills.base_skill import BaseSkill, SkillResult
from app.tools.llm_client import LLMClient
from app.infrastructure.logger import get_logger
from app.api.schemas import InterviewPhase
from app.prompts.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_TOPIC_PROMPT,
    CHAT_EVALUATION_PROMPT,
)

logger = get_logger(__name__)


class ChatModeHandlerSkill(BaseSkill):
    """
    闲聊模式处理器
    
    【话题库】6大类，每类有预设模板 + LLM动态生成两种方式
    【触发条件】4种场景（表现好/差/接近尾声/手动切换）
    """

    def __init__(self):
        super().__init__()
        self._llm = LLMClient()

        self._chat_topics = [
            {
                "topic": "学习方法",
                "keywords": ["学习", "技术成长", "自学", "教程"],
                "template": "你是怎么学习新技术的？能分享下你的学习方法或者最近在学习什么吗？",
                "category": "learning"
            },
            {
                "topic": "职业规划",
                "keywords": ["职业", "目标", "方向", "未来"],
                "template": "未来3年你的职业目标是什么？希望在哪些技术方向上深入发展？",
                "category": "career"
            },
            {
                "topic": "团队协作",
                "keywords": ["团队", "协作", "沟通", "合作"],
                "template": "你更喜欢独立工作还是团队协作？能说说你在团队合作中的角色和感受吗？",
                "category": "teamwork"
            },
            {
                "topic": "技术趋势",
                "keywords": ["趋势", "新技术", "AI", "前沿"],
                "template": "最近关注什么新技术或行业趋势？对 AI 辅助开发有什么看法？",
                "category": "trends"
            },
            {
                "topic": "开源贡献",
                "keywords": ["开源", "GitHub", "社区", "贡献"],
                "template": "有参与过开源项目或者技术社区吗？平时怎么获取技术资讯的？",
                "category": "opensource"
            },
            {
                "topic": "面试反馈",
                "keywords": ["体验", "感受", "建议", "想法"],
                "template": "今天的面试体验怎么样？有什么想聊的吗？或者对我们公司有什么想了解的？",
                "category": "feedback"
            },
        ]

    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        await super().validate(session_id, context)
        
        required = ["phase"]
        for field in required:
            if field not in context:
                raise ValueError(f"需要提供 {field}")

    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行闲聊处理
        
        【参数说明】
        - phase: 当前阶段（必须为 CHAT_MODE）
        - trigger_reason: 触发原因 (good_performance/poor_performance/near_end/manual)
        - recent_scores: 最近N轮得分列表
        - question_count: 已出题目数
        - resume_data: 简历数据（用于个性化话题）
        - user_answer: 用户上一轮的回答（如果有）
        """
        phase = context.get("phase")
        trigger_reason = kwargs.get("trigger_reason", "manual")
        recent_scores = context.get("recent_scores", [])
        question_count = context.get("question_count", 0)
        resume_data = context.get("resume_data", {})
        user_answer = kwargs.get("user_answer")

        logger.info(
            "chat_mode_started",
            session_id=session_id,
            trigger_reason=trigger_reason,
            recent_avg=sum(recent_scores[-5:]) / len(recent_scores[-5:]) if recent_scores else 0,
        )

        if phase != InterviewPhase.CHAT_MODE:
            raise ValueError(f"闲聊模式只能在 CHAT_MODE 阶段使用，当前阶段: {phase}")

        if user_answer:
            result = await self._evaluate_and_respond(
                session_id=session_id,
                answer=user_answer,
                trigger_reason=trigger_reason,
                recent_scores=recent_scores,
                resume_data=resume_data,
            )
        else:
            result = await self._generate_chat_question(
                session_id=session_id,
                trigger_reason=trigger_reason,
                recent_scores=recent_scores,
                question_count=question_count,
                resume_data=resume_data,
            )

        return {
            **result,
            "session_id": session_id,
            "phase": str(phase),
            "trigger_reason": trigger_reason,
        }

    async def should_enter_chat_mode(
        self,
        session_state: dict
    ) -> tuple[bool, str]:
        """
        判断是否应该进入闲聊模式
        
        【返回】(should_enter, reason)
        
        【触发条件】
        1. 表现好：连续3轮得分 >= 80 → "excellent_performance"
        2. 表现差：连续3轮得分 <= 55 → "poor_performance_encouragement"
        3. 接近尾声：已出题数 >= 总题数 - 2 → "approaching_end"
        4. 八股文阶段全部完成 → "phase_transition"
        """
        scores = session_state.get("scores", [])
        question_count = session_state.get("question_count", 0)
        max_questions = session_state.get("max_questions", 15)
        current_phase = session_state.get("current_phase", "")

        if len(scores) >= 3:
            last_3 = [s.get("score", 0) for s in scores[-3:] if isinstance(s, dict)]
            if all(s >= 80 for s in last_3):
                logger.info(
                    "chat_mode_trigger_excellent",
                    session_id=session_state.get("session_id"),
                    last_3_scores=last_3,
                )
                return True, "excellent_performance"

            if all(s <= 55 for s in last_3):
                logger.info(
                    "chat_mode_trigger_poor",
                    session_id=session_state.get("session_id"),
                    last_3_scores=last_3,
                )
                return True, "poor_performance_encouragement"

        if question_count >= max_questions - 2 and current_phase != InterviewPhase.CHAT_MODE:
            logger.info(
                "chat_mode_trigger_near_end",
                session_id=session_state.get("session_id"),
                question_count=question_count,
                max_questions=max_questions,
            )
            return True, "approaching_end"

        if current_phase == InterviewPhase.EIGHT_PART_QA and question_count >= max_questions - 3:
            return True, "phase_transition"

        return False, ""

    async def _generate_chat_question(
        self,
        session_id: str,
        trigger_reason: str,
        recent_scores: list,
        question_count: int,
        resume_data: dict,
    ) -> Dict[str, Any]:
        """生成闲聊问题"""
        topic = self._select_topic(trigger_reason, recent_scores, resume_data)

        if random.random() < 0.5 and topic:
            question_text = topic["template"]
            source = "template"
        else:
            question_text = await self._llm_generate_question(
                session_id=session_id,
                trigger_reason=trigger_reason,
                recent_scores=recent_scores,
                resume_data=resume_data,
            )
            source = "llm"

        logger.info(
            "chat_question_generated",
            session_id=session_id,
            topic=topic["topic"] if topic else "dynamic",
            source=source,
            trigger_reason=trigger_reason,
        )

        return {
            "type": "chat_question",
            "question": question_text,
            "topic": topic["topic"] if topic else "custom",
            "category": topic.get("category", "general") if topic else "general",
            "source": source,
            "is_follow_up": False,
        }

    async def _evaluate_and_respond(
        self,
        session_id: str,
        answer: str,
        trigger_reason: str,
        recent_scores: list,
        resume_data: dict,
    ) -> Dict[str, Any]:
        """评估闲聊回答并生成回应"""
        evaluation = await self._evaluate_chat_response(session_id, answer)

        attitude_score = evaluation.get("attitude_score", 70)
        feedback = evaluation.get("feedback", "")
        next_action = evaluation.get("next_action", "continue_chat")

        logger.info(
            "chat_response_evaluated",
            session_id=session_id,
            attitude_score=attitude_score,
            next_action=next_action,
        )

        if next_action == "end_chat":
            return {
                "type": "chat_evaluation",
                "score": attitude_score,
                "feedback": feedback,
                "next_action": "transition_to_final_score",
                "dimension": "attitude",
                "is_formal_scoring": False,
            }

        followup = await self._generate_followup_response(
            session_id=session_id,
            answer=answer,
            feedback=feedback,
            trigger_reason=trigger_reason,
        )

        return {
            "type": "chat_evaluation_with_followup",
            "score": attitude_score,
            "feedback": feedback,
            "followup": followup,
            "next_action": "continue_chat",
            "dimension": "attitude",
            "is_formal_scoring": False,
        }

    def _select_topic(
        self,
        trigger_reason: str,
        recent_scores: list,
        resume_data: dict,
    ) -> Optional[Dict]:
        """根据触发原因选择合适的话题"""
        if trigger_reason == "excellent_performance":
            candidates = [t for t in self._chat_topics if t["topic"] in ["技术趋势", "开源贡献", "学习方法"]]
        elif trigger_reason == "poor_performance_encouragement":
            candidates = [t for t in self._chat_topics if t["topic"] in ["学习方法", "职业规划", "团队协作"]]
        elif trigger_reason == "approaching_end":
            candidates = [t for t in self._chat_topics if t["topic"] in ["面试反馈", "职业规划"]]
        elif trigger_reason == "phase_transition":
            candidates = [t for t in self._chat_topics if t["topic"] in ["团队协作", "技术趋势"]]
        else:
            candidates = self._chat_topics

        if resume_data.get("skills") or resume_data.get("projects"):
            tech_related = [t for t in candidates if t["category"] in ["trends", "opensource", "learning"]]
            if tech_related and random.random() < 0.6:
                return random.choice(tech_related)

        return random.choice(candidates) if candidates else None

    async def _llm_generate_question(
        self,
        session_id: str,
        trigger_reason: str,
        recent_scores: list,
        resume_data: dict,
    ) -> str:
        """LLM 动态生成闲聊问题"""
        import json

        avg_score = sum(recent_scores[-5:]) / len(recent_scores[-5:]) if recent_scores else 70
        skills_hint = ", ".join(resume_data.get("skills", [])[:5]) if resume_data.get("skills") else "未知"

        prompt = CHAT_TOPIC_PROMPT.format(
            trigger_reason=trigger_reason,
            avg_score=round(avg_score, 1),
            skills_hint=skills_hint,
        )

        response = await self._llm.chat(
            system_prompt=CHAT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )

        content = response.get("content", "").strip()
        if content and len(content) > 10:
            return content

        fallback = random.choice(self._chat_topics)
        return fallback["template"]

    async def _evaluate_chat_response(
        self,
        session_id: str,
        answer: str,
    ) -> Dict[str, Any]:
        """评估闲聊回答"""
        prompt = CHAT_EVALUATION_PROMPT.format(answer=answer)

        response = await self._llm.chat(
            system_prompt=CHAT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        content_str = response.get("content", "{}")
        try:
            import json as _json
            content = _json.loads(content_str) if isinstance(content_str, str) else content_str
        except Exception:
            content = {}

        return {
            "attitude_score": content.get("attitude_score", 70),
            "feedback": content.get("feedback", ""),
            "next_action": content.get("next_action", "continue_chat"),
            "positivity_indicators": content.get("positivity_indicators", []),
        }

    async def _generate_followup_response(
        self,
        session_id: str,
        answer: str,
        feedback: str,
        trigger_reason: str,
    ) -> str:
        """生成闲聊追问/回应"""
        prompt = f"""候选人在闲聊中回答了以下内容：

{answer}

{feedback}

请用1-2句自然的话回应候选人，可以：
- 对他的观点表示认同或补充
- 提出一个自然的后续问题
- 给予适当的鼓励

要求：
- 语气轻松友好
- 不要像正式面试那样严肃
- 回应控制在50字以内"""

        response = await self._llm.chat(
            system_prompt="你是一位友好的面试官，正在和候选人轻松聊天。语气自然亲切。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )

        return response.get("content", "说得不错，还有其他想聊的吗？").strip()


def get_chat_mode_handler() -> ChatModeHandlerSkill:
    """获取 ChatModeHandlerSkill 实例"""
    return ChatModeHandlerSkill()
