"""
面试提问生成提示词模板

【职责】
定义面试题目生成的所有Prompt，确保：
1. 题目与候选人简历高度相关
2. 难度循序渐进
3. 覆盖多个技术维度
4. 符合真实面试场景
"""

# ══════════════════════════════════════════════
# 系统提示词（角色设定）
# ══════════════════════════════════════════════

INTERVIEW_SYSTEM_PROMPT = """你是一位资深的技术面试官，拥有10年+的Java后端开发经验，曾在一线互联网公司担任技术面试官。

【你的特点】
1. 善于根据候选人的背景定制化出题
2. 注重考察实际项目经验而非死记硬背
3. 会追问细节以判断真伪和深度
4. 给予积极的反馈和引导

【出题原则】
- 优先从简历中的技术和项目中出题（占70%）
- 补充基础八股文题目（占30%）
- 难度分布：简单(20%) + 中等(50%) + 困难(30%)
- 每道题都要有明确的考察点

【阶段适配】
不同面试阶段采用不同的策略：
- 自我介绍：开放式问题，让候选人展示自己
- 实习深挖：STAR法则追问，关注具体贡献
- 项目深挖：技术架构、难点解决、成果量化
- 八股文：由浅入深，先概念再原理再应用"""


# ══════════════════════════════════════════════
# 自我介绍阶段提示词
# ══════════════════════════════════════════════

def get_self_intro_prompt(resume_summary: str) -> str:
    """
    生成自我介绍阶段的提示词
    
    【策略】
    - 引导候选人做1-2分钟自我介绍
    - 不需要评分，只需要收集信息
    - 为后续深挖做准备
    """
    return f"""现在开始面试的自我介绍环节。

候选人简历概要：
{resume_summary}

【任务】
生成一段友好的开场白，邀请候选人做自我介绍。

【要求】
1. 语气友好、专业
2. 提及候选人的学校或专业（个性化）
3. 建议时长：1-2分钟
4. 可以给一些提示方向（如教育背景、实习经历、项目经验）

【输出格式】
{{
    "greeting": "开场白内容",
    "suggested_topics": ["建议提及的方向1", "方向2"],
    "time_hint": "建议时长"
}}"""


# ══════════════════════════════════════════════
# 实习经历深挖提示词
# ══════════════════════════════════════════════

def get_internship_question_prompt(
    internship_info: dict,
    asked_questions: list,
    difficulty: str = "medium"
) -> str:
    """
    生成实习经历的面试题
    
    【参数】
    - internship_info: 实习信息字典
    - asked_questions: 已问过的题目列表（避免重复）
    - difficulty: 难度等级 (easy/medium/hard)
    
    【策略】
    - 第一轮：了解整体工作内容和职责
    - 第二轮：STAR法则深挖具体项目/任务
    - 第三轮：技术细节和难点攻克
    """
    import json
    return f"""根据以下实习信息，出一道技术面试题：

【实习信息】
{json.dumps(internship_info, ensure_ascii=False, indent=2)}

【已问过的题目】
{asked_questions if asked_questions else '无'}

【难度要求】
{difficulty}

【出题策略】
1. 如果是第一道实习题（asked_questions为空）：
   - 问整体工作内容和职责范围
   - 了解使用了什么技术栈
   
2. 如果已经问过基础题：
   - 使用STAR法则深挖具体场景
   - 关注技术选型理由
   - 询问遇到的困难和解决方案
   
3. 如果是高难度：
   - 追问底层原理或性能优化
   - 让候选人对比不同方案

【输出格式】
{{
    "question": "题目内容",
    "category": "internship",
    "difficulty": "{difficulty}",
    "expected_focus": "这道题主要考察什么（一句话）",
    "star_aspect": "situation/task/action/result 哪个方面",
    "follow_up_directions": ["可能的追问方向1", "方向2"]
}}"""


# ══════════════════════════════════════════════
# 项目经验深挖提示词
# ══════════════════════════════════════════════

def get_project_question_prompt(
    project_info: dict,
    asked_questions: list,
    difficulty: str = "medium"
) -> str:
    """
    生成项目经验的面试题
    
    【策略】
    - 第一轮：项目概述和技术架构
    - 第二轮：核心模块设计和实现
    - 第三轮：难点攻克和性能优化
    """
    import json
    return f"""根据以下项目信息，出一道技术面试题：

【项目信息】
{json.dumps(project_info, ensure_ascii=False, indent=2)}

【已问过的题目】
{asked_questions if asked_questions else '无'}

【难度要求】
{difficulty}

【出题策略】
1. 第一道题：了解项目背景和技术选型
   - 为什么选择这个技术栈？
   - 项目的主要挑战是什么？
   
2. 后续题目：深入技术细节
   - 核心模块的设计思路
   - 数据库设计或API设计
   - 并发处理或性能优化
   
3. 高难度题目：
   - 如果让你重新设计，会怎么做？
   - 系统的扩展性和容错性

【输出格式】
{{
    "question": "题目内容",
    "category": "project",
    "difficulty": "{difficulty}",
    "expected_focus": "考察重点",
    "tech_focus": "聚焦的技术点",
    "follow_up_directions": ["追问方向"]
}}"""


# ══════════════════════════════════════════════
# 八股文问答提示词
# ══════════════════════════════════════════════

EIGHT_PART_CATEGORIES = {
    "javase": {
        "name": "JavaSE基础",
        "topics": ["集合框架", "异常处理", "反射", "泛型", "IO/NIO"],
        "easy": ["HashMap底层原理", "ArrayList vs LinkedList", "接口与抽象类区别"],
        "medium": ["ConcurrentHashMap原理", "线程池参数配置", "JVM内存模型"],
        "hard": ["CMS/G1收集器原理", "类加载机制", "字节码增强技术"]
    },
    "jvm": {
        "name": "JVM原理",
        "topics": ["内存模型", "垃圾回收", "类加载", "性能调优"],
        "easy": ["堆和栈的区别", "GC的基本概念"],
        "medium": ["GC算法对比", "JVM调优参数", "内存泄漏排查"],
        "hard": ["G1收集器详解", "逃逸分析", "JIT编译优化"]
    },
    "juc": {
        "name": "JUC并发",
        "topics": ["线程池", "锁机制", "并发容器", "原子操作"],
        "easy": ["Thread和Runnable区别", "synchronized用法"],
        "medium": ["volatile关键字", "ThreadPoolExecutor参数", "ReentrantLock"],
        "hard": ["AQS原理", "CAS底层实现", "ThreadLocal内存泄漏"]
    },
    "spring": {
        "name": "Spring框架",
        "topics": ["IOC/AOP", "Spring Boot", "事务管理", "Spring MVC"],
        "easy": ["IOC的概念", "Bean的生命周期"],
        "medium": ["AOP实现原理", "循环依赖解决", "事务传播行为"],
        "hard": ["Spring Boot自动配置原理", "Spring Cloud组件"]
    },
    "mysql": {
        "name": "MySQL数据库",
        "topics": ["索引优化", "事务隔离", "SQL tuning", "锁机制"],
        "easy": ["索引的作用", "事务ACID"],
        "medium": ["B+树原理", "MVCC实现", "慢SQL优化"],
        "hard": ["MySQL架构主从复制", "分库分表策略"]
    },
    "redis": {
        "name": "Redis缓存",
        "topics": ["数据结构", "持久化", "集群模式", "应用场景"],
        "easy": ["String/List/Hash使用场景", "缓存穿透/击穿/雪崩"],
        "medium": ["RDB/AOF对比", "Redis Cluster", "分布式锁实现"],
        "hard": ["Redis源码架构", "BigKey问题", "HotKey发现"]
    }
}


def get_eight_part_question_prompt(
    category: str,
    tech_stack: list,
    asked_categories: dict,
    difficulty: str = "medium"
) -> str:
    """
    生成八股文面试题
    
    【参数】
    - category: 技术分类 (javase/jvm/juc/spring/mysql/redis)
    - tech_stack: 候选人的技术栈（优先出相关题目）
    - asked_categories: 已问过的分类及次数 {"javase": 2, ...}
    - difficulty: 难度等级
    """
    category_info = EIGHT_PART_CATEGORIES.get(category, {})
    category_name = category_info.get("name", category)
    
    import json
    return f"""请出一道{category_name}相关的技术面试题：

【技术分类】{category}
【分类名称】{category_name}
【难度要求】{difficulty}
【候选人技术栈】{tech_stack}
【各分类已问次数】{asked_categories}

【参考题目库】
{json.dumps(category_info.get(difficulty, []), ensure_ascii=False) if category_info else '通用题目'}

【出题要求】
1. 题目要具体，不要太空泛
2. 优先结合候选人的技术栈出题
3. 如果该分类已问过多次，换一个角度或子话题
4. 中等难度要有一定深度，困难题目要触及原理

【输出格式】
{{
    "question": "题目内容",
    "category": "{category}",
    "difficulty": "{difficulty}",
    "expected_focus": "考察的核心知识点",
    "key_points": ["关键回答要点1", "要点2", "要点3"],
    "common_mistakes": ["常见错误理解1", "错误2"]
}}"""
