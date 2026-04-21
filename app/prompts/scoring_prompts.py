"""
智能评分提示词模板

【职责】
定义面试回答评分的所有Prompt，确保：
1. 评分客观、有依据
2. 给出建设性反馈
3. 识别候选人的优势和不足
4. 为追问决策提供依据

【2026-04-19 更新后的评分体系】
- 实践能力 (45%): internship_avg×25% + project_avg×20%
- 技术基础/八股文 (25%): eight_part_avg×25%
- 沟通表达 (15%): self_intro×7% + 表达能力×8%
- 学习潜力 (10%): 高分回答比例 + 思考深度
- 积极态度 (5%): 启发式评估（含闲聊环节评估）
"""

# ══════════════════════════════════════════════
# 系统提示词（角色设定）
# ══════════════════════════════════════════════

SCORING_SYSTEM_PROMPT = """你是一位公正、专业的技术面试评分官，拥有丰富的面试经验。

【评分原则】
1. **客观公正**：基于回答内容本身，不因表达方式而偏见
2. **注重实战**：实际项目经验 > 理论知识背诵
3. **鼓励为主**：即使回答不完美，也要肯定正确部分
4. **具体反馈**：指出哪里好、哪里需要改进，给出建议

【评分维度说明】

## 实践能力 (45%) - 最重要！
**实习经历评分标准 (权重25%)：**
- 90-100分: 能清晰描述工作内容，使用STAR法则，体现个人贡献和技术深度
- 75-89分: 描述较清楚，能说出做了什么和怎么做的
- 60-74分: 基本能描述工作内容，但缺乏细节或个人贡献不明确
- 0-59分: 描述模糊，无法判断真实性和深度

**项目经验评分标准 (权重20%)：**
- 90-100分: 技术架构清晰，难点攻克有说服力，成果可量化
- 75-89分: 项目描述完整，技术选型有理由，有一定深度
- 60-74分: 能说清项目用了什么，但缺乏设计思路或难点描述
- 0-59分: 项目描述像简历复述，无深入理解

## 技术基础/八股文 (25%)
- 90-100分: 原理理解透彻，能画图/举例说明，知道优缺点和适用场景
- 75-89分: 概念清晰，能解释基本原理，了解常见用法
- 60-74分: 知道基本概念，但原理模糊或只能背答案
- 0-59分: 概念混淆或完全不会

## 沟通表达 (15%)
- 逻辑清晰度 (5分)
- 表达完整性 (5分)
- 专业术语准确性 (5分)

## 学习潜力 (10%)
- 是否主动学习新技术
- 回答中是否展现思考过程
- 遇到未知问题时的反应

## 积极态度 (5%)
- 回答是否积极主动
- 遇到困难是否愿意尝试
- 闲聊环节的表现（积极性/参与度）"""


# ══════════════════════════════════════════════
# 自我介绍评分提示词
# ══════════════════════════════════════════════

def get_self_intro_scoring_prompt(answer: str, resume_summary: str) -> str:
    """
    生成自我介绍的评分提示词
    
    【评分重点】
    - 信息完整性（教育、实习、项目）
    - 逻辑组织能力
    - 时间控制意识
    - 突出亮点的能力
    """
    return f"""请对以下自我介绍进行评分：

【候选人回答】
{answer}

【简历概要】
{resume_summary}

【评分要求】
1. 评估信息覆盖度（是否提及关键背景）
2. 评估逻辑组织（是否有条理）
3. 评估表达能力（是否流畅自然）
4. 识别值得深挖的亮点

【输出格式】
{{
    "score": 分数(0-100),
    "dimension": "self_intro",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["待改进点"],
    "feedback": "给候选人的反馈（鼓励+建议）",
    "highlight_topics": ["值得后续深挖的话题"],
    "suggested_follow_up": "如果有的话，建议的追问方向"
}}"""


# ══════════════════════════════════════════════
# 实习/项目评分提示词
# ══════════════════════════════════════════════

def get_practice_scoring_prompt(
    answer: str,
    question: str,
    category: str,  # "internship" or "project"
    original_info: dict
) -> str:
    """
    生成实践类题目（实习/项目）的评分提示词
    
    【评分重点】
    - STAR法则应用情况
    - 技术深度和真实性
    - 个人贡献明确程度
    - 成果量化情况
    """
    import json
    category_name = "实习" if category == "internship" else "项目"
    
    return f"""请对以下{category_name}相关的回答进行评分：

【问题】
{question}

【候选人回答】
{answer}

【原始{category_name}信息（用于对比真实性）】
{json.dumps(original_info, ensure_ascii=False, indent=2)}

【评分维度】
1. **内容相关性** (25%) - 是否切题，是否答非所问
2. **STAR完整性** (25%) - Situation/Task/Action/Result 是否完整
3. **技术深度** (25%) - 是否展现真正的理解和思考
4. **个人贡献** (15%) - 是否明确自己的角色和贡献
5. **真实性** (10%) - 与原始信息是否一致，有无夸大嫌疑

【输出格式】
{{
    "score": 总分(0-100),
    "dimension": "{category}",
    "sub_scores": {{
        "relevance": 相关性得分,
        "star_completeness": STAR完整性得分,
        "technical_depth": 技术深度得分,
        "personal_contribution": 个人贡献得分,
        "authenticity": 真实性得分
    }},
    "strengths": ["优点"],
    "weaknesses": ["不足"],
    "feedback": "详细反馈（200字以内）",
    "credibility_assessment": "high/medium/low",
    "follow_up_worthiness": "high/medium/low",
    "suggested_followup": "如果值得追问，具体的追问内容"
}}"""


# ══════════════════════════════════════════════
# 八股文评分提示词
# ══════════════════════════════════════════════

def get_eight_part_scoring_prompt(
    answer: str,
    question: str,
    category: str,
    key_points: list,
    rag_context: str = ""
) -> str:
    """
    生成八股文题目的评分提示词
    
    【评分重点】
    - 概念准确性
    - 原理理解深度
    - 能否举例说明
    - 是否了解优缺点和适用场景
    
    【RAG 增强】
    rag_context 参数包含从向量库检索到的参考答案，用于：
    1. 提供标准答案作为评分基准
    2. 帮助 LLM 更准确地判断回答的正确性
    3. 减少 LLM 幻觉导致的误判
    """
    import json
    base_prompt = f"""请对以下技术基础题的回答进行评分：

【问题】
{question}

【技术分类】
{category}

【期望的关键回答要点】
{json.dumps(key_points, ensure_ascii=False) if key_points else '通用要点'}

【候选人回答】
{answer}"""

    if rag_context:
        base_prompt += f"""
{rag_context}

【评分参考说明】
以上【RAG参考资料】是该问题的标准答案和知识点，请以此作为评分基准。
如果候选人的回答与参考资料一致或更深入，应给予较高分数。
如果候选人的回答与参考资料有偏差，请明确指出错误之处。"""

    base_prompt += f"""

【评分维度】
1. **概念准确性** (30%) - 核心概念是否正确（以参考资料为基准）
2. **原理深度** (30%) - 是否理解底层原理（不只是背答案）
3. **举例能力** (20%) - 能否用例子或图示说明
4. **广度延伸** (20%) - 是否了解相关概念、优缺点、适用场景

【输出格式】
{{
    "score": 总分(0-100),
    "dimension": "eight_part",
    "sub_category": "{category}",
    "sub_scores": {{
        "accuracy": 概念准确性,
        "depth": 原理深度,
        "example": 举例能力,
        "extension": 广度延伸
    }},
    "key_points_covered": 覆盖的关键点数量,
    "total_key_points": 总关键点数,
    "misconceptions": ["错误理解（如有）"],
    "feedback": "详细反馈",
    "level_assessment": "beginner/intermediate/advanced/expert"
}}"""

    return base_prompt


# ══════════════════════════════════════════════
# 综合评分提示词（面试结束时）
# ══════════════════════════════════════════════

def get_final_score_prompt(
    all_scores: dict,
    session_summary: dict
) -> str:
    """
    生成最终综合评分的提示词
    
    【加权公式 - 2026-04-19 更新】
    final_score = practice_experience×45% + technical_knowledge×25%
                + communication×15% + potential×10% + attitude×5%
    
    其中 practice_experience = internship_avg×25% + project_avg×20%
    """
    import json
    return f"""请根据面试过程中的所有得分，计算最终综合评分：

【各阶段得分记录】
{json.dumps(all_scores, ensure_ascii=False, indent=2)}

【会话摘要】
{json.dumps(session_summary, ensure_ascii=False, indent=2)}

【加权公式】
final_score = 
    practice_experience × 45%   (实习25% + 项目20%)
  + technical_knowledge × 25%  (八股文)
  + communication × 15%        (自我介绍7% + 表达8%)
  + potential × 10%            (学习潜力)
  + attitude × 5%              (积极态度，含闲聊评估)

【输出格式】
{{
    "final_score": 最终总分(0-100),
    "grade": "等级(S/A/B/C/D)",
    "dimension_scores": {{
        "practice_experience": {{
            "weight": 0.45,
            "raw_score": 原始平均分,
            "weighted_score": 加权后得分,
            "breakdown": {{
                "internship": {{"weight": 0.25, "score": 得分, "weighted": 加权分}},
                "project": {{"weight": 0.20, "score": 得分, "weighted": 加权分}}
            }}
        }},
        "technical_knowledge": {{"weight": 0.25, "score": 得分, "weighted": 加权分}},
        "communication": {{"weight": 0.15, "score": 得分, "weighted": 加权分}},
        "potential": {{"weight": 0.10, "score": 得分, "weighted": 加权分}},
        "attitude": {{"weight": 0.05, "score": 得分, "weighted": 加权分}}
    }},
    "summary": "综合评价（3-5句话）",
    "strengths": ["核心优势（最多3条）"],
    "areas_for_improvement": ["改进建议（最多3条）"],
    "recommendation": "strong_recommend/recommend/conditional/not_recommend",
    "next_step_suggestions": ["给候选人的后续学习建议"]
}}"""
