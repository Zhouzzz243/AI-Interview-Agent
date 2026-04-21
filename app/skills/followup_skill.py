"""
追问生成技能

【Java 类比】
- 类似 @Service 注解的 FollowUpDecisionService
- 职责：决定是否追问，以及追问什么内容

【核心功能】
1. 分析当前得分和回答质量
2. 做出追问决策（follow_up / next_question / interest_follow_up / phase_switch）
3. 生成具体的追问内容
4. 管理追问配额（每题最多2次，总共最多5次）

【三层决策机制】
┌─────────────────────────────────────────────────┐
│  第一层：是否值得追问？                           │
│  - score 75-89: 有深挖空间 → follow_up           │
│  - score >= 90 + 高价值信号 → interest_follow_up │
│  - score < 75 或已充分回答 → next_question       │
├─────────────────────────────────────────────────┤
│  第二层：追问什么类型？                            │
│  - 技术深挖、场景扩展、对比分析、边界条件          │
│  - 纠正引导（当有误解时）                         │
├─────────────────────────────────────────────────┤
│  第三层：资源约束检查                              │
│  - 本题已追问 < 2次？                             │
│  - 总剩余配额 > 0？                               │
│  - 连续低分次数 < 2？                             │
└─────────────────────────────────────────────────┘

【调用时机】
评分完成后，由 Orchestrator 调用此 Skill 决定下一步

【使用示例】
skill = FollowupSkill()
result = await skill.execute(
    session_id="session_123",
    context={
        "question": "HashMap的底层原理？",
        "answer": "数组加链表...",
        "score": 78,
        "category": "technical_javase",
        "remaining_budget": 3,
        "current_followup_count": 0
    }
)
decision = result.data  # FollowUpDecision 对象
"""

import json
from typing import Any, Dict, Optional

from app.skills.base_skill import BaseSkill, SkillResult
from app.tools.llm_client import LLMClient
from app.infrastructure.logger import get_logger
from app.api.schemas import InterviewPhase
from app.prompts.followup_prompts import (
    FOLLOWUP_SYSTEM_PROMPT,
    get_followup_decision_prompt,
    generate_followup_content
)

logger = get_logger(__name__)


class FollowUpSkill(BaseSkill):
    """
    追问决策与生成技能
    
    【决策结果类型】
    - follow_up: 标准追问（得分75-89，有深挖空间）
    - interest_follow_up: 兴趣追问（检测到高价值信号）
    - next_question: 不追问，直接下一题（最常见）
    - phase_switch: 切换阶段（当前阶段题目已问完）
    
    【追问类型】
    - technical_deep_dive: 技术细节深挖
    - scenario_extension: 场景扩展应用
    - comparison_analysis: 方案对比分析
    - boundary_condition: 边界条件/异常处理
    - corrective_guidance: 纠正引导
    """
    
    def __init__(self):
        super().__init__()
        self._llm = LLMClient()
        
        # 得分区间到默认决策的映射
        self._score_decision_map = {
            range(90, 101): "interest_follow_up",   # 很好但有价值可深挖
            range(75, 90): "follow_up",             # 有提升空间
            range(0, 75): "next_question"           # 基础不牢或已充分回答
        }
    
    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        """校验必要参数"""
        await super().validate(session_id, context)
        
        required = ["question", "answer", "score", "category"]
        for field in required:
            if field not in context:
                raise ValueError(f"需要提供 {field}")
        
        if "remaining_budget" not in context and "followup_count" not in context:
            raise ValueError("需要提供 remaining_budget 或 followup_count")
    
    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行追问决策
        
        【参数说明】
        - question: 当前问题
        - answer: 候选人回答
        - score: 刚才给出的分数 (0-100)
        - category: 题目分类
        - remaining_budget: 剩余总追问配额
        - followup_count: 本题已追问次数
        - consecutive_low_scores: 连续低分次数（可选）
        - phase: 当前阶段（可选）
        """
        question = context["question"]
        answer = context["answer"]
        score = context["score"]
        category = context["category"]
        remaining_budget = context.get("remaining_budget", 5)
        followup_count = context.get("followup_count", 0)
        consecutive_low_scores = kwargs.get("consecutive_low_scores", 0)
        
        logger.info(
            "followup_decision_started",
            session_id=session_id,
            current_score=score,
            category=category,
            remaining_budget=remaining_budget,
            followup_count=followup_count
        )
        
        # 步骤1：快速预检（规则引擎）
        quick_decision = self._quick_check(
            score=score,
            remaining_budget=remaining_budget,
            followup_count=followup_count,
            consecutive_low_scores=consecutive_low_scores
        )
        
        if quick_decision == "next_question":
            logger.info("quick_decision_next_question", reason="规则过滤")
            return self._build_result(decision="next_question", reason="资源不足或连续低分")
        
        # 步骤2：LLM智能决策
        decision_data = await self._llm_decision(
            question=question,
            answer=answer,
            score=score,
            category=category,
            remaining_budget=remaining_budget,
            followup_count=followup_count
        )
        
        decision = decision_data.get("decision", "next_question")
        
        # 步骤3：如果决定追问，生成追问内容
        followup_content = None
        if decision in ("follow_up", "interest_follow_up"):
            followup_content = await self._generate_followup(
                original_question=question,
                original_answer=answer,
                score=score,
                category=category,
                followup_type=decision_data.get("followup_type", "technical_deep_dive")
            )
        
        result = {
            "decision": decision,
            "reason": decision_data.get("reason", ""),
            "confidence": decision_data.get("confidence", 0.8),
            "tags": decision_data.get("tags"),
            "follow_up_content": followup_content,
            "followup_type": decision_data.get("followup_type") if followup_content else None,
            "session_id": session_id,
            "original_score": score,
            "original_category": category
        }
        
        logger.info(
            "followup_decision_completed",
            session_id=session_id,
            decision=decision,
            has_followup=bool(followup_content)
        )
        
        return result
    
    def _quick_check(
        self,
        score: int,
        remaining_budget: int,
        followup_count: int,
        consecutive_low_scores: int = 0
    ) -> Optional[str]:
        """
        快速预检（基于规则的快速过滤）
        
        【返回】None 表示需要LLM决策，否则直接返回决策
        """
        # 每题最多追问2次
        if followup_count >= 2:
            return "next_question"
        
        # 配额用完
        if remaining_budget <= 0:
            return "next_question"
        
        # 连续2次低分（<65），不再追问避免打击信心
        if consecutive_low_scores >= 2:
            return "next_question"
        
        # 分数太低（<60），基础不牢
        if score < 60:
            return "next_question"
        
        return None  # 需要LLM进一步判断
    
    async def _llm_decision(
        self,
        question: str,
        answer: str,
        score: int,
        category: str,
        remaining_budget: int,
        followup_count: int
    ) -> dict:
        """调用LLM进行智能决策"""
        user_prompt = get_followup_decision_prompt(
            question=question,
            answer=answer,
            current_score=score,
            category=category,
            remaining_budget=remaining_budget,
            followup_count=followup_count
        )
        
        response = await self._llm.chat(
            system_prompt=FOLLOWUP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.4,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_response(response.get("content", ""))
        
        return content
    
    async def _generate_followup(
        self,
        original_question: str,
        original_answer: str,
        score: int,
        category: str,
        followup_type: str = "technical_deep_dive"
    ) -> Optional[str]:
        """生成具体的追问内容"""
        try:
            prompt = generate_followup_content(
                original_question=original_question,
                original_answer=original_answer,
                score=score,
                category=category,
                followup_type=followup_type
            )
            
            response = await self._llm.chat(
                system_prompt=FOLLOWUP_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = self._parse_response(response.get("content", ""))
            
            return content.get("follow_up_question")
            
        except Exception as e:
            logger.error("followup_generation_failed", error=str(e))
            return None
    
    @staticmethod
    def _build_result(
        decision: str,
        reason: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """构建标准返回格式"""
        return {
            "decision": decision,
            "reason": reason or f"自动决策: {decision}",
            "confidence": 0.9,
            "tags": kwargs.get("tags", []),
            "follow_up_content": None,
            **kwargs
        }
    
    @staticmethod
    def _parse_response(content: str) -> dict:
        """解析LLM返回的JSON"""
        if not content:
            return {"decision": "next_question", "reason": "解析失败"}
        
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
            
            return {"decision": "next_question", "reason": content[:100]}
    
    async def post_process(
        self,
        session_id: str,
        result: Any,
        context: Dict[str, Any]
    ) -> None:
        """后处理：记录日志"""
        decision = result.get("decision", "unknown")
        
        logger.info(
            "followup_skill_completed",
            session_id=session_id,
            decision=decision,
            will_followup=decision in ("follow_up", "interest_follow_up")
        )


def get_followup_skill() -> FollowUpSkill:
    """获取 FollowUpSkill 实例"""
    return FollowUpSkill()
