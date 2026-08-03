"""
面试阶段提示词模块 —— 集中管理系统提示词

【Java 类比】
类似 Java 中的消息资源文件或配置常量类：
```java
public class InterviewPrompts {
    public static final String SELF_INTRO = "你是专业的面试官...";
    // ...
}
```

【设计意图】
- 从 orchestrator 中抽离硬编码的提示词字符串
- 便于后续多语言支持、A/B 测试、模板化
- 单一职责：只管理提示词文本，不包含业务逻辑
"""

from app.api.schemas import InterviewPhase

# ══════════════════════════════════════════════
# 各阶段系统提示词
# ══════════════════════════════════════════════

PHASE_PROMPTS = {
    InterviewPhase.SELF_INTRO: "你是专业的面试官，正在引导候选人做自我介绍。",
    InterviewPhase.INTERNSHIP_QA: "你是技术面试官，正在深入询问候选人的实习经历。",
    InterviewPhase.PROJECT_QA: "你是技术面试官，正在深入询问候选人的项目经验。",
    InterviewPhase.EIGHT_PART_QA: "你是技术面试官，正在考察候选人的技术基础知识。",
    InterviewPhase.CHAT_MODE: "你现在处于轻松的闲聊模式，可以聊一些非技术话题。",
    InterviewPhase.FINAL_SCORE: "面试即将结束，准备给出综合评价。",
}

# 兜底提示词
DEFAULT_PROMPT = "你是专业的面试官。"


def get_phase_prompt(phase: InterviewPhase) -> str:
    """根据阶段获取系统提示词"""
    return PHASE_PROMPTS.get(phase, DEFAULT_PROMPT)
