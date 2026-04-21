"""
智能评分技能

【Java 类比】
- 类似 @Service 注解的 ScoringService
- 职责：对候选人的回答进行多维度评分和反馈

【核心功能】
1. 根据题目类型选择评分维度
2. 调用 LLM 进行智能评分（而非规则匹配）
3. 给出建设性反馈意见
4. 识别候选人的优势和不足
5. 为追问决策提供依据

【评分体系】(2026-04-19 优化版)
┌─────────────────────┬────────┬──────────────────────────────┐
│ 维度                 │ 权重   │ 说明                         │
├─────────────────────┼────────┼──────────────────────────────┤
│ 实践能力             │ 45%    │ 实习25% + 项目20%            │
│ 技术基础 (八股文)    │ 25%    │ 原理理解、应用能力           │
│ 沟通表达             │ 15%    │ 自我介绍7% + 表达能力8%       │
│ 学习潜力             │ 10%    │ 思考深度、主动学习           │
│ 积极态度             │ 5%     │ 积极性、参与度               │
└─────────────────────┴────────┴──────────────────────────────┘

【调用时机】
每次候选人回答问题后，由 Orchestrator 调用此 Skill

【使用示例】
skill = ScoringSkill()
result = await skill.execute(
    session_id="session_123",
    context={
        "question": "HashMap的底层原理是什么？",
        "answer": "HashMap底层是数组加链表...",
        "category": "technical_javase",
        "phase": "eight_part_qa"
    }
)
score_result = result.data  # 包含 score, feedback, sub_scores 等
"""

import json
from typing import Any, Dict, List, Optional

from app.skills.base_skill import BaseSkill, SkillResult
from app.tools.llm_client import LLMClient
from app.rag import get_rag_engine
from app.infrastructure.logger import get_logger
from app.api.schemas import InterviewPhase, QuestionCategory
from app.prompts.scoring_prompts import (
    SCORING_SYSTEM_PROMPT,
    get_self_intro_scoring_prompt,
    get_practice_scoring_prompt,
    get_eight_part_scoring_prompt,
    get_final_score_prompt
)

logger = get_logger(__name__)


class ScoringSkill(BaseSkill):
    """
    智能评分技能
    
    【支持的评分类型】
    - self_intro: 自我介绍评分
    - internship: 实习经历回答评分
    - project: 项目经验回答评分  
    - eight_part: 八股文技术题评分
    - chat: 闲聊模式评分
    
    【执行流程】
    1. 根据 category 选择评分策略和 Prompt
    2. 构建包含问题和答案的上下文
    3. 调用 LLM 进行评分
    4. 解析评分结果和反馈
    5. 返回结构化的评分数据
    """
    
    def __init__(self):
        super().__init__()
        self._llm = LLMClient()
        self._rag = get_rag_engine()
        
        # 分类到评分方法的映射
        self._scoring_methods = {
            QuestionCategory.SELF_INTRODUCTION.value: self._score_self_intro,
            QuestionCategory.INTERNSHIP.value: self._score_practice,
            QuestionCategory.PROJECT.value: self._score_practice,
        }
        
        # 八股文分类前缀
        self._eight_part_prefix = "technical_"
    
    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        """校验必要参数"""
        await super().validate(session_id, context)
        
        required_fields = ["question", "answer", "category"]
        for field in required_fields:
            if field not in context:
                raise ValueError(f"需要提供 {field}")
        
        if not context["answer"].strip():
            raise ValueError("回答内容不能为空")
    
    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行评分
        
        【参数说明】
        - question: 面试题目
        - answer: 候选人回答
        - category: 题目分类
        - phase: 当前阶段（可选）
        - original_info: 原始实习/项目信息（用于对比真实性）
        - key_points: 期望的关键回答要点（八股文用）
        """
        question = context["question"]
        answer = context["answer"]
        category = context["category"]
        phase = context.get("phase")
        original_info = context.get("original_info", {})
        key_points = context.get("key_points", [])
        
        logger.info(
            "scoring_started",
            session_id=session_id,
            category=category,
            answer_length=len(answer)
        )
        
        # 选择评分方法
        if category in self._scoring_methods:
            score_data = await self._scoring_methods[category](
                question=question,
                answer=answer,
                category=category,
                phase=phase,
                original_info=original_info,
                **kwargs
            )
        elif category.startswith(self._eight_part_prefix):
            # 八股文题目
            sub_category = category.replace(self._eight_part_prefix, "")
            score_data = await self._score_eight_part(
                question=question,
                answer=answer,
                category=category,
                sub_category=sub_category,
                key_points=key_points
            )
        else:
            # 默认：通用评分
            score_data = await self._score_generic(
                question=question,
                answer=answer,
                category=category
            )
        
        result = {
            "session_id": session_id,
            "question": question,
            "category": category,
            **score_data,
            "scored_at": __import__("datetime").datetime.now().isoformat()
        }
        
        logger.info(
            "scoring_completed",
            session_id=session_id,
            category=category,
            score=result.get("score"),
            dimension=result.get("dimension")
        )
        
        return result
    
    async def _score_self_intro(
        self,
        question: str,
        answer: str,
        category: str,
        phase: InterviewPhase = None,
        resume_summary: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """自我介绍评分"""
        user_prompt = get_self_intro_scoring_prompt(
            answer=answer,
            resume_summary=resume_summary or kwargs.get("resume_summary", "")
        )
        
        response = await self._llm.chat(
            system_prompt=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        return {
            "score": content.get("score", 70),
            "dimension": "self_intro",
            "sub_scores": {},
            "feedback": content.get("feedback", ""),
            "strengths": content.get("strengths", []),
            "weaknesses": content.get("weaknesses", []),
            "highlight_topics": content.get("highlight_topics", []),
            "follow_up_worthiness": content.get("suggested_follow_up") and "medium" or "low"
        }
    
    async def _score_practice(
        self,
        question: str,
        answer: str,
        category: str,
        phase: InterviewPhase = None,
        original_info: dict = None,
        **kwargs
    ) -> Dict[str, Any]:
        """实践类评分（实习/项目）"""
        user_prompt = get_practice_scoring_prompt(
            answer=answer,
            question=question,
            category=category,
            original_info=original_info or {}
        )
        
        response = await self._llm.chat(
            system_prompt=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        return {
            "score": content.get("score", 70),
            "dimension": category,
            "sub_scores": content.get("sub_scores", {}),
            "feedback": content.get("feedback", ""),
            "strengths": content.get("strengths", []),
            "weaknesses": content.get("weaknesses", []),
            "credibility_assessment": content.get("credibility_assessment", "medium"),
            "follow_up_worthiness": content.get("follow_up_worthiness", "medium"),
            "suggested_followup": content.get("suggested_followup")
        }
    
    async def _score_eight_part(
        self,
        question: str,
        answer: str,
        category: str,
        sub_category: str,
        key_points: list = None,
        **kwargs
    ) -> Dict[str, Any]:
        """八股文技术题评分（RAG 增强）"""
        
        # ═══ RAG 检索：获取参考答案作为评分基准 ═══
        rag_context = ""
        try:
            rag_context = await self._rag.retrieve_for_scoring(
                question=question,
                answer=answer,
                category=sub_category,
                top_k=3
            )
            if rag_context:
                logger.info(
                    "rag_context_injected",
                    sub_category=sub_category,
                    context_length=len(rag_context)
                )
        except Exception as e:
            logger.warning("rag_retrieval_skipped", error=str(e))
        
        user_prompt = get_eight_part_scoring_prompt(
            answer=answer,
            question=question,
            category=sub_category,
            key_points=key_points or [],
            rag_context=rag_context
        )
        
        response = await self._llm.chat(
            system_prompt=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        return {
            "score": content.get("score", 70),
            "dimension": "eight_part",
            "sub_category": sub_category,
            "sub_scores": content.get("sub_scores", {}),
            "key_points_covered": content.get("key_points_covered", 0),
            "total_key_points": content.get("total_key_points", 0),
            "misconceptions": content.get("misconceptions", []),
            "feedback": content.get("feedback", ""),
            "level_assessment": content.get("level_assessment", "intermediate")
        }
    
    async def _score_generic(
        self,
        question: str,
        answer: str,
        category: str,
        **kwargs
    ) -> Dict[str, Any]:
        """通用评分（兜底）"""
        prompt = f"""请对以下回答进行简单评分：

【问题】{question}

【回答】{answer}

【分类】{category}

【输出格式】JSON
{{
    "score": 分数(0-100),
    "feedback": "简要反馈"
}}"""
        
        response = await self._llm.chat(
            system_prompt="你是一位面试官，请对回答进行客观评分。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        return {
            "score": content.get("score", 70),
            "dimension": category,
            "feedback": content.get("feedback", "")
        }
    
    async def calculate_final_score(
        self,
        session_id: str,
        all_scores: dict,
        session_summary: dict
    ) -> Dict[str, Any]:
        """
        计算最终综合评分
        
        【加权公式 - 2026-04-19 更新】
        final_score = practice×45% + technical×25% 
                    + communication×15% + potential×10% + attitude×5%
        
        其中 practice = internship×25% + project×20%
        """
        logger.info(
            "final_score_calculation_started",
            session_id=session_id
        )
        
        user_prompt = get_final_score_prompt(all_scores, session_summary)
        
        response = await self._llm.chat(
            system_prompt=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        final_score = content.get("final_score", 0)
        raw_dimensions = content.get("dimension_scores", {})
        
        dimensions = [
            {"dimension": dim, "score": score, "details": ""}
            for dim, score in raw_dimensions.items()
        ]
        
        result = {
            "final_score": final_score,
            "level": content.get("grade", "C"),
            "dimensions": dimensions,
            "summary": content.get("summary", ""),
            "strengths": content.get("strengths", []),
            "weaknesses": content.get("areas_for_improvement", []),
            "suggestions": content.get("next_step_suggestions", []),
            "passed": final_score >= 70
        }
        
        logger.info(
            "final_score_calculated",
            session_id=session_id,
            final_score=result["final_score"],
            level=result["level"],
            passed=result["passed"]
        )
        
        return result
    
    @staticmethod
    def _parse_response(content: str) -> dict:
        """解析LLM返回的JSON"""
        if not content:
            return {"score": 50, "feedback": "解析失败"}
        
        if isinstance(content, dict):
            return content
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            
            return {"score": 50, "feedback": content[:200]}
    
    async def post_process(
        self,
        session_id: str,
        result: Any,
        context: Dict[str, Any]
    ) -> None:
        """后处理：记录日志"""
        logger.info(
            "scoring_skill_completed",
            session_id=session_id,
            score=result.get("score"),
            follow_up_worthy=result.get("follow_up_worthiness") in ["high", "medium"]
        )


def get_scoring_skill() -> ScoringSkill:
    """获取 ScoringSkill 实例"""
    return ScoringSkill()
