# 🎯 AI Interview Agent

> 基于 **ReAct Agent** 架构的 AI 驱动智能模拟面试系统（Python 端）

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 项目简介

本系统是一套**企业级 AI 面试模拟平台**的 Python AI 引擎，采用 **ReAct（Reasoning + Acting）Agent** 范式设计，通过 RAG 检索增强、状态机流程控制、多维评分模型等核心技术，实现从简历解析到综合评估的全链路智能面试体验。

### 核心能力

| 能力 | 说明 |
|------|------|
| 📄 **简历智能解析** | PDF/DOCX 上传 → LLM 结构化提取 → 向量化入库 |
| 🤖 **ReAct Agent 调度** | "思考→行动→观察" 循环推理，动态路由决策 |
| 🔍 **RAG 检索增强** | ChromaDB 向量检索 + 语义匹配，抑制 LLM 幻觉 |
| 📊 **多维加权评分** | 实习(18%) + 项目(24%) + 八股(28%) + 表达(15%) + 潜力(10%) + 态度(5%) |
| 💬 **多轮对话管理** | Redis 持久化 + 滑动窗口裁剪，保障上下文连贯性 |

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        系统架构概览                                  │
│                                                                     │
│  ┌──────────┐    HTTP/REST     ┌─────────────────────────┐          │
│  │          │ ◄──────────────► │                         │          │
│  │  前端    │                 │      Java 后端          │          │
│  │ (Vue)    │                 │   (Spring Boot :8082)   │          │
│  │          │                 │  • 用户管理 / 简历上传   │          │
│  └──────────┘                 │  • 面试会话 / 对话记录   │          │
│                               └──────────┬──────────────┘          │
│                                          │                          │
│                                          ▼                          │
│                               ┌─────────────────────────┐          │
│                               │  ★ Python AI Engine     │          │
│                               │   (FastAPI :8083)       │          │
│                               │                         │          │
│                               │  • ReAct Agent 编排器    │          │
│                               │  • RAG 检索增强引擎     │          │
│                               │  • 多维评分系统         │          │
│                               │  • 会话 Memory 管理     │          │
│                               └─────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

### 六层架构详解

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AI Interview Agent 六层架构                        │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 1: API 接入层 (FastAPI)                                 │  │
│  │  POST /api/resume/parse  → 简历解析+向量化                     │  │
│  │  POST /api/interview/chat → 多轮对话(出题+评分)                │  │
│  │  POST /api/interview/end  → 综合评估报告                       │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 2: Orchestrator 编排层 ⭐核心                           │  │
│  │                                                               │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │        InterviewOrchestrator (700+ 行)                   │  │  │
│  │  │                                                         │  │  │
│  │  │  状态机流转:                                             │  │  │
│  │  │  SELF_INTRO → INTERNSHIP_QA → PROJECT_QA               │  │  │
│  │  │            → EIGHT_PART_QA → CHAT_MODE                │  │  │
│  │  │            → FINAL_SCORE → END                         │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 3: Skills 技能层 (6 大 Skill 模块)                      │  │
│  │                                                               │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐    │  │
│  │  │ ResumeSkill  │ │InterviewSkill│ │ ScoringSkill       │    │  │
│  │  │ 简历解析     │ │ 智能出题     │ │ 多维评分           │    │  │
│  │  ├──────────────┤ ├──────────────┤ ├────────────────────┤    │  │
│  │  │ FollowUpSkill│ │ChatModeHandler│                     │    │  │
│  │  │ 追问策略     │ │ 闲聊模式     │                     │    │  │
│  │  └──────────────┘ └──────────────┘ └────────────────────┘    │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 4: RAG 检索增强层 ⭐亮点                                │  │
│  │                                                               │  │
│  │  ┌─────────────┐  ┌──────────────────┐  ┌────────────────┐  │  │
│  │  │Resume Vector│  │ Eight-Part Bank  │  │ Scoring Ref    │  │  │
│  │  │ DB 简历向量库│  │ 八股知识库(9方向)│  │ 评分参考库     │  │  │
│  │  │             │  │ Java/JVM/MySQL/  │  │                │  │  │
│  │  │ education   │  │ Redis/并发/网络/ │  │ 各题型标准答案 │  │  │
│  │  │ skills      │  │ Docker/RabbitMQ │  │ 和评分要点     │  │  │
│  │  │ internship  │  │ 等 300+ 题      │  │                │  │  │
│  │  │ projects    │  └────────┬─────────┘  └────────────────┘  │  │
│  │  └──────┬──────┘           │                                 │  │
│  │         └────────┬─────────┘                                 │  │
│  │                  ▼                                           │  │
│  │         Embedding: bge-large-zh-v1.5 (免费中文模型)           │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 5: Tools 工具层                                        │  │
│  │  LLMClient(GLM-4) │ OSSClient │ RedisClient │ FileParser    │  │
│  └───────────────────────────┬───────────────────────────────────┘  │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Layer 6: Memory 记忆层                                       │  │
│  │  ┌──────────────────┐  ┌──────────────────────────────────┐  │  │
│  │  │ ShortTermMemory   │  │ SessionStore (Redis Hash)       │  │  │
│  │  │ 内存上下文窗口     │  │ 持久化存储 / TTL 过期           │  │  │
│  │  │ 滑动窗口裁剪       │  │ 分布式锁 / 缓存一致性          │  │  │
│  │  └──────────────────┘  └──────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ 技术栈

| 类别 | 技术 | 用途 |
|------|------|------|
| **Web 框架** | FastAPI | 异步高性能 API 服务 |
| **LLM 大模型** | 智谱 GLM-4-Plus | 简历解析 / 出题 / 评分 / 对话 |
| **向量数据库** | ChromaDB | RAG 知识库存储与检索 |
| **Embedding** | bge-large-zh-v1.5 | 中文文本向量化 |
| **数据校验** | Pydantic v2 | 请求/响应 Schema 校验 |
| **缓存/会话** | Redis | 会话持久化 + 分布式锁 |
| **对象存储** | 阿里云 OSS | 简历文件存储 |
| **容器化** | Docker + Compose | 一键部署 |

---

## 📁 项目结构

```
AI-Interview-Agent/
├── app/
│   ├── api/                  # FastAPI 路由 & Schema 定义
│   │   ├── routes.py         # RESTful 接口定义
│   │   └── schemas.py        # Pydantic 数据模型
│   ├── orchestrator/         # ⭐ 核心：Agent 编排器
│   │   └── interview_orchestrator.py  # 700+行，状态机+技能调度
│   ├── skills/               # 技能模块层
│   │   ├── base_skill.py     # Skill 抽象基类
│   │   ├── resume_skill.py   # 简历解析 Skill
│   │   ├── interview_skill.py # 智能出题 Skill
│   │   ├── scoring_skill.py  # 多维评分 Skill
│   │   ├── followup_skill.py # STAR追问策略
│   │   └── chat_mode_handler.py  # 闲聊模式处理器
│   ├── prompts/              # Prompt 模板库
│   │   ├── resume_prompts.py
│   │   ├── interview_prompts.py
│   │   ├── scoring_prompts.py
│   │   ├── followup_prompts.py
│   │   └── chat_prompts.py
│   ├── tools/                # 基础工具层
│   │   ├── llm_client.py     # GLM-4 封装（温度参数动态调节）
│   │   ├── file_parser.py    # PDF/Word 解析
│   │   ├── oss_client.py     # 阿里云 OSS 封装
│   │   ├── redis_client.py   # Redis 连接池
│   │   └── vector_store.py   # ChromaDB 操作封装
│   ├── memory/               # ⭐ 会话记忆管理
│   │   ├── memory_manager.py # 双层记忆门面
│   │   ├── session_store.py  # Redis 持久化
│   │   └── short_term_memory.py  # 滑动窗口上下文
│   ├── rag/                  # RAG 检索增强模块
│   ├── infrastructure/       # 基础设施
│   │   ├── config.py         # 配置中心（Pydantic Settings）
│   │   ├── error_handler.py  # 全局异常处理
│   │   ├── circuit_breaker.py # 熔断降级
│   │   └── logger.py         # 日志配置
│   └── main.py               # FastAPI 应用入口
├── scripts/
│   └── import_knowledge_base.py  # 八股知识库导入脚本
├── docs/
│   ├── config.yaml          # 业务配置文件
│   ├── schema.sql           # 数据库建表 SQL
│   └── DOCKER零基础部署指南.md
├── tests/                   # 测试用例
├── .env.example             # 环境变量模板
├── .gitignore
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Redis（本地或远程）
- 智谱 AI API Key（[免费申请](https://open.bigmodel.cn)）

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/Zhouzzz243/AI-Interview-Agent.git
cd AI-Interview-Agent

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key 和配置

# 5. 启动 Redis（如未安装可用 Docker）
docker run -d -p 6379:6379 redis:alpine

# 6. 启动服务
uvicorn app.main:app --reload --port 8083
```

访问 `http://localhost:8083/docs` 查看 Swagger API 文档。

### Docker 一键部署

```bash
docker-compose up -d
```

详见 [DOCKER部署指南](docs/DOCKER零基础部署指南.md)

---

## 💡 核心设计亮点

### 1️⃣ ReAct Agent 循环引擎

```
用户输入 → Thought(思考当前阶段) → Action(选择Skill) 
         → Observation(执行结果) → 输出回复 → 循环
```

支持**动态路由决策**与**异常场景降级处理**。

### 2️⃣ 温度参数动态调节

| 场景 | Temperature | 原因 |
|------|-------------|------|
| 评分场景 | **0.3** | 低随机性，保证客观公正 |
| 出题场景 | **0.8** | 高随机性，提升题目多样性 |
| 默认场景 | **0.7** | 平衡创意与稳定性 |

### 3️⃣ Prompt 工程三重机制

1. **角色固化模板** — System Prompt 锁定面试官人设
2. **Few-Shot 示例** — 提供标准问答范例引导输出格式
3. **JSON Schema 约束** — Pydantic 强制结构化输出，错误率从 23% 降至 <2%

### 4️⃣ 会话 Memory 双层协作

```
┌─────────────────────────────────────────────┐
│              MemoryManager (门面)            │
│                                             │
│  ┌───────────────────┐  ┌────────────────┐ │
│  │ SessionStore      │  │ ShortTermMemory│ │
│  │ (Redis 持久化)    │  │ (内存 上下文)   │ │
│  │ TTL=2h / 分布式锁  │  │ 滑动窗口裁剪   │ │
│  └───────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 📊 评分体系

```
总分 = 实习经历(18%) + 项目经验(24%) + 八股文(28%) 
     + 自我介绍(7%) + 沟通表达(8%) + 学习潜力(10%) + 态度(5%)

等级: A(≥85) / B(≥70) / C(<70)
```

---

## 📄 License

MIT License

---

## 👨‍💻 Author

[Zhouzzz243](https://github.com/Zhouzzz243)
