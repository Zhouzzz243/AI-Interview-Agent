"""
简历解析提示词模板

【职责】
定义简历解析相关的所有Prompt，确保LLM输出符合预期的JSON格式

【设计原则】
1. 使用结构化Prompt（System + User）
2. 明确指定输出格式（JSON Schema）
3. 提供示例降低幻觉风险
"""

# ══════════════════════════════════════════════
# 系统提示词（角色设定）
# ══════════════════════════════════════════════

RESUME_PARSE_SYSTEM_PROMPT = """你是一位专业的HR技术面试官助手，擅长从简历中提取和结构化关键信息。

【核心能力】
1. 准确识别教育背景、实习经历、项目经验
2. 提取技术栈和技能熟练度
3. 判断信息的完整性和可信度
4. 标注需要深挖的亮点（用于后续面试）

【输出要求】
- 必须输出严格的JSON格式
- 不要编造简历中不存在的信息
- 对于不确定的信息，使用null或空列表
- 技术栈要标准化（如"Spring Boot"而不是"springboot"）"""


# ══════════════════════════════════════════════
# 用户提示词（任务指令）
# ══════════════════════════════════════════════

def get_resume_parse_user_prompt(resume_text: str) -> str:
    """
    生成简历解析的用户提示词
    
    【参数】resume_text: 从PDF/DOCX中提取的原始文本
    
    【返回】包含任务指令的完整prompt
    """
    return f"""请解析以下简历内容，提取关键信息并以JSON格式返回：

```text
{resume_text}
```

【输出格式要求】
{{
    "basic_info": {{
        "name": "姓名",
        "phone": "联系电话",
        "email": "电子邮箱",
        "university": "毕业院校",
        "major": "专业"
    }},
    "education": [
        {{
            "school": "学校名称",
            "degree": "学历（本科/硕士/博士）",
            "major": "专业名称",
            "graduation_date": "毕业时间（YYYY-MM）",
            "gpa": 绩点（可选，没有则不填）
        }}
    ],
    "internships": [
        {{
            "company": "公司名称",
            "position": "职位",
            "duration": "实习时长（如'2025.03-2025.09'或'6个月'）",
            "description": "工作内容描述（200字以内）",
            "technologies": ["使用的技术栈"]
        }}
    ],
    "projects": [
        {{
            "project_name": "项目名称",
            "role": "担任角色",
            "description": "项目描述（300字以内）",
            "tech_stack": ["技术栈"],
            "highlights": ["项目亮点（最多3条）"]
        }}
    ],
    "skills": [
        {{
            "category": "分类（编程语言/框架/数据库/中间件/工具）",
            "skills": ["具体技能"],
            "proficiency": "熟练度（了解/熟悉/熟练/精通）"
        }}
    ],
    "analysis": {{
        "total_experience_months": 实习总月数（整数）,
        "project_count": 项目数量,
        "tech_stack_richness": 技术栈丰富度评分(1-10),
        "highlight_keywords": ["值得深挖的关键词"],
        "suggested_interview_topics": ["建议的面试话题"]
    }}
}}

【注意事项】
1. 如果某项信息缺失，使用空数组[]或null
2. technologies和tech_stack字段要拆分为独立的字符串数组
3. description要简洁，保留关键技术和成果
4. highlight_keywords要提取能体现技术深度或业务价值的关键词"""


# ══════════════════════════════════════════════
# 简历丰富度评估提示词
# ══════════════════════════════════════════════

RESUME_RICHNESS_SYSTEM_PROMPT = """你是一位资深技术招聘专家，擅长评估简历的信息丰富度和质量。

【评估维度】
1. 教育背景完整性（学校层次、专业相关性、GPA等）
2. 实习经历含金量（公司知名度、岗位匹配度、描述详细程度）
3. 项目经验深度（技术难度、个人贡献、成果量化）
4. 技能覆盖广度（技术栈数量、主流框架掌握情况）
5. 可面试性（是否有足够的内容支撑一场30分钟技术面试）

【输出要求】
给出0-100的分数，以及改进建议"""


def get_richness_evaluation_prompt(parsed_resume: dict) -> str:
    """
    生成简历丰富度评估的提示词
    """
    import json
    return f"""请评估以下已解析简历的信息丰富度：

```json
{json.dumps(parsed_resume, ensure_ascii=False, indent=2)}
```

【输出格式】
{{
    "richness_score": 分数(0-100),
    "education_score": 教育背景得分(0-20),
    "internship_score": 实习经历得分(0-30),
    "project_score": 项目经验得分(0-30),
    "skill_score": 技能覆盖得分(0-20),
    "strengths": ["优势1", "优势2", "优势3"],
    "weaknesses": ["不足1", "不足2"],
    "improvement_suggestions": ["建议1", "建议2"],
    "interview_readiness": "ready/partial/limited",
    "recommended_focus_areas": ["建议重点考察的方向"]
}}"""
