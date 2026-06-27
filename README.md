<p align="center">
  <!-- Logo placeholder: replace with your project logo -->
  <h1 align="center">🧠 知识库智能运维 Agent 系统</h1>
  <p align="center">
    <em>企业级智能对话和运维助手，支持 RAG 知识库问答和 AIOps 智能诊断</em><br>
    <em>Enterprise-grade intelligent assistant — RAG knowledge-base Q&A & AIOps diagnostics</em>
  </p>
  <p align="center">
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python&logoColor=white" alt="Python"></a>
    <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.109+-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI"></a>
    <a href="https://www.langchain.com/"><img src="https://img.shields.io/badge/LangChain-latest-ff6f00.svg?logo=langchain&logoColor=white" alt="LangChain"></a>
    <a href="https://milvus.io/"><img src="https://img.shields.io/badge/Milvus-vector--db-00A1EA.svg?logo=milvus&logoColor=white" alt="Milvus"></a>
    <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-✓-2496ED.svg?logo=docker&logoColor=white" alt="Docker"></a>
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License"></a>
  </p>
</p>

---

<details open>
<summary><strong>📑 目录 / Table of Contents</strong></summary>

- [✨ 核心特性 / Core Features](#-核心特性--core-features)
- [🛠️ 技术栈 / Tech Stack](#️-技术栈--tech-stack)
- [🚀 快速开始 / Quick Start](#-快速开始--quick-start)
- [📡 API 接口 / API Reference](#-api-接口--api-reference)
- [📁 项目结构 / Project Structure](#-项目结构--project-structure)
- [⚙️ 配置说明 / Configuration](#️-配置说明--configuration)
- [🎯 AIOps 智能运维 / AIOps Intelligent Operations](#-aiops-智能运维--aiops-intelligent-operations)
- [📝 开发指南 / Development Guide](#-开发指南--development-guide)
- [🐛 常见问题 / FAQ](#-常见问题--faq)
- [📚 参考资源 / References](#-参考资源--references)
- [📄 许可证 / License](#-许可证--license)

</details>

---

## ✨ 核心特性 / Core Features

| 特性 | 说明 |
|------|------|
| 🤖 **智能对话** / Intelligent Chat | LangChain 多轮对话 + 流式输出 / Multi-turn conversation with streaming |
| 📚 **RAG 问答** / RAG Q&A | 向量检索增强，支持文档上传、自动建立向量索引、自动更新知识库 / Vector retrieval with auto-indexing |
| 🔧 **AIOps 诊断** / AIOps Diagnostics | Plan-Execute-Replan 自动故障诊断和根因分析 / Automated root-cause analysis |
| 🌐 **Web 界面** / Web UI | 现代化 UI，支持快速问答与流式对话两种模式 / Modern UI with two chat modes |
| 🔌 **MCP 集成** / MCP Integration | 日志查询和监控数据工具接入 / Log query & monitoring data tools |

---

## 🛠️ 技术栈 / Tech Stack

| 层级 | 技术 |
|------|------|
| **框架** / Framework | FastAPI + LangChain + LangGraph |
| **LLM** | 阿里云 DashScope (通义千问) / Alibaba DashScope (Qwen) |
| **向量库** / Vector DB | Milvus |
| **工具协议** / Tool Protocol | MCP (Model Context Protocol) |

---

## 🚀 快速开始 / Quick Start

### 环境要求 / Prerequisites

- Python 3.10+
- 阿里云 DashScope API Key（[获取地址](https://dashscope.aliyun.com/)）/ [Get API Key](https://dashscope.aliyun.com/)

<details>
<summary><strong>🐧 Linux / macOS</strong></summary>

```bash
# 1. 克隆项目 / Clone
git clone <repository_url>
cd super_biz_agent_py

# 2. 安装依赖（推荐使用 uv）/ Install dependencies (uv recommended)
# 方式 1: 使用 uv / via uv
pip install uv
uv venv
source .venv/bin/activate
uv pip install -e .

# 方式 2: 使用 pip / via pip
pip install -e .

# 3. 编辑配置文件 / Configure
# 首次使用需要编辑 .env 文件，填入你的 DASHSCOPE_API_KEY
vim .env

# 4. 一键初始化（启动 Docker + 服务 + 上传文档）
make init

# 5. 一键启动
make start
```

</details>

<details>
<summary><strong>🪟 Windows</strong></summary>

**手动启动 / Manual Start：**

```powershell
# 1. 克隆项目 / Clone
git clone <repository_url>
cd super_biz_agent_py

# 2. 创建虚拟环境并安装依赖 / Setup venv & install
# 方式 1: 使用 uv / via uv
pip install uv
uv venv
.venv\Scripts\activate
uv pip install -e .

# 方式 2: 使用 pip / via pip
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# 3. 编辑配置文件 / Configure
notepad .env

# 4. 启动 Docker Desktop（确保已安装并运行）

# 5. 启动 Milvus 向量数据库 / Start Milvus
docker compose -f vector-database.yml up -d

# 6. 等待 Milvus 启动完成 / Wait for Milvus
timeout /t 10

# 7. 启动 MCP 服务（各开一个新 PowerShell 窗口）
python mcp_servers/cls_server.py      # CLS 日志查询
python mcp_servers/monitor_server.py  # Monitor 监控

# 8. 启动 FastAPI 主服务（新开 PowerShell 窗口）
# 日志自动输出到 logs\app_YYYY-MM-DD.log
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 9. 上传文档到向量库 / Upload docs
timeout /t 5
python -c "import requests, os, time; [requests.post('http://localhost:9900/api/upload', files={'file': open(f'aiops-docs/{f}', 'rb')}) or time.sleep(1) for f in os.listdir('aiops-docs') if f.endswith('.md')]"
```

**一键启动脚本 / One-click Scripts：**

```powershell
.\start-windows.bat   # 启动所有服务 / Start all
.\stop-windows.bat    # 停止所有服务 / Stop all
```

</details>

### 访问服务 / Access

| 服务 | 地址 |
|------|------|
| **Web 界面** / Web UI | http://localhost:9900 |
| **API 文档** / API Docs | http://localhost:9900/docs |

---

## 📡 API 接口 / API Reference

| 功能 / Feature | 方法 | 路径 | 说明 / Description |
|---------------|------|------|-------------------|
| 普通对话 / Chat | `POST` | `/api/chat` | 一次性返回 / Single response |
| 流式对话 / Stream Chat | `POST` | `/api/chat_stream` | SSE 流式输出 / Server-Sent Events |
| AIOps 诊断 / Diagnostics | `POST` | `/api/aiops` | 自动故障诊断（流式）/ Streaming diagnostics |
| 文件上传 / Upload | `POST` | `/api/upload` | 上传并索引文档 / Upload & index |
| 健康检查 / Health | `GET` | `/api/health` | 服务状态检查 / Health check |

### 使用示例 / Examples

```bash
# 普通对话 / Chat
curl -X POST "http://localhost:9900/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"Id":"session-123","Question":"你好"}'

# 流式对话 / Stream Chat
curl -X POST "http://localhost:9900/api/chat_stream" \
  -H "Content-Type: application/json" \
  -d '{"Id":"session-123","Question":"你好"}' \
  --no-buffer

# AIOps 诊断 / AIOps Diagnostics
curl -X POST "http://localhost:9900/api/aiops" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-123"}' \
  --no-buffer
```

---

## 📁 项目结构 / Project Structure

<details>
<summary><strong>📂 点击展开目录树 / Click to expand</strong></summary>

```
super_biz_agent_py/
├── app/                                    # 应用核心 / Application Core
│   ├── __init__.py                         # 包初始化（自动加载日志配置）
│   ├── main.py                             # FastAPI 应用入口
│   ├── config.py                           # 配置管理（环境变量、MCP 服务器配置）
│   ├── api/                                # API 路由层 / API Routes
│   │   ├── __init__.py
│   │   ├── chat.py                         # 对话接口（RAG 聊天）
│   │   ├── aiops.py                        # AIOps 接口（故障诊断）
│   │   ├── file.py                         # 文件管理（文档上传）
│   │   └── health.py                       # 健康检查（服务状态）
│   ├── services/                           # 业务服务层 / Business Services
│   │   ├── __init__.py
│   │   ├── rag_agent_service.py            # RAG Agent（LangGraph 状态图）
│   │   ├── aiops_service.py                # AIOps 服务（计划-执行-重规划）
│   │   ├── vector_store_manager.py         # 向量存储管理器
│   │   ├── vector_embedding_service.py     # 向量 Embedding 服务
│   │   ├── vector_index_service.py         # 向量索引服务
│   │   ├── vector_search_service.py        # 向量检索服务
│   │   └── document_splitter_service.py    # 文档分割服务
│   ├── agent/                              # Agent 模块 / Agent Module
│   │   ├── __init__.py
│   │   ├── mcp_client.py                   # MCP 客户端（工具调用）
│   │   └── aiops/                          # AIOps 核心逻辑
│   │       ├── __init__.py
│   │       ├── planner.py                  # 计划制定器
│   │       ├── executor.py                 # 步骤执行器
│   │       ├── replanner.py                # 重规划器
│   │       ├── state.py                    # 状态定义
│   │       └── utils.py                    # 工具函数
│   ├── models/                             # 数据模型层 / Data Models
│   │   ├── __init__.py
│   │   ├── aiops.py                        # AIOps 模型
│   │   ├── document.py                     # 文档模型
│   │   ├── request.py                      # 请求模型
│   │   └── response.py                     # 响应模型
│   ├── tools/                              # Agent 工具集 / Tools
│   │   ├── __init__.py
│   │   ├── knowledge_tool.py               # 知识库查询工具
│   │   └── time_tool.py                    # 时间工具
│   ├── core/                               # 核心组件 / Core Components
│   │   ├── __init__.py
│   │   ├── llm_factory.py                  # LLM 工厂（模型管理）
│   │   └── milvus_client.py                # Milvus 客户端
│   └── utils/                              # 工具类 / Utilities
│       ├── __init__.py
│       └── logger.py                       # 日志配置（Loguru）
├── static/                                 # Web 前端 / Web Frontend
│   ├── index.html                          # 主页面
│   ├── app.js                              # 前端逻辑
│   └── styles.css                          # 样式表
├── mcp_servers/                            # MCP 服务器 / MCP Servers
│   ├── cls_server.py                       # CLS 日志查询服务
│   ├── monitor_server.py                   # 监控数据服务
│   └── README.md                           # MCP 服务说明
├── aiops-docs/                             # 运维知识库 / Ops Knowledge Base
├── logs/                                   # 日志目录 / Logs (Loguru)
│   └── app_YYYY-MM-DD.log                  # 按天轮转的日志文件
├── uploads/                                # 上传文件临时目录 / Upload Temp
├── volumes/                                # Milvus 数据持久化目录
├── .env                                    # 环境变量配置（需手动创建）
├── Makefile                                # 项目管理命令（Linux/macOS）
├── start-windows.bat                       # Windows 启动脚本
├── stop-windows.bat                        # Windows 停止脚本
├── vector-database.yml                     # Milvus Docker Compose 配置
├── pyproject.toml                          # 项目配置（依赖、元数据）
├── uv.lock                                 # uv 依赖锁定文件
├── pyrightconfig.json                      # Pyright 类型检查配置
└── README.md                               # 项目说明
```

</details>

---

## ⚙️ 配置说明 / Configuration

通过 `.env` 文件配置 / Configure via `.env`:

```bash
# 阿里云 LLM DashScope 配置（必填）/ DashScope Config (Required)
# 秘钥管理： https://bailian.console.aliyun.com/
DASHSCOPE_API_KEY=your-api-key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-max

# Milvus 配置 / Milvus Config
MILVUS_HOST=localhost
MILVUS_PORT=19530

# RAG 配置 / RAG Config
RAG_TOP_K=3
CHUNK_MAX_SIZE=800
CHUNK_OVERLAP=100
```

| 变量 | 必填 | 默认值 | 说明 |
|------|:--:|--------|------|
| `DASHSCOPE_API_KEY` | ✅ | — | 阿里云 DashScope API 密钥 / API Key |
| `DASHSCOPE_API_BASE` | — | 新加坡站点 | API 端点地址 / Endpoint URL |
| `DASHSCOPE_MODEL` | — | `qwen-max` | 使用的模型 / Model name |
| `MILVUS_HOST` | — | `localhost` | Milvus 主机地址 |
| `MILVUS_PORT` | — | `19530` | Milvus 端口号 |
| `RAG_TOP_K` | — | `3` | 检索返回条数 / Top-K results |
| `CHUNK_MAX_SIZE` | — | `800` | 文档分块最大长度 |
| `CHUNK_OVERLAP` | — | `100` | 分块重叠长度 |

---

## 🎯 AIOps 智能运维 / AIOps Intelligent Operations

基于 **Plan-Execute-Replan** 模式实现自动故障诊断。

> *Automated fault diagnosis powered by the Plan-Execute-Replan agent pattern.*

### 诊断流程 / Diagnostic Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Planner │───▶│ Executor │───▶│Replanner │───▶│  Report  │
│  制定计划 │    │  执行步骤 │    │  评估结果 │    │  诊断报告 │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
      │                              │
      └──────── 调整/重新规划 ◀───────┘
```

> 1. **Planner** 制定计划 → 生成 4-6 个诊断步骤
> 2. **Executor** 执行步骤 → 调用 MCP 工具（日志查询、监控数据）
> 3. **Replanner** 评估结果 → 决定继续/调整/生成报告
> 4. **输出诊断报告** → 根因分析 + 运维建议

### 核心特性 / Highlights

- ✅ 自动制定诊断计划 / Auto plan generation
- ✅ 智能工具调用 / Intelligent tool orchestration
- ✅ 动态调整步骤 / Dynamic re-planning
- ✅ 流式输出诊断过程 / Streaming progress
- ✅ 生成结构化报告 / Structured reports

### 快速测试 / Quick Test

```bash
# 访问 Web 界面，点击"智能运维与诊断工具"
# 或使用 API / Or via API:
curl -X POST "http://localhost:9900/api/aiops" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test"}' \
  --no-buffer
```

---

## 📝 开发指南 / Development Guide

### 常用命令 / Common Commands

```bash
# 项目管理 / Project
make init              # 一键初始化（Docker + 服务 + 文档）
make start             # 启动所有服务 / Start all services
make stop              # 停止所有服务 / Stop all services
make restart           # 重启所有服务 / Restart all services

# 依赖管理 / Dependencies
make install-dev       # 安装开发依赖 / Install dev deps
make sync              # 同步依赖 / Sync dependencies

# Docker 管理 / Docker
make up                # 启动 Docker 容器 / Start containers
make down              # 停止 Docker 容器 / Stop containers

# 代码质量 / Code Quality
make format            # 格式化代码 / Format code
make lint              # 代码检查 / Lint
```

---

## 🐛 常见问题 / FAQ

<details>
<summary><strong>🪟 Windows：<code>make</code> 命令不可用</strong></summary>

Windows 不支持 `make` 命令，请使用提供的批处理脚本：

```powershell
.\start-windows.bat   # 启动服务
.\stop-windows.bat    # 停止服务
```

</details>

<details>
<summary><strong>🪟 Windows：PowerShell 执行策略限制</strong></summary>

如果遇到 "无法加载文件，因为在此系统上禁止运行脚本" 错误：

```powershell
# 临时允许脚本执行（管理员权限）
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# 或者使用 CMD 而不是 PowerShell
cmd
.\start-windows.bat
```

</details>

<details>
<summary><strong>🪟 Windows：端口被占用</strong></summary>

```powershell
# 查看占用端口的进程
netstat -ano | findstr :9900

# 结束进程（替换 PID 为实际进程 ID）
taskkill /F /PID <PID>
```

</details>

<details>
<summary><strong>🔑 API Key 错误 / API Key Error</strong></summary>

```bash
# 检查环境变量 / Check env
cat .env | grep DASHSCOPE_API_KEY      # Linux/macOS
type .env | findstr DASHSCOPE_API_KEY   # Windows
```

</details>

<details>
<summary><strong>🗄️ Milvus 连接失败 / Milvus Connection Failure</strong></summary>

```bash
# 确保本机有 Docker 服务并且已经启动
# Ensure Docker is installed and running

# 检查 Milvus 状态 / Check status
docker ps | grep milvus

# 重启 Milvus / Restart Milvus
docker compose -f vector-database.yml restart
# 或重启单个服务
docker compose -f vector-database.yml restart standalone
```

</details>

<details>
<summary><strong>🔍 服务无法启动 / Service Won't Start</strong></summary>

**Linux/macOS：**
```bash
# 查看服务日志 / View logs
tail -f logs/app_$(date +%Y-%m-%d).log   # FastAPI 主服务
tail -f mcp_cls.log                       # CLS MCP 服务
tail -f mcp_monitor.log                   # Monitor MCP 服务

# 检查端口占用 / Check port usage
lsof -i :9900   # FastAPI
lsof -i :8003   # CLS MCP
lsof -i :8004   # Monitor MCP
```

**Windows：**
```powershell
# 查看服务日志 / View logs
$today = Get-Date -Format "yyyy-MM-dd"
type logs\app_$today.log

# 或查看最新的日志文件
Get-ChildItem logs\*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 50

# 检查端口占用 / Check port usage
netstat -ano | findstr :9900   # FastAPI
netstat -ano | findstr :8003   # CLS MCP
netstat -ano | findstr :8004   # Monitor MCP
```

</details>

---

## 📚 参考资源 / References

| 资源 | 链接 |
|------|------|
| FastAPI | https://fastapi.tiangolo.com/ |
| LangChain | https://python.langchain.com/ |
| LangGraph Plan-Execute | https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/ |
| 阿里云 DashScope | https://dashscope.aliyun.com/ |
| MCP 协议 | https://modelcontextprotocol.io/ |

---

## 📄 许可证 / License

<p align="center">
  <strong>Author：chief</strong><br>
  MIT License
</p>

<p align="center">
  <sub>Made with ❤️ for smarter operations</sub>
</p>
