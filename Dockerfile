# Super Biz Agent 主应用 Dockerfile
# 多阶段构建：先安装依赖，再复制源码

FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖（Node.js 用于腾讯云 CLS MCP Server 的 npx 调用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && npm install -g npx \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（快速 Python 包管理器）
RUN pip install --no-cache-dir uv

# 先复制依赖文件，利用 Docker 缓存层
COPY pyproject.toml ./

# 创建虚拟环境并安装依赖
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache -e ".[dev]" && \
    uv pip install --no-cache psutil langgraph-checkpoint-sqlite

# 复制应用代码
COPY . .

# 创建数据和日志目录
RUN mkdir -p /app/data /app/logs /app/uploads

# 设置环境变量
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:9900/health || exit 1

EXPOSE 9900

# 启动命令
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9900"]
