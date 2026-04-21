"""
面试提问生成技能

【Java 类比】
- 类似 @Service 注解的 InterviewQuestionService
- 职责：根据当前阶段和候选人背景，生成合适的面试题目

【核心功能】
1. 根据面试阶段（自我介绍/实习/项目/八股文）选择出题策略
2. 结合简历信息定制化出题
3. 控制难度递进
4. 避免重复提问
5. 支持多种题型分类

【调用时机】
每次需要出新题时，由 Orchestrator 调用此 Skill

【使用示例】
skill = InterviewSkill()
result = await skill.execute(
    session_id="session_123",
    context={
        "phase": "internship_qa",
        "resume_data": {...},
        "asked_questions": [...]
    }
)
question = result.data  # GeneratedQuestion 对象
"""

import json
import random
from typing import Any, Dict, List, Optional

from app.skills.base_skill import BaseSkill, SkillResult
from app.tools.llm_client import LLMClient
from app.infrastructure.logger import get_logger
from app.api.schemas import InterviewPhase, QuestionCategory, DifficultyLevel
from app.prompts.interview_prompts import (
    INTERVIEW_SYSTEM_PROMPT,
    get_self_intro_prompt,
    get_internship_question_prompt,
    get_project_question_prompt,
    get_eight_part_question_prompt,
    EIGHT_PART_CATEGORIES
)

logger = get_logger(__name__)


class InterviewSkill(BaseSkill):
    """
    面试提问技能
    
    【支持的阶段和题型映射】
    - SELF_INTRO → 自我介绍引导
    - INTERNSHIP_QA → 实习经历深挖 (QuestionCategory.INTERNSHIP)
    - PROJECT_QA → 项目经验深挖 (QuestionCategory.PROJECT)
    - EIGHT_PART_QA → 八股文问答 (9种技术方向)
    
    【执行策略】
    1. 根据 phase 选择对应的 Prompt 模板
    2. 从简历中提取相关信息作为上下文
    3. 查询已问过的题目避免重复
    4. 根据历史得分调整难度
    5. 调用 LLM 生成题目
    """
    
    def __init__(self):
        super().__init__()
        self._llm = LLMClient()
        
        # 阶段到Prompt方法的映射
        self._prompt_generators = {
            InterviewPhase.SELF_INTRO: self._generate_self_intro,
            InterviewPhase.INTERNSHIP_QA: self._generate_internship_question,
            InterviewPhase.PROJECT_QA: self._generate_project_question,
            InterviewPhase.EIGHT_PART_QA: self._generate_eight_part_question,
        }
    
    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        """校验必要参数"""
        await super().validate(session_id, context)
        
        if "phase" not in context:
            raise ValueError("需要提供 phase（当前面试阶段）")
        
        phase = context["phase"]
        
        if isinstance(phase, str):
            try:
                phase = InterviewPhase(phase)
                context["phase"] = phase
            except ValueError:
                raise ValueError(f"无效的面试阶段: {phase}")
        
        # 不同阶段的额外校验
        if phase in [InterviewPhase.INTERNSHIP_QA, InterviewPhase.PROJECT_QA]:
            if "resume_data" not in context:
                raise ValueError(f"{phase.value} 阶段需要提供 resume_data")
        
        if phase == InterviewPhase.EIGHT_PART_QA:
            if "tech_stack" not in context and "resume_data" not in context:
                raise ValueError("八股文阶段需要提供 tech_stack 或 resume_data")
    
    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行提问生成
        
        【参数说明】
        - phase: 当前面试阶段 (InterviewPhase)
        - resume_data: 已解析的简历数据
        - asked_questions: 已问过的题目列表
        - tech_stack: 候选人技术栈（可选）
        - asked_categories: 各分类已问次数 {"javase": 1, ...}
        - difficulty: 指定难度（可选，默认自动判断）
        """
        phase = context["phase"]
        resume_data = context.get("resume_data", {})
        asked_questions = context.get("asked_questions", [])
        tech_stack = context.get(
            "tech_stack", 
            self._extract_tech_stack(resume_data)
        )
        asked_categories = context.get("asked_categories", {})
        difficulty = kwargs.get(
            "difficulty",
            self._determine_difficulty(asked_questions, kwargs.get("scores", {}))
        )
        
        logger.info(
            "question_generation_started",
            session_id=session_id,
            phase=phase.value if isinstance(phase, InterviewPhase) else phase,
            difficulty=difficulty,
            asked_count=len(asked_questions)
        )
        
        # 根据阶段选择生成方法
        generator = self._prompt_generators.get(phase)
        
        if not generator:
            raise ValueError(f"不支持的面试阶段: {phase}")
        
        question_data = await generator(
            session_id=session_id,
            phase=phase,
            resume_data=resume_data,
            asked_questions=asked_questions,
            tech_stack=tech_stack,
            asked_categories=asked_categories,
            difficulty=difficulty
        )
        
        result = {
            **question_data,
            "session_id": session_id,
            "generated_at": __import__("datetime").datetime.now().isoformat()
        }
        
        logger.info(
            "question_generated",
            session_id=session_id,
            category=result.get("category"),
            difficulty=result.get("difficulty")
        )
        
        return result
    
    async def _generate_self_intro(
        self,
        session_id: str,
        phase: InterviewPhase,
        **kwargs
    ) -> Dict[str, Any]:
        """生成自我介绍引导"""
        resume_data = kwargs.get("resume_data", {})
        
        # 构建简历摘要
        summary = self._build_resume_summary(resume_data)
        
        user_prompt = get_self_intro_prompt(summary)
        
        response = await self._llm.chat(
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_llm_response(response.get("content", ""))
        
        return {
            "question": content.get("greeting", "请先做个自我介绍吧"),
            "category": QuestionCategory.SELF_INTRODUCTION.value,
            "difficulty": DifficultyLevel.EASY.value,
            "expected_focus": "了解候选人的基本背景和表达能力",
            "phase": phase.value,
            "suggested_topics": content.get("suggested_topics", []),
            "time_hint": content.get("time_hint", "1-2分钟")
        }
    
    async def _generate_internship_question(
        self,
        session_id: str,
        phase: InterviewPhase,
        resume_data: dict,
        asked_questions: list,
        difficulty: str,
        **kwargs
    ) -> Dict[str, Any]:
        """生成实习经历问题"""
        internships = resume_data.get("internships", [])
        
        if not internships:
            logger.warning("no_internships_found", session_id=session_id)
            return {
                "question": "我看你简历上没有写实习经历，能聊聊你做过哪些实践项目吗？",
                "category": QuestionCategory.INTERNSHIP.value,
                "difficulty": DifficultyLevel.EASY.value,
                "expected_focus": "了解实践经验",
                "phase": phase.value
            }
        
        # 选择一个实习（轮询或随机）
        internship = self._select_item(internships, asked_questions, "company")
        
        user_prompt = get_internship_question_prompt(
            internship_info=internship,
            asked_questions=asked_questions,
            difficulty=difficulty
        )
        
        response = await self._llm.chat(
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.8,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_llm_response(response.get("content", ""))
        
        return {
            "question": content.get("question", ""),
            "category": QuestionCategory.INTERNSHIP.value,
            "difficulty": difficulty,
            "expected_focus": content.get("expected_focus", ""),
            "phase": phase.value,
            "target_company": internship.get("company"),
            "follow_up_directions": content.get("follow_up_directions", [])
        }
    
    async def _generate_project_question(
        self,
        session_id: str,
        phase: InterviewPhase,
        resume_data: dict,
        asked_questions: list,
        difficulty: str,
        **kwargs
    ) -> Dict[str, Any]:
        """生成项目经验问题"""
        projects = resume_data.get("projects", [])
        
        if not projects:
            logger.warning("no_projects_found", session_id=session_id)
            return {
                "question": "能详细说说你做过的最有技术挑战性的项目吗？",
                "category": QuestionCategory.PROJECT.value,
                "difficulty": DifficultyLevel.MEDIUM.value,
                "expected_focus": "了解项目经验和技术深度",
                "phase": phase.value
            }
        
        project = self._select_item(projects, asked_questions, "project_name")
        
        user_prompt = get_project_question_prompt(
            project_info=project,
            asked_questions=asked_questions,
            difficulty=difficulty
        )
        
        response = await self._llm.chat(
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.8,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_llm_response(response.get("content", ""))
        
        return {
            "question": content.get("question", ""),
            "category": QuestionCategory.PROJECT.value,
            "difficulty": difficulty,
            "expected_focus": content.get("expected_focus", ""),
            "phase": phase.value,
            "target_project": project.get("project_name"),
            "tech_focus": content.get("tech_focus", "")
        }
    
    async def _generate_eight_part_question(
        self,
        session_id: str,
        phase: InterviewPhase,
        tech_stack: list,
        asked_categories: dict,
        difficulty: str,
        **kwargs
    ) -> Dict[str, Any]:
        """生成八股文问题"""
        # 选择技术分类
        category = self._select_eight_part_category(
            tech_stack=tech_stack,
            asked_categories=asked_categories
        )
        
        user_prompt = get_eight_part_question_prompt(
            category=category,
            tech_stack=tech_stack,
            asked_categories=asked_categories,
            difficulty=difficulty
        )
        
        response = await self._llm.chat(
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.8,
            response_format={"type": "json_object"}
        )
        
        content = self._parse_llm_response(response.get("content", ""))
        
        category_enum_value = f"technical_{category}"
        
        return {
            "question": content.get("question", ""),
            "category": category_enum_value,
            "difficulty": difficulty,
            "expected_focus": content.get("expected_focus", ""),
            "phase": phase.value,
            "key_points": content.get("key_points", []),
            "common_mistakes": content.get("common_mistakes", [])
        }
    
    # ══════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════
    
    def _extract_tech_stack(self, resume_data: dict) -> List[str]:
        """从简历中提取技术栈"""
        skills = resume_data.get("skills", [])
        tech_stack = []
        
        for skill_group in skills:
            if isinstance(skill_group, dict):
                tech_stack.extend(skill_group.get("skills", []))
            elif isinstance(skill_group, str):
                tech_stack.append(skill_group)
        
        # 也从项目中提取
        for project in resume_data.get("projects", []):
            if isinstance(project, dict):
                tech_stack.extend(project.get("tech_stack", []))
        
        return list(set(tech_stack))  # 去重
    
    def _build_resume_summary(self, resume_data: dict) -> str:
        """构建简历摘要（用于自我介绍提示词）"""
        parts = []
        
        basic = resume_data.get("basic_info", {})
        if basic.get("university"):
            parts.append(f"学校：{basic['university']}")
        if basic.get("major"):
            parts.append(f"专业：{basic['major']}")
        
        education = resume_data.get("education", [])
        if education:
            edu = education[0] if isinstance(education[0], dict) else {}
            parts.append(f"学历：{edu.get('degree', '')} {edu.get('major', '')}")
        
        internships = resume_data.get("internships", [])
        if internships:
            companies = [i.get("company", "") for i in internships if isinstance(i, dict)]
            parts.append(f"实习：{', '.join(companies[:3])}")
        
        projects = resume_data.get("projects", [])
        if projects:
            project_names = [p.get("project_name", "") for p in projects if isinstance(p, dict)]
            parts.append(f"项目：{', '.join(project_names[:3])}")
        
        return "\n".join(parts) if parts else "暂无详细信息"
    
    def _select_item(self, items: list, asked_questions: list, key: str) -> dict:
        """从列表中选择一个项目（避免重复）"""
        if not items:
            return {}
        
        # 尝试找到未被问过的
        unasked = [
            item for item in items 
            if isinstance(item, dict) and 
            item.get(key, "") not in str(asked_questions)
        ]
        
        if unasked:
            return random.choice(unasked)
        
        # 如果都问过了，随机选一个（可能追问不同角度）
        return random.choice(items)
    
    def _select_eight_part_category(
        self,
        tech_stack: list,
        asked_categories: dict
    ) -> str:
        """选择八股文技术分类"""
        categories = list(EIGHT_PART_CATEGORIES.keys())
        
        # 优先选择与候选人技术栈相关的
        relevant = []
        for cat in categories:
            cat_info = EIGHT_PART_CATEGORIES[cat]
            if any(tech.lower() in str(cat_info).lower() for tech in tech_stack):
                relevant.append(cat)
        
        if relevant:
            # 在相关分类中选择问得最少的
            relevant.sort(key=lambda c: asked_categories.get(c, 0))
            return relevant[0]
        
        # 否则选择问得最少的分类
        categories.sort(key=lambda c: asked_categories.get(c, 0))
        return categories[0]
    
    def _determine_difficulty(
        self,
        asked_questions: list,
        scores: dict
    ) -> str:
        """根据历史情况自动判断难度"""
        if not scores or len(asked_questions) < 3:
            return DifficultyLevel.MEDIUM.value
        
        recent_scores = list(scores.values())[-3:] if scores else []
        
        if recent_scores and sum(recent_scores) / len(recent_scores) >= 85:
            return DifficultyLevel.HARD.value
        elif recent_scores and sum(recent_scores) / len(recent_scores) < 65:
            return DifficultyLevel.EASY.value
        
        return DifficultyLevel.MEDIUM.value
    
    @staticmethod
    def _parse_llm_response(content: str) -> dict:
        """解析LLM返回的JSON"""
        if not content:
            return {}
        
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
            
            return {"question": content}
    
    async def post_process(
        self,
        session_id: str,
        result: Any,
        context: Dict[str, Any]
    ) -> None:
        """后处理：记录日志"""
        logger.info(
            "interview_skill_completed",
            session_id=session_id,
            category=result.get("category"),
            difficulty=result.get("difficulty")
        )


def get_interview_skill() -> InterviewSkill:
    """获取 InterviewSkill 实例"""
    return InterviewSkill()
