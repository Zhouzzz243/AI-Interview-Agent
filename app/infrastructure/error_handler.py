"""
统一错误处理模块

【Java类比】
- 类似 Spring Boot 的 @ControllerAdvice + @ExceptionHandler 组合
- 自定义异常体系（类似自定义RuntimeException体系）
- FastAPI 的 exception_handler 装饰器实现全局异常捕获

【Python特性说明】
1. 自定义异常类: 继承 Exception，添加 error_code 和 detail 属性
2. FastAPI exception_handler: 类似 @ExceptionHandler，但用装饰器语法
3. Pydantic ValidationError: 自动校验失败时的异常类型
4. HTTPException: FastAPI 内置的HTTP异常类

【错误响应格式】
{
    "code": "RESUME_PARSE_ERROR",      // 错误码（枚举值）
    "message": "简历解析失败",           // 用户友好的提示信息
    "detail": "PDF文件损坏无法读取"       // 详细技术信息（开发环境显示）
}

【使用示例】
# 抛出自定义异常
from app.infrastructure.error_handler import ResumeParseError, SessionNotFoundError

raise ResumeParseError("PDF文件格式不支持")
raise SessionNotFoundError(session_id="abc123")

# 在路由中自动被捕获（无需try-except）
"""

from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError


class ErrorCode(str, Enum):
    """
    错误码枚举（类似Java的错误码常量类）

    【命名规范】
    - 全大写 + 下划线分隔
    - 格式: 模块_具体错误
    - 示例: RESUME_PARSE_ERROR, LLM_CALL_TIMEOUT
    """
    SUCCESS = "SUCCESS"

    # 简历相关 (1xxx)
    RESUME_PARSE_ERROR = "RESUME_PARSE_ERROR"
    RESUME_FILE_TOO_LARGE = "RESUME_FILE_TOO_LARGE"
    RESUME_UNSUPPORTED_FORMAT = "RESUME_UNSUPPORTED_FORMAT"

    # LLM调用相关 (2xxx)
    LLM_CALL_ERROR = "LLM_CALL_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_QUOTA_EXCEEDED = "LLM_QUOTA_EXCEEDED"

    # 会话相关 (3xxx)
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_PHASE = "INVALID_PHASE"

    # OSS相关 (4xxx)
    OSS_UPLOAD_ERROR = "OSS_UPLOAD_ERROR"
    OSS_DOWNLOAD_ERROR = "OSS_DOWNLOAD_ERROR"
    OSS_FILE_NOT_FOUND = "OSS_FILE_NOT_FOUND"

    # 向量数据库相关 (5xxx)
    VECTOR_DB_ERROR = "VECTOR_DB_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    SEARCH_FAILED = "SEARCH_FAILED"

    # 通用错误 (9xxx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"


class InterviewBaseError(Exception):
    """
    面试系统基础异常类（类似Java的自定义RuntimeException）

    【设计模式】
    - 所有业务异常都继承此类
    - 统一的错误码和消息格式
    - 支持链式异常（cause参数）

    【属性说明】
    error_code: ErrorCode枚举值，用于程序化判断
    message: str, 用户可见的错误提示
    detail: Optional[str], 详细技术信息（可选）
    http_status: int, HTTP状态码（默认500）
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        detail: Optional[str] = None,
        http_status: int = 500
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.detail = detail
        self.http_status = http_status

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式（用于JSON序列化）

        【返回示例】
        {
            "code": "RESUME_PARSE_ERROR",
            "message": "简历解析失败",
            "detail": "PDF文件损坏"
        }
        """
        result = {
            "code": self.error_code.value,
            "message": self.message
        }
        if self.detail:
            result["detail"] = self.detail
        return result


# ========== 具体异常类（继承基础异常）==========

class ResumeParseError(InterviewBaseError):
    """简历解析异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.RESUME_PARSE_ERROR,
            detail=detail,
            http_status=400
        )


class LLMCallError(InterviewBaseError):
    """LLM调用异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_CALL_ERROR,
            detail=detail,
            http_status=502  # Bad Gateway（上游服务错误）
        )


class LLMTimeoutError(InterviewBaseError):
    """LLM调用超时异常"""
    def __init__(self, message: str = "LLM请求超时", detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_TIMEOUT,
            detail=detail,
            http_status=504  # Gateway Timeout
        )


class FileParseError(InterviewBaseError):
    """文件解析异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.RESUME_PARSE_ERROR,
            detail=detail,
            http_status=400
        )


class EmbeddingError(InterviewBaseError):
    """Embedding 向量化异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.EMBEDDING_ERROR,
            detail=detail,
            http_status=500
        )


class SessionNotFoundError(InterviewBaseError):
    """会话未找到异常"""
    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 {session_id} 不存在或已过期",
            error_code=ErrorCode.SESSION_NOT_FOUND,
            detail=f"Session ID: {session_id}",
            http_status=404
        )


class InvalidPhaseError(InterviewBaseError):
    """无效阶段转换异常"""
    def __init__(self, message: str, current_phase: str = "", target_phase: str = ""):
        detail = f"当前阶段: {current_phase}, 目标阶段: {target_phase}" if (current_phase or target_phase) else None
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_PHASE,
            detail=detail,
            http_status=400
        )


class OssError(InterviewBaseError):
    """OSS操作异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.OSS_UPLOAD_ERROR,
            detail=detail,
            http_status=502
        )


class VectorDbError(InterviewBaseError):
    """向量数据库异常"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.VECTOR_DB_ERROR,
            detail=detail,
            http_status=500
        )


def register_exception_handlers(app: FastAPI):
    """
    注册全局异常处理器（在FastAPI应用启动时调用）

    【Java类比】
    类似 @ControllerAdvice 类中的多个 @ExceptionHandler 方法：
    
    @ControllerAdvice
    public class GlobalExceptionHandler {
        @ExceptionHandler(ResumeParseException.class)
        public ResponseEntity<?> handleResumeError(ResumeParseException e) { ... }
        
        @ExceptionHandler(Exception.class)
        public ResponseEntity<?> handleGenericError(Exception e) { ... }
    }

    【使用方式】
    from fastapi import FastAPI
    from app.infrastructure.error_handler import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)  # 注册所有异常处理器

    【处理优先级】
    1. InterviewBaseError（自定义业务异常）- 最高优先级
    2. ValidationError（Pydantic校验异常）- 参数校验失败
    3. Exception（兜底）- 捕获所有未处理的异常
    """

    @app.exception_handler(InterviewBaseError)
    async def handle_interview_error(request: Request, exc: InterviewBaseError):
        """
        处理所有自定义业务异常

        【返回格式】
        HTTP Status: exc.http_status
        Body: {"code": "...", "message": "...", "detail": "..."}
        """
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict()
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, exc: ValidationError):
        """
        处理Pydantic数据校验异常

        【触发场景】
        - API请求体字段缺失或类型错误
        - 字段值不满足验证规则（如email格式、数值范围等）

        【返回示例】
        {
            "code": "VALIDATION_ERROR",
            "message": "请求参数校验失败",
            "detail": [
                {"field": "session_id", "message": "Field required"},
                {"field": "score", "message": "Input should be less than 100"}
            ]
        }
        """
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            })

        return JSONResponse(
            status_code=422,  # Unprocessable Entity
            content={
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "请求参数校验失败",
                "detail": errors
            }
        )

    @app.exception_handler(Exception)
    async def handle_generic_error(request: Request, exc: Exception):
        """
        兜底异常处理器（捕获所有未处理的异常）

        【安全注意事项】
        - 生产环境不要返回详细的异常堆栈信息！
        - 只记录到日志，返回通用错误消息给用户
        - 开发环境可以返回详细信息方便调试
        """
        from app.infrastructure.logger import get_logger
        logger = get_logger(__name__)

        logger.error(
            "未处理的异常",
            error=str(exc),
            path=request.url.path,
            method=request.method,
            exc_info=True  # 记录完整堆栈
        )

        return JSONResponse(
            status_code=500,
            content={
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "服务器内部错误，请稍后重试",
                "detail": str(exc) if app.debug else None
            }
        )
