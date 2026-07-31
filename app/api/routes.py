"""
API 路由层（Step 11）- 类似 Java 的 Controller 层

【Java 类比】
- 类似 Spring Boot 的 @RestController + @RequestMapping 组合
- 每个路由函数对应一个 @PostMapping/@GetMapping 方法
- 通过依赖注入获取 InterviewOrchestrator 服务实例

【设计原则】
1. 薄 Controller：只做参数校验 + 调用 Orchestrator + 格式化响应
2. 不包含业务逻辑，所有逻辑委托给 Orchestrator
3. 统一异常处理通过 error_handler 全局注册
4. 请求/响应模型全部定义在 schemas.py

【调用关系】
Java端(HTTP) ──→ FastAPI Router(本文件) ──→ InterviewOrchestrator ──→ Skills/Memory

【6 个接口清单】
┌──────────────────────────┬───────┬─────────────────────────────┐
│ 接口                      │ 方法  │ 说明                        │
├──────────────────────────┼───────┼─────────────────────────────┤
│ /api/resume/parse        │ POST  │ 简历解析（链路1）            │
│ /api/interview/start     │ POST  │ 开始面试（链路2）            │
│ /api/interview/chat      │ POST  │ 多轮对话（链路3）⭐核心      │
│ /api/interview/end       │ POST  │ 结束评分（链路4）            │
│ /health                  │ GET   │ 健康检查                    │
│ /internal/resume/{id}    │ GET   │ Java回调获取简历数据（内部）  │
└──────────────────────────┴───────┴─────────────────────────────┘
"""

import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.infrastructure.logger import get_logger
from app.orchestrator.interview_orchestrator import (
    InterviewOrchestrator,
    get_interview_orchestrator,
)
from app.api.schemas import (
    ResumeParseRequest,
    ResumeParseResponse,
    StartInterviewRequest,
    ChatRequest,
    EndInterviewRequest,
    ChatResponse,
    EvaluateResponse,
)
from app.infrastructure.error_handler import (
    SessionNotFoundError,
    LLMCallError,
)

logger = get_logger(__name__)

router = APIRouter()


def _build_success_response(data: Any = None, message: str = "success") -> Dict:
    """构建统一成功响应"""
    return {"code": 200, "message": message, "data": data}


@router.get("/health")
async def health_check():
    """
    健康检查接口

    【用途】
    - Java端启动时检测Python服务是否可用
    - K8s/Docker的 livenessProbe 和 readinessProbe
    - 负载均衡器的健康检查

    【返回示例】
    {
        "status": "ok",
        "service": "AI-Interview-Agent-Python",
        "version": "1.0.0",
        "timestamp": 1744972800
    }
    """
    return {
        "status": "ok",
        "service": "AI-Interview-Agent-Python",
        "version": "1.0.0",
        "timestamp": int(time.time()),
    }


@router.post("/api/resume/parse")
async def parse_resume(request: ResumeParseRequest):
    """
    简历解析接口（链路1）

    【Java类比】
    ```java
    @PostMapping("/api/resume/parse")
    public Result<String> parseResume(@RequestBody ParseRequest req) { ... }
    ```

    【触发时机】
    用户上传简历后，Java端调用此接口触发LLM解析

    【请求参数】
    - file_url: OSS上的PDF文件URL（必填）

    【返回值】
    - code: 200=成功
    - content: 结构化JSON字符串（姓名/技能/实习/项目...）

    【错误码】
    - 400: 文件格式不支持或URL无效
    - 500: LLM调用失败或文件下载失败
    - 502: AI服务暂时不可用
    """
    logger.info("api_parse_resume_called", file_url=request.file_url[:80])

    orchestrator = get_interview_orchestrator()
    result = await orchestrator.parse_resume(
        file_url=request.file_url,
        user_id=request.user_id,
    )

    if result.get("code") == 200:
        return _build_success_response(
            data=result.get("content"),
            message="简历解析成功",
        )

    error_code = result.get("code", 500)
    error_msg = result.get("error", "未知错误")

    if error_code == 503:
        raise LLMCallError(error_msg)

    return JSONResponse(status_code=error_code, content=result)


@router.post("/api/interview/start")
async def start_interview(request: StartInterviewRequest):
    """
    开始面试接口（链路2）

    【Java类比】
    ```java
    @PostMapping("/api/interview/start")
    public Result<StartVO> startInterview(@RequestBody StartReq req) { ... }
    ```

    【触发时机】
    用户点击"开始面试"按钮后，Java创建会话并调用此接口

    【请求参数】
    - session_id: 面试会话ID（Java生成的自增主键）
    - resume_id: 已解析的简历ID

    【返回值】
    - question: 第一道面试题目（自我介绍）

    【执行流程】
    ① Redis创建SessionState（TTL=7200秒）
    ② 从Java端加载简历数据（HTTP回调）
    ③ 调用InterviewSkill生成第一题
    ④ 返回题目文本

    【错误码】
    - 400: 参数校验失败
    - 404: 简历不存在或未解析
    - 500: Redis连接失败
    - 503: LLM服务不可用
    """
    logger.info(
        "api_start_interview_called",
        session_id=request.session_id,
        resume_id=request.resume_id,
    )

    orchestrator = get_interview_orchestrator()
    result = await orchestrator.start_interview(
        session_id=request.session_id,
        resume_id=request.resume_id,
    )

    if result.get("code") == 200:
        return _build_success_response(
            data={"question": result.get("question"), "sessionId": request.session_id},
            message="面试已开始",
        )

    error_code = result.get("code", 500)
    error_msg = result.get("error", "未知错误")

    if error_code in (503,):
        raise LLMCallError(error_msg)

    return JSONResponse(status_code=error_code, content=result)


@router.post("/api/interview/chat")
async def chat(request: ChatRequest):
    """
    多轮对话接口（链路3）⭐ 最核心！最高频！

    【Java类比】
    ```java
    @PostMapping("/api/interview/chat")
    public Result<ChatVO> chat(@RequestBody ChatReq req) { ... }
    ```

    【触发时机】
    每次候选人回答一道题并点击发送，Java将答案转发给Python

    【请求参数】
    - session_id: 会话ID
    - content: 候选人的回答内容（1~10000字符）

    【返回值】ChatResponse（8个字段 + decision子对象）：
    - score: 本轮得分(0-100)
    - feedback: AI反馈意见
    - nextQuestion: 下一道题或追问内容
    - phase: 当前阶段
    - isFollowUp: 是否追问
    - questionCount: 已出题目总数
    - remainingQuestions: 剩余题目数
    - decision: 追问决策详情

    【执行流程（7步）】
    ① 从Redis加载SessionState
    ② 用户回答加入短期记忆窗口
    ③ ScoringSkill多维度评分
    ④ FollowUpSkill三层决策（规则→LLM→约束）
    ⑤ 决定下一题（追问/新题/切阶段）
    ⑥ 更新Redis状态
    ⑦ 构建ChatResponse返回

    【性能说明】
    此接口包含2次LLM调用（评分+决策），预计耗时15~30秒
    Java端应设置较长的超时时间（建议60秒+）

    【错误码】
    - 400: 回答内容为空或过长
    - 404: 会话不存在或已过期
    - 500: 服务器内部错误
    - 503: LLM服务不可用
    """
    logger.info(
        "api_chat_called",
        session_id=request.session_id,
        answer_length=len(request.content),
    )

    orchestrator = get_interview_orchestrator()
    result = await orchestrator.chat(
        session_id=request.session_id,
        user_answer=request.content,
    )

    if result.get("code") == 200:
        data = result.get("data", {})
        return _build_success_response(data=data, message="OK")

    error_code = result.get("code", 500)
    error_msg = result.get("error", "未知错误")

    if error_code == 404:
        raise SessionNotFoundError(request.session_id)
    if error_code in (503,):
        raise LLMCallError(error_msg)

    return JSONResponse(status_code=error_code, content=result)


@router.post("/api/interview/end")
async def end_interview(request: EndInterviewRequest):
    """
    结束面试评分接口（链路4）

    【Java类比】
    ```java
    @PostMapping("/api/interview/end")
    public Result<EndVO> endInterview(@RequestBody EndInterviewReq req) { ... }
    ```

    【触发时机】
    用户点击"结束面试"或题目用完时自动触发

    【请求参数】
    - session_id: 会话ID（Pydantic请求体）

    【返回值】FinalScoreResult（9个字段）：
    - final_score: 最终总分(0-100)
    - level: 等级(A/B/C/D)
    - summary: 总体评价摘要
    - dimensions: 各维度得分明细
    - strengths: 优势分析列表
    - weaknesses: 待提升点列表
    - suggestions: 改进建议列表
    - passed: 是否通过(>=70)

    【评分公式】
    final = practice×42% + technical×28% + communication×15% + potential×10% + attitude×5%

    【错误码】
    - 404: 会话不存在
    - 500: 综合评分计算失败
    - 503: LLM服务不可用
    """
    logger.info("api_end_interview_called", session_id=request.session_id)

    orchestrator = get_interview_orchestrator()
    result = await orchestrator.end_interview(session_id=request.session_id)

    if result.get("code") == 200:
        data = result.get("data", {})
        return _build_success_response(data=data, message="评分完成")

    error_code = result.get("code", 500)
    error_msg = result.get("error", "未知错误")

    if error_code == 404:
        raise SessionNotFoundError(request.session_id)
    if error_code in (503,):
        raise LLMCallError(error_msg)

    return JSONResponse(status_code=error_code, content=result)


@router.get("/internal/resume/{resume_id}")
async def get_resume_data(resume_id: str):
    """
    [内部接口] 获取简历数据（供 Java 端实现后 Python 回调）

    【说明】
    此接口是 Step 11 新增的内部接口，Java端实现后 Python 通过 HTTP 回调获取简历数据。

    【两种对接模式】

    模式A（推荐）：Java端提供此接口，Python HTTP回调
    ┌──────────┐    GET /internal/resume/{id}    ┌──────────┐
    │  Python  │ ──────────────────────────────► │   Java   │
   (Orchestrator)                              (Controller)
    │          │ ◄────────────────────────────── │          │
    │          │   { parsed_content: "{JSON}" }  │          │
    └──────────┘                                └──────────┘

    模式B：Python直连MySQL读取resume表parsed_content字段
    （违反架构原则，不推荐）

    【Python端需要的数据格式】
    Python的start_interview()需要拿到简历的结构化数据，
    用于传给InterviewSkill生成个性化题目。
    期望返回格式：
    {
        "resumeId": "123",
        "parsedContent": "{\"name\":\"张三\",\"skills\":[\"Java\",...],...}",
        "parseStatus": 2,
        "rawText": "原始简历全文（用于RAG向量化）"
    }

    【Java端需要做的事】
    详见 docs/step11_java_api_contract.md

    【注意】
    - 此接口带 /internal/ 前缀，表示仅供内部服务间调用
    - 生产环境应通过内网通信，不走公网
    - 建议加签名验证或IP白名单
    """
    logger.info("internal_get_resume_called", resume_id=resume_id)

    from app.infrastructure.config import get_settings

    settings = get_settings()
    java_url = settings.java_backend_url
    java_timeout = settings.java_backend_timeout

    import httpx

    try:
        async with httpx.AsyncClient(timeout=java_timeout) as client:
            response = await client.get(
                f"{java_url}/api/internal/python/resume/{resume_id}",
                headers={"X-Internal-Service": "ai-interview-python"},
            )
            response.raise_for_status()
            return response.json()

    except httpx.TimeoutException:
        logger.warning("java_resume_api_timeout", resume_id=resume_id)
        return JSONResponse(
            status_code=504,
            content={
                "code": "JAVA_BACKEND_TIMEOUT",
                "message": "Java后端获取简历超时",
                "detail": f"resume_id={resume_id}",
            },
        )
    except httpx.HTTPStatusError as e:
        logger.warning(
            "java_resume_api_error",
            status_code=e.response.status_code,
            resume_id=resume_id,
        )
        return JSONResponse(
            status_code=e.response.status_code,
            content={
                "code": "JAVA_BACKEND_ERROR",
                "message": f"Java后端返回错误: {e.response.status_code}",
            },
        )
    except Exception as e:
        logger.exception("internal_get_resume_error", resume_id=resume_id, error=str(e))
        return JSONResponse(
            status_code=502,
            content={
                "code": "JAVA_BACKEND_UNREACHABLE",
                "message": "无法连接到Java后端服务",
                "detail": str(e) if settings.app.app_env == "development" else None,
            },
        )
