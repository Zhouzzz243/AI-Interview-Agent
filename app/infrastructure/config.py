"""
统一配置管理模块

【Java类比】
- 类似 Spring Boot 的 @ConfigurationProperties + @Value 注解组合
- 使用 pydantic-settings 库实现类型安全的配置读取
- 支持从 .env 文件和环境变量自动读取配置

【Python特性说明】
1. pydantic.BaseSettings: 自动从环境变量读取配置
2. pydantic.Field(): 提供默认值、描述、示例（类似Swagger注解）
3. 类型注解 (str, int, float): Python 3.6+ 的类型提示（运行时不强制检查）
4. Config类: 配置pydantic行为（如env_prefix前缀）

【使用方式】
from app.infrastructure.config import get_settings
settings = get_settings()
print(settings.app_name)  # -> "AI-Interview-Agent-Python"
"""

import os
from functools import lru_cache
from typing import Optional
from pathlib import Path

import yaml
from pydantic import Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


class AppSettings(BaseSettings):
    """应用基础配置（类似Spring Boot的server.*配置）"""

    app_name: str = Field(default="AI-Interview-Agent-Python", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本号")
    app_env: str = Field(default="development", description="运行环境")
    port: int = Field(default=8083, ge=1024, le=65535, description="服务端口")
    debug: bool = Field(default=True, description="调试模式")
    cors_origins: str = Field(
        default="http://localhost:8082,http://localhost:3000",
        description="CORS 允许的跨域来源（逗号分隔）"
    )

    model_config = SettingsConfigDict(env_prefix="APP_")


class LLMSettings(BaseSettings):
    """智谱AI GLM-4 LLM配置"""

    api_key: str = Field(default="", description="智谱AI API Key")
    model: str = Field(default="glm-4.7", description="模型名称")
    base_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", description="API地址")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="温度参数")
    max_tokens: int = Field(default=2000, ge=100, le=8000, description="最大Token数")
    timeout: int = Field(default=30, ge=5, le=120, description="超时时间(秒)")

    def is_configured(self) -> bool:
        """检查API Key是否已配置"""
        return bool(self.api_key and self.api_key != 'your_api_key_here')

    model_config = SettingsConfigDict(env_prefix="ZHIPUAI_")


class OSSSettings(BaseSettings):
    """阿里云OSS对象存储配置"""

    endpoint: str = Field(default="oss-cn-beijing.aliyuncs.com", description="OSS Endpoint")
    access_key_id: str = Field(default="", description="AccessKey ID")
    access_key_secret: str = Field(default="", description="AccessKey Secret")
    bucket_name: str = Field(default="", description="Bucket名称")

    def is_configured(self) -> bool:
        """检查OSS是否已配置"""
        return bool(self.access_key_id and self.access_key_secret and self.bucket_name)

    model_config = SettingsConfigDict(env_prefix="ALIYUN_OSS_")


class RedisSettings(BaseSettings):
    """Redis缓存配置"""

    host: str = Field(default="localhost", description="Redis主机地址")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis端口")
    password: Optional[str] = Field(default=None, description="Redis密码")
    db: int = Field(default=0, ge=0, le=15, description="数据库编号")
    session_ttl: int = Field(default=7200, ge=300, description="会话过期时间(秒)")

    model_config = SettingsConfigDict(env_prefix="REDIS_")


class ChromaDBSettings(BaseSettings):
    """ChromaDB向量数据库配置"""

    persist_dir: str = Field(default="./chroma_db", description="数据持久化目录")
    embedding_model: str = Field(default="BAAI/bge-large-zh-v1.5", description="Embedding模型名称")

    model_config = SettingsConfigDict(env_prefix="CHROMA_")


class InterviewSettings(BaseSettings):
    """面试流程配置"""

    default_question_limit: int = Field(default=15, ge=10, le=25, description="默认题数上限")
    extended_question_limit: int = Field(default=18, ge=15, le=25, description="扩展题数上限")
    follow_up_budget_base: int = Field(default=3, ge=1, le=10, description="基础追问配额")
    follow_up_budget_max: int = Field(default=5, ge=3, le=10, description="最大追问配额")
    followup_budget: int = Field(default=5, ge=1, le=10, description="默认追问配额")


class ScoringSettings(BaseSettings):
    """
    评分体系配置（2026-04-19 更新版）

    【设计理念】
    实践能力(45%) > 技术基础/八股文(25%) > 沟通表达(15%) > 潜力(10%) > 态度(5%)

    【权重分配理由】
    1. practice_experience (45%): 最重要！实习+项目合并评估
       - 实习25%: 真实企业环境中的工作经历，含金量高
       - 项目20%: 个人或团队项目的深度和广度
       - 很多人把实习内容写在项目经历里，真正能体现技术深度
    2. technical_knowledge (25%): 八股文进一步降低占比
       - 范围太广（9大方向），很少有人完全掌握
       - 不应成为"一票否决"的标准
       - 够用即可，不要求背诵
    3. communication (15%): 沟通能力
       - 团队协作必备，但可通过实践间接体现
    4. potential (10%): 学习潜力
       - 从回答深度和思考方式判断成长性
    5. attitude (5%): 态度积极性
       - 基础门槛，不作为主要区分维度
    """

    dimensions: dict = Field(
        default={
            # ── 核心维度（用于最终评级）──
            "practice_experience": 0.45,   # 实践能力（实习+项目）
            "technical_knowledge": 0.25,   # 技术理论基础（八股文）
            "communication": 0.15,         # 沟通表达能力
            "potential": 0.10,             # 学习潜力
            "attitude": 0.05,              # 态度积极性

            # ── 细分维度（用于内部计算）──
            "internship": 0.25,            # 实习经历（归属practice_experience）
            "project": 0.20,               # 项目经验（归属practice_experience）
            "eight_part": 0.25,            # 八股文（=technical_knowledge）
            "self_intro": 0.07,            # 自我介绍（归属communication）
        },
        description="各维度权重（总和应为1.0）"
    )
    pass_threshold: float = Field(default=70.0, ge=0.0, le=100.0, description="通过分数线")
    excellent_threshold: float = Field(default=85.0, ge=0.0, le=100.0, description="优秀分数线")


class RAGSettings(BaseSettings):
    """RAG检索增强配置"""

    chunk_size: int = Field(default=500, ge=100, le=2000, description="文本分块大小")
    chunk_overlap: int = Field(default=50, ge=0, le=500, description="分块重叠大小")
    top_k: int = Field(default=5, ge=1, le=20, description="检索返回数量")
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="相似度阈值")


class Settings(BaseSettings):
    """
    全局设置聚合类（单例模式）

    【设计模式】
    - 使用 @lru_cache 装饰器实现单例（类似Spring的Singleton Scope）
    - 所有子配置作为嵌套对象聚合
    - 支持从 config.yaml 读取额外配置
    """

    app: AppSettings = AppSettings()
    llm: LLMSettings = LLMSettings()
    oss: OSSSettings = OSSSettings()
    redis: RedisSettings = RedisSettings()
    chromadb: ChromaDBSettings = ChromaDBSettings()
    interview: InterviewSettings = InterviewSettings()
    scoring: ScoringSettings = ScoringSettings()
    rag: RAGSettings = RAGSettings()

    java_backend_url: str = Field(default="http://localhost:8082", description="Java后端地址")
    java_backend_timeout: float = Field(default=10.0, ge=1.0, le=60.0, description="Java后端HTTP超时(秒)")

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


def get_settings() -> Settings:
    """
    获取全局配置单例

    【Python特性】
    - 每次调用都重新加载 .env 文件（开发阶段方便调试）
    - 生产环境可通过环境变量控制是否缓存

    【使用示例】
    from app.infrastructure.config import get_settings

    settings = get_settings()
    print(settings.llm.api_key)     # 智谱AI API Key
    print(settings.redis.host)       # Redis地址
    print(settings.app.port)         # 服务端口
    """
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        try:
            load_dotenv(env_path, encoding="utf-8", override=True)
        except Exception as e:
            print(f"Warning: Failed to load .env file: {e}")
            # 尝试不带编码参数加载
            load_dotenv(env_path, override=True)
    return Settings()


def load_yaml_config(yaml_path: str = "config.yaml") -> dict:
    """
    从YAML文件加载额外配置

    【参数】
    yaml_path: YAML文件路径（默认为项目根目录下的config.yaml）

    【返回】
    dict: 解析后的配置字典

    【异常】
    FileNotFoundError: 文件不存在时抛出
    yaml.YAMLError: YAML格式错误时抛出

    【使用场景】
    用于加载不适合放在环境变量中的复杂配置结构
    （如评分维度权重、RAG参数等）
    """
    if not os.path.exists(yaml_path):
        return {}

    with open(yaml_path, 'r', encoding='utf-8') as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"⚠️ YAML配置文件解析失败: {e}")
            return {}
