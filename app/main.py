"""FastAPI 应用入口

主应用程序，配置路由、中间件、静态文件等
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api import aiops, chat, file, health
from app.config import config
from app.core.checkpoint_store import checkpoint_store
from app.core.milvus_client import milvus_manager
from app.core.task_queue import task_queue
from app.core.rate_limiter import rate_limit_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("=" * 60)
    logger.info(f"🚀 {config.app_name} v{config.app_version} 启动中...")
    logger.info(f"📝 环境: {'开发' if config.debug else '生产'}")
    logger.info(f"🌐 监听地址: http://{config.host}:{config.port}")
    logger.info(f"📚 API 文档: http://{config.host}:{config.port}/docs")

    # 显示 CLS MCP 模式
    if config.cls_use_tencent_cloud:
        logger.info("☁️  CLS MCP: 腾讯云官方 cls-mcp-server (npx + stdio)")
    else:
        logger.info("💻 CLS MCP: 本地日志文件模式 (localhost:8003)")

    # 连接 Milvus
    logger.info("🔌 正在连接 Milvus...")
    milvus_manager.connect()
    logger.info("✅ Milvus 连接成功")

    # 连接 SQLite 检查点数据库（替代内存存储，重启不丢会话）
    logger.info("🔌 正在连接 SQLite 检查点数据库...")
    checkpoint_store.connect()
    logger.info(f"✅ SQLite 检查点数据库连接成功: {checkpoint_store.get_db_path()}")

    # 启动异步任务队列
    await task_queue.start()
    logger.info("✅ 异步任务队列已启动")

    logger.info("=" * 60)

    yield

    # 关闭时执行
    logger.info("🔌 正在停止异步任务队列...")
    await task_queue.stop()
    logger.info("🔌 正在关闭 SQLite 检查点数据库...")
    checkpoint_store.close()
    logger.info("🔌 正在关闭 Milvus 连接...")
    milvus_manager.close()
    logger.info(f"👋 {config.app_name} 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="基于 LangChain 的智能oncall运维系统",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 速率限制（最先执行，优先级最高）
app.middleware("http")(rate_limit_middleware)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Set browser protections for the dashboard and its API responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return response

# 注册路由
app.include_router(health.router, tags=["健康检查"])
app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(file.router, prefix="/api", tags=["文件管理"])
app.include_router(aiops.router, prefix="/api", tags=["AIOps智能运维"])

# 挂载静态文件
static_dir = "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """返回首页"""
    index_path = os.path.join(static_dir, "chat.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": f"Welcome to {config.app_name} API",
        "version": config.app_version,
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info"
    )
