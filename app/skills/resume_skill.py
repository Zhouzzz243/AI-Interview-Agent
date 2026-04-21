"""
简历解析技能

【Java 类比】
- 类似 @Service 注解的 ResumeParserService
- 职责：接收原始简历文件，解析并返回结构化数据

【核心功能】
1. 从 OSS 下载/读取简历文件
2. 使用 FileParser 解析 PDF/DOCX 为文本
3. 调用 LLM 提取结构化信息（教育、实习、项目、技能）
4. 评估简历丰富度
5. 存储解析结果到向量数据库（用于RAG）

【调用时机】
用户上传简历后，Java 端调用 Python /api/resume/parse 接口触发

【使用示例】
skill = ResumeSkill()
result = await skill.execute(
    session_id="temp_session",
    context={
        "file_url": "oss://resumes/user_123.pdf",
        "user_id": "user_456"
    }
)
parsed_resume = result.data  # ParsedResume 对象
"""

import json
import uuid
from typing import Any, Dict, Optional

from app.skills.base_skill import BaseSkill, SkillResult
from app.tools.file_parser import FileParser
from app.tools.llm_client import LLMClient
from app.infrastructure.logger import get_logger
from app.prompts.resume_prompts import (
    RESUME_PARSE_SYSTEM_PROMPT,
    get_resume_parse_user_prompt,
    RESUME_RICHNESS_SYSTEM_PROMPT,
    get_richness_evaluation_prompt
)

logger = get_logger(__name__)


class ResumeSkill(BaseSkill):
    """
    简历解析技能
    
    【执行流程】
    1. 读取简历文件（从本地路径或OSS）
    2. 使用 FileParser 提取文本
    3. 调用 LLM 解析为结构化 JSON
    4. 验证和清洗数据
    5. （可选）评估简历丰富度
    """
    
    def __init__(self):
        super().__init__()
        self._parser = FileParser()
        self._llm = LLMClient()
    
    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        """校验必要参数"""
        await super().validate(session_id, context)
        
        if "file_path" not in context and "file_url" not in context:
            raise ValueError("需要提供 file_path 或 file_url")
        
        if "user_id" not in context:
            raise ValueError("需要提供 user_id")
    
    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行简历解析
        
        【步骤】
        1. 文件 → 文本 (FileParser)
        2. 文本 → 结构化JSON (LLM)
        3. 数据验证和清洗
        4. 生成 resume_id
        5. 返回完整结果
        """
        file_path = context.get("file_path") or context.get("file_url")
        user_id = context["user_id"]
        evaluate_richness = kwargs.get("evaluate_richness", True)
        
        logger.info(
            "resume_parsing_started",
            session_id=session_id,
            file_path=file_path,
            user_id=user_id
        )
        
        # 步骤1：提取文本
        raw_text = await self._extract_text(file_path)
        
        if not raw_text or len(raw_text.strip()) < 50:
            raise ValueError(f"简历内容过短或无法解析，长度: {len(raw_text) if raw_text else 0}")
        
        # 步骤2：LLM解析
        parsed_data = await self._parse_with_llm(raw_text)
        
        # 步骤3：生成ID和组装结果
        resume_id = f"resume_{uuid.uuid4().hex[:12]}"
        
        result = {
            "resume_id": resume_id,
            "user_id": user_id,
            **parsed_data,
            "raw_text": raw_text,
            "total_text_length": len(raw_text)
        }
        
        # 步骤4：（可选）评估丰富度
        if evaluate_richness:
            richness = await self._evaluate_richness(result)
            result["richness_evaluation"] = richness
        
        logger.info(
            "resume_parsing_completed",
            session_id=session_id,
            resume_id=resume_id,
            education_count=len(parsed_data.get("education", [])),
            internship_count=len(parsed_data.get("internships", [])),
            project_count=len(parsed_data.get("projects", []))
        )
        
        return result
    
    async def _extract_text(self, file_path: str) -> str:
        """
        从文件中提取文本
        
        【调用工具】FileParser
        """
        try:
            result = await self._parser.parse_file(file_path)
            text = result.text
            
            if not text:
                logger.warning("resume_parse_empty", file_path=file_path)
                return ""
            
            logger.info(
                "text_extracted",
                file_path=file_path,
                length=len(text)
            )
            
            return text
            
        except Exception as e:
            logger.error(
                "text_extraction_failed",
                file_path=file_path,
                error=str(e)
            )
            raise
    
    async def _parse_with_llm(self, raw_text: str) -> dict:
        """
        调用LLM解析简历文本为结构化数据
        
        【调用工具】LLMClient
        【使用Prompt】resume_prompts.py
        """
        try:
            user_prompt = get_resume_parse_user_prompt(raw_text)
            
            response = await self._llm.chat(
                system_prompt=RESUME_PARSE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.1,  # 低温度确保结构化输出
                response_format={"type": "json_object"}
            )
            
            content = response.get("content", "")
            
            if not content:
                raise ValueError("LLM返回内容为空")
            
            # 解析JSON
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                # 尝试提取JSON块
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    raise ValueError(f"无法从LLM响应中解析JSON: {content[:200]}")
            
            logger.info(
                "llm_parse_success",
                has_education=bool(parsed.get("education")),
                has_internships=bool(parsed.get("internships")),
                has_projects=bool(parsed.get("projects"))
            )
            
            return parsed
            
        except Exception as e:
            logger.error(
                "llm_parse_failed",
                error=str(e)
            )
            raise
    
    async def _evaluate_richness(self, parsed_resume: dict) -> dict:
        """
        评估简历信息丰富度
        
        【可选步骤】用于判断简历质量
        """
        try:
            user_prompt = get_richness_evaluation_prompt(parsed_resume)
            
            response = await self._llm.chat(
                system_prompt=RESUME_RICHNESS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            content = response.get("content", "")
            
            if content:
                try:
                    return json.loads(content) if isinstance(content, str) else content
                except:
                    pass
            
            return {"richness_score": 50, "error": "评估失败"}
            
        except Exception as e:
            logger.warning("richness_evaluation_failed", error=str(e))
            return {"richness_score": 50, "error": str(e)}
    
    async def post_process(
        self,
        session_id: str,
        result: Any,
        context: Dict[str, Any]
    ) -> None:
        """后处理：记录日志"""
        logger.info(
            "resume_skill_completed",
            session_id=session_id,
            resume_id=result.get("resume_id"),
            richness_score=result.get("richness_evaluation", {}).get("richness_score")
        )


# ══════════════════════════════════════════════
# 工厂函数
# ══════════════════════════════════════════════

def get_resume_skill() -> ResumeSkill:
    """获取 ResumeSkill 单例"""
    return ResumeSkill()
