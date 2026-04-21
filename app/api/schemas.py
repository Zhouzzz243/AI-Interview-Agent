"""
API 数据模型定义（Pydantic Schemas）

【Java类比】
- 类似 Spring Boot 的 DTO (Data Transfer Object) + Swagger/OpenAPI 注解组合
- Pydantic v2 提供数据校验、序列化、文档生成一体化
- 所有 API 请求和响应的数据结构都在这里定义

【Python特性说明】
1. BaseModel: Pydantic 基类，提供数据校验和序列化能力
2. Field(): 字段元数据（描述、默认值、示例、约束条件）
3. Enum: 枚举类型（继承str方便JSON序列化）
4. Optional[X]: 可选字段（可为None，类似Java的包装类Integer vs int）
5. List[Type]: 列表类型（类似Java的List<Type>）
6. Dict[str, Any]: 字典类型（类似Map<String, Object>）

【使用示例】
from app.api.schemas import ResumeParseRequest, ChatResponse

# 创建请求对象（自动校验）
request = ResumeParseRequest(file_url="oss://xxx", user_id="123")

# 转换为字典
data = request.model_dump()

# 转换为JSON字符串
json_str = request.model_dump_json()
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ══════════════════════════════════════════════════════════
# 一、通用响应模型
# ══════════════════════════════════════════════════════════

class BaseResponse(BaseModel):
    """
    通用响应基类（所有API响应的统一格式）

    【Java类比】
    类似 Result<T> 泛型响应类：
    public class Result<T> {
        private int code;
        private String message;
        private T data;
        private long timestamp;
    }

    【设计规范】
    - code: 业务状态码（200=成功，其他=错误）
    - message: 提示信息
    - data: 业务数据（泛型）
    - timestamp: 时间戳（用于调试和日志关联）
    """
    code: int = Field(default=200, description="业务状态码")
    message: str = Field(default="success", description="提示信息")
    data: Optional[Any] = Field(default=None, description="业务数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")


class ErrorResponse(BaseModel):
    """
    错误响应模型

    【使用场景】
    - 参数校验失败
    - 业务逻辑错误
    - 系统内部错误
    """
    code: str = Field(..., description="错误码枚举值")
    message: str = Field(..., description="用户友好的错误提示")
    detail: Optional[Any] = Field(default=None, description="详细技术信息")


# ══════════════════════════════════════════════════════════
# 二、简历解析相关模型
# ══════════════════════════════════════════════════════════

class EducationInfo(BaseModel):
    """教育经历信息"""
    school: str = Field(..., description="学校名称", example="XX大学")
    degree: str = Field(..., description="学历", example="本科")
    major: str = Field(..., description="专业", example="计算机科学与技术")
    graduation_date: Optional[str] = Field(default=None, description="毕业时间", example="2026-06")
    gpa: Optional[float] = Field(default=None, description="GPA", ge=0.0, le=4.0)


class InternshipInfo(BaseModel):
    """实习经历信息"""
    company: str = Field(..., description="公司名称", example="字节跳动")
    position: str = Field(..., description="职位", example="后端开发实习生")
    duration: Optional[str] = Field(default=None, description="实习时长", example="6个月")
    description: str = Field(default="", description="工作内容描述")
    technologies: List[str] = Field(default_factory=list, description="使用的技术栈")


class ProjectInfo(BaseModel):
    """项目经验信息"""
    project_name: str = Field(..., description="项目名称", example="电商秒杀系统")
    role: str = Field(default="核心开发", description="角色", example="后端负责人")
    description: str = Field(..., description="项目描述")
    tech_stack: List[str] = Field(default_factory=list, description="技术栈", example=["Spring Boot", "Redis", "MySQL"])
    start_date: Optional[str] = Field(default=None, description="开始时间")
    end_date: Optional[str] = Field(default=None, description="结束时间")
    highlights: List[str] = Field(default_factory=list, description="项目亮点")


class SkillInfo(BaseModel):
    """技能信息"""
    category: str = Field(..., description="技能分类", example="编程语言")
    skills: List[str] = Field(..., description="技能列表", example=["Python", "Java", "Go"])
    proficiency: Optional[str] = Field(default=None, description="熟练度", example="精通")


class ParsedResume(BaseModel):
    """
    简历解析完整结果

    【说明】
    这是简历解析接口的返回数据结构
    包含结构化的教育/实习/项目/技能信息
    以及丰富度评估结果
    """
    resume_id: str = Field(..., description="简历唯一标识", example="resume_abc123")
    user_id: str = Field(..., description="用户ID", example="user_456")

    basic_info: Dict[str, str] = Field(
        default_factory=dict,
        description="基本信息（姓名/电话/邮箱等）",
        example={"name": "张三", "phone": "13800138000", "email": "zhangsan@example.com"}
    )

    education: List[EducationInfo] = Field(default_factory=list, description="教育经历列表")
    internships: List[InternshipInfo] = Field(default_factory=list, description="实习经历列表")
    projects: List[ProjectInfo] = Field(default_factory=list, description="项目经验列表")
    skills: List[SkillInfo] = Field(default_factory=list, description="技能列表")

    total_text_length: int = Field(default=0, description="简历总文本长度（字符数）")
    raw_text: Optional[str] = Field(default=None, description="原始文本（用于RAG向量化）")


class ResumeParseRequest(BaseModel):
    """简历解析请求"""
    file_url: str = Field(..., description="简历文件URL（OSS地址）", example="oss://resumes/user_123.pdf")
    user_id: str = Field(..., description="用户ID", example="user_456")


class ResumeParseResponse(BaseModel):
    """简历解析响应"""
    code: int = Field(default=200)
    message: str = Field(default="简历解析成功")
    data: ParsedResume


# ══════════════════════════════════════════════════════════
# 三、面试流程相关模型（核心！）
# ══════════════════════════════════════════════════════════

class InterviewPhase(str, Enum):
    """
    面试阶段枚举（状态机的7个状态）

    【Java类比】
    类似Java的枚举：
    public enum InterviewPhase {
        SELF_INTRO("self_introduction"),
        INTERNSHIP_QA("internship_qa"),
        ...
    }

    【状态流转规则】
    SELF_INTRO → INTERNSHIP_QA → PROJECT_QA → EIGHT_PART_QA → CHAT_MODE → FINAL_SCORE → END
    （某些阶段可以跳过，如无实习则跳过INTERNSHIP_QA）
    """
    SELF_INTRO = "self_introduction"           # 自我介绍阶段
    INTERNSHIP_QA = "internship_qa"             # 实习经历深挖阶段
    PROJECT_QA = "project_qa"                   # 项目经验深挖阶段
    EIGHT_PART_QA = "eight_part_qa"             # 八股文问答阶段
    CHAT_MODE = "chat_mode"                     # 闲聊模式（放松/鼓励）
    FINAL_SCORE = "final_score"                 # 综合评分阶段
    END = "end"                                 # 结束


class QuestionCategory(str, Enum):
    """
    题目分类枚举（11种题型）

    【用途】
    - 标记每道题的类型
    - 用于统计各类型的覆盖情况
    - 决定评分时采用哪个维度的标准
    """
    SELF_INTRODUCTION = "self_introduction"     # 自我介绍
    INTERNSHIP = "internship"                   # 实习经历
    PROJECT = "project"                         # 项目经验
    TECHNICAL_JAVASE = "technical_javase"       # JavaSE基础
    TECHNICAL_JVM = "technical_jvm"             # JVM原理
    TECHNICAL_JUC = "technical_juc"             # JUC并发
    TECHNICAL_SPRING = "technical_spring"       # Spring框架
    TECHNICAL_MYSQL = "technical_mysql"         # MySQL数据库
    TECHNICAL_REDIS = "technical_redis"         # Redis缓存
    TECHNICAL_MQ = "technical_mq"              # 消息队列
    TECHNICAL_NETWORK = "technical_network"     # 计算机网络
    CHAT = "chat"                               # 闲聊话题
    REVERSE_QUESTION = "reverse_question"       # 反问环节


class DifficultyLevel(str, Enum):
    """难度等级"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class StartInterviewRequest(BaseModel):
    """开启面试请求"""
    session_id: str = Field(..., description="会话唯一ID", example="session_abc123")
    resume_id: str = Field(..., description="已解析的简历ID", example="resume_xyz789")


class ChatRequest(BaseModel):
    """
    多轮对话请求（核心接口！）

    【说明】
    这是面试过程中最频繁调用的接口
    每次候选人回答一道题后就调用此接口
    返回：评分 + 下一题 + 反馈 + 阶段信息
    """
    session_id: str = Field(..., description="会话ID", example="session_abc123")
    content: str = Field(
        ...,
        description="候选人的回答内容",
        min_length=1,
        max_length=10000,
        example="HashMap底层是数组加链表，当链表长度超过8时会转换为红黑树..."
    )


class GeneratedQuestion(BaseModel):
    """
    生成的面试题目

    【属性说明】
    question: 题目文本
    category: 题目分类（用于统计和评分策略选择）
    difficulty: 难度等级
    expected_focus: 这道题主要考察什么（1句话）
    phase: 所属面试阶段
    """
    question: str = Field(..., description="题目内容")
    category: QuestionCategory = Field(..., description="题目分类")
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.MEDIUM, description="难度等级")
    expected_focus: Optional[str] = Field(default=None, description="考察重点")
    phase: InterviewPhase = Field(..., description="所属阶段")


class FollowUpDecision(BaseModel):
    """
    追问决策结果

    【决策取值说明】
    - follow_up: 高价值追问（得分75~89但有深挖空间）
    - next_question: 不追问，直接出下一题（最常见的情况）
    - interest_follow_up: 兴趣追问（检测到自研/开源/性能优化等信号）
    - phase_switch: 切换到下一阶段（当前阶段题目已问完）

    【属性说明】
    decision: 决策类型
    reason: 决策理由（一句话）
    follow_up_content: 如果决定追问，这里是追问的具体问题；否则为null
    confidence: 决策置信度（0.0~1.0），低于0.7倾向于next_question
    tags: 标签（high_value/interest/remedial/null）
    """
    decision: str = Field(
        ...,
        description="决策类型",
        pattern="^(follow_up|next_question|interest_follow_up|phase_switch)$"
    )
    reason: str = Field(..., description="决策理由", example="候选人提到了Redis分布式锁的实现细节")
    follow_up_content: Optional[str] = Field(default=None, description="追问内容（仅decision=follow_up时有值）")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="决策置信度")
    tags: Optional[List[str]] = Field(default=None, description="标签", example=["high_value"])


class ChatResponse(BaseModel):
    """
    多轮对话响应（面试主接口返回值）

    【这是最重要的响应模型！】

    【Java类比】
    类似Controller方法返回的复杂DTO对象，
    包含了前端需要的所有信息：分数、下一题、反馈等。

    【属性详解】
    score: 当前这道题的得分（0-100）
    feedback: AI给出的反馈意见（鼓励或指出不足）
    next_question: 下一道题目（如果is_follow_up=True则为追问内容）
    phase: 当前所处的面试阶段
    is_follow_up: 是否为追问（true=追问 false=新题目）
    question_count: 已出题目总数（含追问）
    remaining_questions: 剩余可出题目数
    decision: 追问决策详情（用于调试和分析）
    """
    score: Optional[int] = Field(default=None, description="本轮得分(0-100)", ge=0, le=100)
    feedback: Optional[str] = Field(default=None, description="AI反馈意见")
    next_question: Optional[str] = Field(default=None, description="下一道题目或追问内容")
    phase: InterviewPhase = Field(..., description="当前面试阶段")
    is_follow_up: bool = Field(default=False, description="是否为追问")
    question_count: int = Field(default=0, description="已出题目总数")
    remaining_questions: int = Field(default=15, description="剩余题目数")
    decision: Optional[FollowUpDecision] = Field(default=None, description="追问决策详情")


# ══════════════════════════════════════════════════════════
# 四、评分相关模型
# ══════════════════════════════════════════════════════════

class DimensionScore(BaseModel):
    """单维度评分结果"""
    dimension: str = Field(..., description="维度名称", example="technical")
    score: float = Field(..., description="该维度得分", ge=0.0, le=100.0)
    details: Optional[str] = Field(default=None, description="详细评价")


class FinalScoreResult(BaseModel):
    """
    最终评分结果（面试结束时返回）

    【2026-04-19 更新后的加权公式】
    final_score = practice_experience×45% + technical_knowledge×25%
                + communication×15% + potential×10% + attitude×5%

    其中：
    - practice_experience(45%) = internship_avg×25% + project_avg×20%
      （实习权重提升：真实企业经历含金量更高）
    - technical_knowledge(25%) = eight_part_avg×25%
      （八股文进一步降低占比，够用即可不要求背诵）
    - communication(15%) = self_intro×7% + 表达能力启发式×8%
    - potential(10%) = 高分回答比例 + 思考深度
    - attitude(5%) = 积极性启发式评估（含闲聊环节）

    【等级判定】
    A (优秀): >= 85分  → "技术扎实，项目经验丰富，建议直接进入二面"
    B (良好): >= 70分  → "基础扎实，部分领域可再深入，整体符合要求"
    C (合格): >= 60分  → "基础尚可，但项目深度不足，建议加强XXX方向"
    D (不合格): < 60分 → "基础薄弱，建议先补充XXX知识"
    """
    final_score: float = Field(..., description="最终总分(0-100)", ge=0.0, le=100.0)
    level: str = Field(..., description="等级(A/B/C/D)", pattern="^[ABCD]$")
    summary: str = Field(..., description="总体评价摘要", example="技术扎实，项目经验丰富...")
    dimensions: List[DimensionScore] = Field(default_factory=list, description="各维度得分明细")
    strengths: List[str] = Field(default_factory=list, description="优势分析")
    weaknesses: List[str] = Field(default_factory=list, description="待提升点")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")
    passed: bool = Field(..., description="是否通过（>=70分为通过）")


class EvaluateResponse(BaseModel):
    """综合评分接口响应"""
    code: int = Field(default=200)
    message: str = Field(default="评分完成")
    data: FinalScoreResult


# ══════════════════════════════════════════════════════════
# 五、面试计划相关模型（来自interview-followup-strategy.md）
# ══════════════════════════════════════════════════════════

class InterviewPlan(BaseModel):
    """
    面试计划（动态生成的题量分配方案）

    【来源】
    interview-followup-strategy.md §5 动态题量分配器(InterviewBudgetAllocator)

    【属性说明】
    max_questions: 题数上限（15或18）
    main_allocation: 各模块的基础题量分配字典
    follow_up_budget: 追问配额（3-5次）
    richness_level: 简历丰富度等级（rich/normal/thin）
    richness_score: 简历丰富度分数（0.0-1.0）
    """
    max_questions: int = Field(..., description="题数上限", ge=10, le=25)
    main_allocation: Dict[str, int] = Field(
        ...,
        description="各模块题量分配",
        example={
            "self_intro": 1,
            "internship": 2,
            "project": 3,
            "technical": 4,
            "chat": 1,
            "reverse_question": 1
        }
    )
    follow_up_budget: int = Field(..., description="追问配额", ge=1, le=10)
    richness_level: str = Field(..., description="丰富度等级", pattern="^(rich|normal|thin)$")
    richness_score: float = Field(..., description="丰富度分数", ge=0.0, le=1.0)

    @property
    def total_budget(self) -> int:
        """
        计算总预算（含追问）

        【Python特性】
        @property装饰器：将方法变成属性访问
        类似Java的getter方法但语法更简洁：

        Java: public int getTotalBudget() { return ...; }
        Python: plan.total_budget  # 直接像属性一样访问
        """
        base_total = sum(self.main_allocation.values())
        return base_total + self.follow_up_budget

    def to_prompt_context(self) -> str:
        """
        转换为Prompt上下文字符串（用于注入LLM Prompt中）

        【使用场景】
        在调用LLM生成问题时，将面试计划作为上下文传入，
        让LLM知道还剩多少题、应该出什么类型的题。

        【输出示例】
        '''
        【本次面试计划】
        - 题数上限: 15题
        - 简历丰富度: rich（0.76）

        【各模块题量分配】
        - 自我介绍: 1题
        - 实习经历: 2题
        - 项目经历: 3题
        - 技术八股: 4题
        - 闲聊环节: 1题
        - 反问环节: 1题

        【追问配额】剩余 4 次，请合理使用。
        '''
        """
        allocation_lines = [
            f"- {key.replace('_', ' ').title()}: {value}题"
            for key, value in self.main_allocation.items()
        ]

        return f"""
【本次面试计划】
- 题数上限: {self.max_questions}题
- 简历丰富度: {self.richness_level}（{self.richness_score}）

【各模块题量分配】
{chr(10).join(allocation_lines)}

【追问配额】剩余 {self.follow_up_budget} 次，请合理使用。
""".strip()


class RichnessResult(BaseModel):
    """
    简历丰富度评估结果

    【来源】
    interview-followup-strategy.md §4 简历丰富度算法（ResumeRichnessScorer）

    【五维度权重】
    internship(0.25) + project(0.35) + skills(0.20) + education(0.10) + overall(0.10)
    """
    total_score: float = Field(..., description="总分(0-1)", ge=0.0, le=1.0)
    level: str = Field(..., description="等级(rich/normal/thin)")
    dimension_scores: Dict[str, float] = Field(
        ...,
        description="各维度得分",
        example={"internship": 0.85, "project": 0.78, "skills": 0.72, "education": 0.85, "overall": 0.80}
    )
    allocation_hint: Dict[str, Any] = Field(
        default_factory=dict,
        description="题量分配建议"
    )


# ══════════════════════════════════════════════════════════
# 六、会话状态相关模型（Redis持久化用）
# ══════════════════════════════════════════════════════════

class ConversationTurn(BaseModel):
    """单轮对话记录"""
    turn_id: str = Field(..., description="轮次ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    phase: InterviewPhase = Field(..., description="所属阶段")
    question: str = Field(..., description="面试官问题")
    answer: str = Field(..., description="候选人回答")
    score: Optional[int] = Field(default=None, description="本轮得分")
    is_follow_up: bool = Field(default=False, description="是否为追问")
    category: Optional[QuestionCategory] = Field(default=None, description="题目分类")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class SessionState(BaseModel):
    """
    完整的面试会话状态模型（存储在Redis中）

    【Java类比】
    类似Spring Session的对象，但更复杂：
    - 包含面试进度追踪
    - 包含评分记录
    - 包含对话历史
    - 包含动态决策状态

    【存储方式】
    Redis Hash结构：
    Key: session:{session_id}
    Value: SessionState.model_dump_json() (JSON序列化)

    【生命周期】
    创建 -> 面试进行中 -> 评分 -> 结束
    TTL: 2小时（可通过配置调整）
    """
    session_id: str = Field(..., description="会话唯一ID")
    user_id: str = Field(..., description="用户ID")
    resume_id: str = Field(..., description="简历ID")
    current_phase: InterviewPhase = Field(default=InterviewPhase.SELF_INTRO, description="当前阶段")

    plan: Optional[InterviewPlan] = Field(default=None, description="面试计划（动态分配结果）")

    progress: Dict[str, int] = Field(
        default_factory=lambda: {
            "question_count": 0,
            "used_follow_ups": 0,
            "remaining_follow_ups": 3
        },
        description="进度追踪"
    )

    coverage: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "asked_internships": [],
            "asked_projects": [],
            "asked_eight_parts": [],
            "covered_modules": []
        },
        description="已覆盖记录（避免重复提问）"
    )

    scores: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="各阶段评分记录 {phase_name: [score1, score2, ...]}"
    )

    conversation_history: List[ConversationTurn] = Field(
        default_factory=list,
        description="对话历史（最近20轮）"
    )

    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")
    is_active: bool = Field(default=True, description="会话是否活跃")
