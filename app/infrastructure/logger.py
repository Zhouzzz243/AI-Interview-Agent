"""
结构化日志模块

【Java类比】
- 类似 SLF4J + Logback 的组合
- structlog 库提供结构化JSON日志输出（生产环境推荐）
- 开发环境支持彩色控制台输出

【Python特性说明】
1. structlog: 结构化日志库，日志以字典形式存储
2. 日志级别: DEBUG < INFO < WARNING < ERROR < CRITICAL（类似Logback）
3. get_logger() 工厂函数: 类似 LoggerFactory.getLogger()
4. 上下文绑定: 可自动绑定request_id等上下文信息

【配置方式】
开发模式: 彩色控制台输出（易读）
生产模式: JSON格式输出（方便ELK收集）

【使用示例】
from app.infrastructure.logger import get_logger

logger = get_logger(__name__)
logger.info("用户登录成功", user_id="123", ip="192.168.1.1")
# 输出: [2024-01-15 10:30:00] INFO  [module.name] 用户登录成功 user_id=123 ip=192.168.1.1
"""

import logging
import sys
from typing import Optional

import structlog
from structlog.dev import ConsoleRenderer


def setup_logging(
    log_level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None
):
    """
    初始化日志系统（应用启动时调用一次即可）

    【参数】
    log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    json_output: 是否使用JSON格式输出（True=生产环境, False=开发环境带颜色）
    log_file: 可选的日志文件路径

    【调用时机】
    在 FastAPI 的 startup 事件中调用：
    @app.on_event("startup")
    async def startup():
        setup_logging(log_level="INFO", json_output=False)

    【输出格式对比】
    开发模式(json_output=False):
        [2024-01-15 10:30:00] INFO  [app.main] 用户登录成功 user_id=123

    生产模式(json_output=True):
        {"timestamp":"2024-01-15T10:30:00","level":"info","event":"用户登录成功","user_id":123,"logger":"app.main"}
    """

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output:
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=getattr(logging, log_level.upper()),
        )
    else:
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True)
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=getattr(logging, log_level.upper()),
        )

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    获取日志记录器实例（工厂方法）

    【参数】
    name: 通常传入 __name__（当前模块名）
         例如在 app/main.py 中调用：get_logger(__name__) -> logger名为 "app.main"

    【返回】
    structlog.BoundLogger: 支持链式调用的日志器

    【使用示例】
    # 方式1：获取模块级logger（推荐）
    logger = get_logger(__name__)

    # 方式2：绑定额外上下文
    logger = get_logger(__name__).bind(request_id="abc123")

    # 记录不同级别的日志
    logger.debug("调试信息", variable=value)       # 详细调试信息
    logger.info("正常信息", user_id="123")           # 一般业务日志
    logger.warning("警告信息", retry_count=3)        # 需要注意的情况
    logger.error("错误信息", error=str(e))           # 错误发生
    logger.critical("严重错误", system="down")        # 系统级故障

    【与Java SLF4J对比】
    Java:  private static final Logger logger = LoggerFactory.getLogger(MyClass.class);
    Python: logger = get_logger(__name__)
    """
    return structlog.get_logger(name)
