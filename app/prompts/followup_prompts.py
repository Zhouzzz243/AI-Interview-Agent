"""
追问生成提示词模板

【职责】
定义追问决策和生成的所有Prompt

【追问策略三层决策】
1. **是否追问** (follow_up / next_question)
   - 得分 75-89: 有深挖空间 → follow_up
   - 得分 >= 90: 很好，可以兴趣追问 → interest_follow_up
   - 得分 < 75: 基础不牢或已充分回答 → next_question
   
2. **追问什么** (技术深挖 / 场景扩展 / 对比分析)
   - 回答浅尝辄止 → 技术细节追问
   - 提到有趣的项目/方案 → 兴趣追问
   - 有错误理解 → 纠正式追问
   
3. **追问配额管理**
   - 每道题最多追问2次
   - 总追问次数不超过5次
   - 连续2次低分不再追问
"""

# ══════════════════════════════════════════════
# 系统提示词（角色设定）
# ══════════════════════════════════════════════

FOLLOWUP_SYSTEM_PROMPT = """你是一位经验丰富的技术面试官，擅长通过追问来深度评估候选人的真实水平。

【追问的艺术】
1. **目的明确**：每次追问都要有明确的考察目标
2. **循序渐进**：从宏观到微观，从概念到实现
3. **给机会**：即使回答不完美，也给候选人解释的机会
4. **见好就收**：已经充分了解后及时切换下一题

【追问类型】
- **技术深挖型**：针对回答中的技术点深入询问原理或实现
- **场景扩展型**：让候选人将知识应用到新场景
- **对比分析型**：对比不同方案的优缺点
- **边界条件型**：询问极端情况或异常处理
- **纠正引导型**：委婉指出错误并引导正确方向"""


def get_followup_decision_prompt(
    question: str,
    answer: str,
    current_score: int,
    category: str,
    remaining_budget: int,
    followup_count: int
) -> str:
    """
    生成追问决策的提示词
    
    【参数说明】
    - question: 当前问题
    - answer: 候选人回答
    - current_score: 刚才给出的分数
    - category: 题目分类
    - remaining_budget: 剩余追问配额
    - followup_count: 该题目已追问次数
    
    【输出】决策结果 + 追问内容（如果决定追问）
    """
    return f"""请根据以下信息，决定是否对候选人进行追问：

【当前问题】
{question}

【候选人回答】
{answer}

【本轮得分】
{current_score}/100

【题目分类】
{category}

【追问状态】
- 剩余总配额: {remaining_budget} 次
- 本题已追问: {followup_count} 次（每题最多2次）

【决策规则】
1. **应该追问的情况 (follow_up)**:
   - 得分 75-89 分且回答有深挖空间
   - 候选人提到了感兴趣的技术/项目但没展开
   - 回答中有模糊或不完整的地方需要澄清
   
2. **兴趣追问 (interest_follow_up)**:
   - 得分 >= 90 但候选人展示了特别有价值的内容
   - 检测到自研、开源贡献、性能优化等高价值信号
   
3. **不出追问 (next_question)**:
   - 得分 < 75 且基础不扎实（避免打击信心）
   - 已经充分回答了问题
   - 本题已追问过2次
   - 剩余配额不足
   
4. **阶段切换 (phase_switch)**:
   - 当前阶段的题目已经问完
   - 需要进入下一个面试阶段

【输出格式】
{{
    "decision": "follow_up|next_question|interest_follow_up|phase_switch",
    "reason": "决策理由（一句话）",
    "confidence": 决策置信度(0.0-1.0),
    "tags": ["标签(high_value/interest/remedial/complete)"],
    "follow_up_content": "追问内容（仅当decision为follow_up或interest_follow_up时填写）",
    "followup_type": "technical_deep_dive|scenario_extension|comparison_analysis|boundary_condition|corrective_guidance",
    "expected_improvement": "期望从追问中获得什么信息"
}}"""


def generate_followup_content(
    original_question: str,
    original_answer: str,
    score: int,
    category: str,
    followup_type: str = "technical_deep_dive"
) -> str:
    """
    根据决策生成具体的追问内容
    
    【参数】
    - followup_type: 追问类型
      * technical_deep_dive: 技术深挖
      * scenario_extension: 场景扩展
      * comparison_analysis: 对比分析
      * boundary_condition: 边界条件
      * corrective_guidance: 纠正引导
    """
    type_descriptions = {
        "technical_deep_dive": "深入询问技术实现细节、底层原理",
        "scenario_extension": "将知识点应用到新的业务场景",
        "comparison_analysis": "对比不同技术方案的优劣",
        "boundary_condition": "询问极端情况、异常处理、并发场景",
        "corrective_guidance": "委婉指出可能的误解，引导正确方向"
    }
    
    return f"""请生成一道{type_descriptions.get(followup_type, '追问')}：

【原问题】
{original_question}

【原回答】
{original_answer}

【当前得分】
{score}

【题目分类】
{category}

【追问类型】
{followup_type}

【要求】
1. 追问要具体，基于候选人的回答内容
2. 不要重复原问题已经问过的内容
3. 给出适当的提示或引导
4. 控制在2-3句话以内

【输出格式】
{{
    "follow_up_question": "具体的追问内容",
    "hint": "可选的提示信息",
    "expected_focus": "这道追问想考察什么"
}}"""
