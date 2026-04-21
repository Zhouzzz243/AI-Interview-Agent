# Docker 零基础部署指南 - AI Interview Agent Python

> **目标读者**：从未用过 Docker 的人，跟着做就能跑起来
> **预计时间**：30 分钟

---

## 一、Docker 是什么？（一句话理解）

**Docker = 轻量级虚拟机 + 自动化环境配置**

```
没有 Docker：
  你的电脑 → 装 Python → pip install → 可能报错 → 换电脑又要重装

有 Docker：
  写一个配置文件（Dockerfile）→ docker-compose up → 任何机器都能跑
```

**类比**：
- 传统方式 = 自己买菜、切菜、炒菜（每次都要重复）
- Docker = 点外卖（别人帮你做好，你直接吃）

---

## 二、安装 Docker Desktop（Windows）

### 步骤1：下载安装包

1. 打开浏览器访问：https://www.docker.com/products/docker-desktop/
2. 点击 **Download for Windows**
3. 下载 `Docker Desktop Installer.exe`（约 500MB）

### 步骤2：安装

1. 双击运行安装程序
2. **勾选 "Use WSL 2 instead of Hyper-V"**（推荐，性能更好）
3. 点击 OK，等待安装完成
4. 安装完成后**重启电脑**

### 步骤3：验证安装成功

打开 PowerShell（或 CMD），输入：

```powershell
docker --version
docker-compose --version
```

看到类似输出就说明装好了：

```
Docker version 24.x.x, build xxxxx
Docker Compose version v2.x.x
```

### ⚠️ 常见问题

| 问题 | 解决方法 |
|------|---------|
| 提示需要 WSL 2 | 打开 PowerShell 运行 `wsl --install`，然后重启 |
| 提示需要开启虚拟化 | 重启电脑进 BIOS 开启 VT-x/AMD-V |
| Docker 启动很慢 | 首次启动正常，后续会快 |

---

## 三、用 Docker 部署你的项目

### 项目结构（你需要创建的文件）

```
AI-Interview-Agent-python/
├── app/                          # 已有的代码
├── chroma_db/                    # ChromaDB 数据目录
├── docs/
├── tests/
├── requirements.txt              # 已有
├── .env                          # 已有
│
├── Dockerfile                    # ← 新建：Python 服务镜像定义
├── docker-compose.yml            # ← 新建：编排所有服务
└── knowledge_base/               # ← 新建：放你的 PDF/Word 八股文文档
    ├── java_八股文.pdf
    ├── mysql_八股文.pdf
    └── redis_八股文.docx
```

---

### 文件1：Dockerfile（Python 服务镜像）

在项目根目录新建 `Dockerfile`：

```dockerfile
# 使用 Python 3.10 官方镜像作为基础
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量（避免 Python 缓冲导致日志延迟）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 先复制依赖文件（利用 Docker 缓存层，只有依赖变了才重新安装）
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目代码
COPY . .

# 创建 ChromaDB 数据持久化目录
RUN mkdir -p /data/chroma_db

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**逐行解释：**

```dockerfile
FROM python:3.10-slim        # 基础镜像：Python 3.10 精简版（小）
WORKDIR /app                  # 进入容器后的默认目录
COPY requirements.txt .       # 把依赖文件复制到容器里
RUN pip install ...           # 在容器内安装依赖
COPY . .                      # 把整个项目代码复制进去
EXPOSE 8000                   # 告诉外界这个服务用 8000 端口
CMD ["uvicorn", ...]          # 容器启动时运行的命令
```

---

### 文件2：docker-compose.yml（一键启动所有服务）

在项目根目录新建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  # ════════════════════════════
  # Java 后端服务
  # ════════════════════════════
  java-backend:
    image: your-java-image:latest  # 替换为你的 Java 镜像
    # 或者 build: ./java-backend    # 如果本地构建
    container_name: ai-interview-java
    ports:
      - "8082:8082"            # 本地8082 → 容器8082
    environment:
      # Python Agent 地址（Docker 内部使用服务名）
      - PYTHON_AGENT_URL=http://python-agent:8083
      # 其他 Java 配置...
    depends_on:
      - redis
    restart: unless-stopped
    networks:
      - interview-network

  # ════════════════════════════
  # Python AI Agent 服务
  # ════════════════════════════
  python-agent:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ai-interview-python
    ports:
      - "8083:8083"            # 本地8083 → 容器8083
    environment:
      # Java 后端地址（Docker 内部使用服务名）
      - JAVA_BACKEND_URL=http://java-backend:8082
      # Redis 配置
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=${REDIS_PASSWORD:-}
      # ChromaDB 配置
      - CHROMADB_PERSIST_DIR=/data/chroma_db
      # LLM API Key
      - ZHIPUAI_API_KEY=${ZHIPUAI_API_KEY}
      - ZHIPUAI_MODEL=${ZHIPUAI_MODEL:-glm-4}
    volumes:
      # ChromaDB 数据持久化（容器重启数据不丢）
      - ./chroma_db:/data/chroma_db
      # 知识库文档目录（挂载进去方便导入）
      - ./knowledge_base:/data/knowledge_base:ro
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped     # 崩溃自动重启
    networks:
      - interview-network

  # ════════════════════════════
  # Redis 服务
  # ════════════════════════════
  redis:
    image: redis:7-alpine      # Alpine 版本很小（~40MB）
    container_name: ai-interview-redis
    ports:
      - "6379:6379"
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD:-}
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data        # Redis 数据持久化
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-}", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped
    networks:
      - interview-network

# ════════════════════════════
# 数据卷（持久化存储）
# ════════════════════════════
volumes:
  redis_data:

# 网络（让容器之间可以互相通信）
networks:
  interview-network:
    driver: bridge
```

**逐段解释：**

```yaml
services:
  python-agent:          # 第一个服务：你的 Python 项目
    build: .             # 用当前目录的 Dockerfile 构建镜像
    ports:               # 端口映射
      - "8000:8000"      # 外部访问 localhost:8000 → 转发到容器的 8000
    environment:         # 环境变量（相当于 .env 的内容）
    volumes:             # 目录挂载（把本机目录映射到容器内）
      - ./chroma_db:/data/chroma_db  # 本机的 chroma_db → 容器的 /data/chroma_db
    depends_on:          # 依赖关系（Redis 启动后才启动 Python）
    
  redis:                 # 第二个服务：Redis
    image: redis:7-alpine # 直接用官方镜像，不用自己写 Dockerfile
```

---

### 文件3：.env 更新（添加 Docker 相关变量）

确保 `.env` 文件包含这些变量：

```env
# ===== LLM 配置 =====
ZHIPUAI_API_KEY=你的API密钥
ZHIPUAI_MODEL=glm-4

# ===== Redis 配置 =====
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=          # 可选，不设密码就留空

# ===== Java 后端地址 =====
JAVA_BACKEND_URL=http://localhost:8082

# ===== ChromaDB 配置 =====
CHROMADB_PERSIST_DIR=./chroma_db
CHROMADB_EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5

# ===== RAG 配置 =====
RAG_TOP_K=5
RAG_ENABLED=true
```

---

## 四、开始部署（三步走）

### Step 1：构建并启动

在项目根目录打开 PowerShell：

```powershell
# 构建镜像（首次需要下载基础镜像，约 200MB）
docker-compose build

# 启动所有服务（后台运行）
docker-compose up -d
```

看到以下输出说明成功了：

```
Creating network "ai-interview_interview-network" done
Creating volume "ai-interview_redis_data" done
Creating ai-interview-redis ... done
Creating ai-interview-python ... done
```

### Step 2：验证服务是否正常运行

```powershell
# 查看容器状态（应该都是 Up 状态）
docker-compose ps

# 查看 Python 日志（确认没有报错）
docker-compose logs python-agent

# 测试 API 是否能访问
curl http://localhost:8000/docs
```

### Step 3：日常操作命令

```powershell
# 停止所有服务
docker-compose down

# 重启某个服务
docker-compose restart python-agent

# 查看实时日志
docker-compose logs -f python-agent

# 进入容器内部（调试用）
docker exec -it ai-interview-python bash

# 重新构建并启动（代码改了之后用这个）
docker-compose up -d --build
```

---

## 五、部署到阿里云 ECS

### 前提条件

1. 你有一台阿里云 ECS（推荐配置：2核4G，带宽 3Mbps 以上）
2. 已经安装了 Docker Desktop 或 Docker Engine
3. 服务器开放了安全组端口：**8000（Python）、6379（Redis）、22（SSH）**

### 部署步骤

```bash
# 1. SSH 登录到阿里云
ssh root@你的阿里云公网IP

# 2. 安装 Docker（如果还没装）
curl -fsSL https://get.docker.com | sh
systemctl start docker
systemctl enable docker

# 3. 安装 Docker Compose
pip install docker-compose
# 或者用官方脚本：
# curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
# chmod +x /usr/local/bin/docker-compose

# 4. 上传代码到服务器（在你本地电脑执行）
scp -r ./AI-Interview-Agent-python root@你的阿里云公网IP:/root/

# 5. 在服务器上进入项目目录
cd /root/AI-Interview-Agent-python

# 6. 修改 .env 中的 IP 地址
vim .env
# 把 JAVA_BACKEND_URL 改成实际的 Java 后端地址

# 7. 构建并启动
docker-compose build
docker-compose up -d

# 8. 验证
curl http://localhost:8000/docs
```

### 访问测试

浏览器打开：`http://你的阿里云公网IP:8000/docs`

应该能看到 Swagger API 文档页面。

---

## 六、常见问题排查

| 问题 | 排查命令 | 解决方法 |
|------|---------|---------|
| 容器一直重启 | `docker-compose logs python-agent` | 检查日志中的错误信息 |
| 端口被占用 | `netstat -ano \| findstr :8000` | 杀掉占用端口的进程或换端口 |
| Redis 连接失败 | `docker-compose logs redis` | 检查 Redis 是否正常启动 |
| ChromaDB 数据丢失 | `ls -la ./chroma_db/` | 确保 volume 挂载正确 |
| 依赖安装失败 | `docker-compose build --no-cache` | 清除缓存后重新构建 |
| 内存不足 | `free -h` | 升级 ECS 配置或限制 Redis 内存 |

---

## 七、面试怎么讲 Docker？

> "我用 Docker Compose 编排了三个服务：Python Agent + Redis + ChromaDB。
>
> **为什么用 Docker？**
> 1. **环境一致性**：开发环境和生产环境完全一致，不会出现'在我电脑能跑'的问题
> 2. **快速部署**：新服务器只需要 `docker-compose up` 就能启动，不用手动配环境
> 3. **资源隔离**：每个服务独立运行，互不影响
>
> **我的架构是：**
> ```
> docker-compose.yml
> ├── python-agent (自定义 Dockerfile)
> │   ├── 基于 python:3.10-slim 镜像
> │   ├── 安装 FastAPI + ChromaDB + 依赖
> │   ├── 暴露 8000 端口
> │   └── 挂载 chroma_db 数据卷
> │
> └── redis (官方 redis:7-alpine)
>     ├── 设置密码和内存限制
>     ├── 数据持久化到 volume
>     └── 健康检查（确保可用才启动 Python）
> ```
>
> **关键点：**
> - 用 `volumes` 做**数据持久化**（ChromaDB 和 Redis 数据不因容器重启而丢失）
> - 用 `depends_on` + `healthcheck` 保证**启动顺序**（Redis 就绪后再启动 Python）
> - 用 `restart: unless-stopped` 实现**崩溃自愈**（进程挂了自动重启）"

---

## 八、Docker 核心概念速查表

| 概念 | 类比 | 说明 |
|------|------|------|
| **Image（镜像）** | ISO 文件 / 安装包 | 只读的模板，用来创建容器 |
| **Container（容器）** | 运行中的虚拟机 | 镜像的实例，可以启动/停止/删除 |
| **Dockerfile** | 安装脚本 | 定义如何构建镜像的文本文件 |
| **docker-compose.yml** | 编排文件 | 定义多个容器如何协同工作 |
| **Volume（数据卷）** | U盘/外接硬盘 | 容器和主机之间的共享存储 |
| **Network（网络）** | 局域网交换机 | 让不同容器之间互相通信 |
| **Registry（仓库）** | 应用商店 | 存储和分发镜像的地方（如 Docker Hub） |

---

**记住这几个核心命令就够了：**
```bash
docker-compose up -d      # 启动所有服务（后台运行）
docker-compose down       # 停止并删除所有容器
docker-compose logs -f    # 查看实时日志
docker-compose ps         # 查看服务状态
docker-compose restart    # 重启服务
```
