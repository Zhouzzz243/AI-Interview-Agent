"""
AI Interview Agent - 应用主入口（Step 11）

【Java 类比】
- 类似 Spring Boot 的启动类（带 @SpringBootApplication 注解）
- 或者类似 public static void main(String[] args) 方法
- 负责创建 FastAPI 实例、注册中间件、挂载路由、启动服务

【启动方式】
    # 开发模式（热重载）
    python -m uvicorn app.main:app --reload --port 8083

    # 生产模式
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8083 --workers 2

【应用架构】
┌─────────────────────────────────────────────┐
│               FastAPI App (本文件)            │
│                                             │
│  ┌───────────┐  ┌────────────────────────┐  │
│  │ Middleware │  │ Exception Handlers     │  │
│  │ (请求日志) │  │ (全局异常捕获)          │  │
│  └─────┬─────┘  └────────────────────────┘  │
│        ▼                                    │
│  ┌────────────────────────────────────────┐ │
│  │ API Router (routes.py)                  │ │
│  │  /api/resume/parse   → 简历解析         │ │
│  │  /api/interview/start → 开始面试        │ │
│  │  /api/interview/chat  → 多轮对话 ⭐     │ │
│  │  /api/interview/end   → 结束评分        │ │
│  │  /health              → 健康检查         │ │
│  │  /internal/resume/{id}→ 内部回调        │ │
│  └───────────────┬────────────────────────┘ │
│                  ▼                          │
│  ┌────────────────────────────────────────┐ │
│  │ InterviewOrchestrator (编排器)          │ │
│  │  ├── ScoringSkill    (LLM评分)         │ │
│  │  ├── FollowUpSkill   (追问决策)        │ │
│  │  ├── InterviewSkill  (出题)            │ │
│  │  ├── ResumeSkill     (简历解析)        │ │
│  │  └── MemoryManager   (Redis会话)       │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.config import get_settings, AppSettings
from app.infrastructure.logger import get_logger
from app.infrastructure.error_handler import register_exception_handlers
from app.api.routes import router as api_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理（FastAPI 推荐方式，替代 @on_event）

    【Java 类比】
    类似 Spring 的：
    - @PostConstruct：应用启动后执行初始化
    - @PreDestroy：应用关闭前执行清理

    【startup 阶段】
    - 加载配置并打印关键信息
    - 初始化 Redis 连接池
    - 预热 LLM Client（可选）

    【shutdown 阶段】
    - 关闭 Redis 连接
    - 释放资源
    """

    settings = get_settings()
    app_settings = settings.app
    llm_settings = settings.llm
    redis_settings = settings.redis

    logger.info(
        "app_starting",
        service=app_settings.app_name,
        version="1.0.0",
        port=app_settings.port,
        env=app_settings.app_env,
        llm_model=llm_settings.model,
        llm_configured=llm_settings.is_configured(),
        redis_host=redis_settings.host,
        redis_port=redis_settings.port,
    )

    yield

    logger.info("app_shutting_down", service=app_settings.app_name)


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例（工厂方法）

    【Java 类比】
    类似 Spring Boot 的 main 方法或 @Configuration 配置类：

    ```java
    @SpringBootApplication
    public class Application {
        public static void main(String[] args) {
            SpringApplication.run(Application.class, args);
        }
    }
    ```

    【设计理由】
    使用工厂函数而非模块级 app = FastAPI() 的原因：
    1. 方便测试时创建多个独立实例
    2. 可以根据环境变量动态配置中间件
    3. 符合依赖注入的最佳实践
    """

    settings = get_settings()

    app_settings = settings.app
    llm_settings = settings.llm

    app = FastAPI(
        title=app_settings.app_name,
        description="""
## AI Interview Agent - Python AI 服务端

基于 **ReAct Agent** 范式的智能面试模拟系统 Python 服务。

### 核心能力
- 📄 **简历解析**: LLM 智能提取简历结构化信息
- 🎯 **智能出题**: 基于简历和阶段动态生成面试题目
- 📊 **多维评分**: 5维度加权评分体系（实践42%+技术28%+沟通15%+潜力10%+态度5%）
- 🔄 **三层决策**: 规则过滤 → LLM智能决策 → 资源约束检查
- 💬 **多轮对话**: 7阶段状态机驱动的完整面试流程

### 架构设计
```
Java(Spring Boot:8082) ←HTTP→ Python(FastAPI:8083)
                              ├─ LLM(GLM-4): 出题/评分/决策
                              ├─ Redis: 会话状态管理
                              └─ ChromaDB: 向量检索(RAG)
```

### 对接文档
- [Java端接口对接规范](./docs/step11_java_api_contract.md)
- [完整链路文档](./docs/AI_Interview_完整链路文档_v1.md)
- [架构方案 v2.0](./docs/AI_Interview_Agent_完整架构方案_v2.0.md)
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ══════════════════════════════════════
    # 1. CORS 中间件（跨域支持）
    # ══════════════════════════════════════
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if app_settings.app_env == "development" else [
            "http://localhost:8082",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ══════════════════════════════════════
    # 2. 请求日志中间件
    # ══════════════════════════════════════
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """记录所有HTTP请求的耗时和状态码"""
        start_time = time.time()

        response = await call_next(request)

        process_time = (time.time() - start_time) * 1000
        logger.info(
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(process_time, 2),
        )

        response.headers["X-Process-Time"] = f"{round(process_time, 2)}ms"
        return response

    # ══════════════════════════════════════
    # 3. 注册全局异常处理器
    # ══════════════════════════════════════
    register_exception_handlers(app)

    # ══════════════════════════════════════
    # 4. 挂载 API 路由
    # ══════════════════════════════════════
    app.include_router(api_router)

    logger.info(
        "app_created",
        routes_count=len(api_router.routes),
        port=app_settings.port,
    )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app.port,
        reload=settings.app.app_env == "development",
    )
