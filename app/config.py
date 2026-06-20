"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "知识库智能运维Agent 系统"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900
    # Turn this off in constrained test environments that cannot create a log queue.
    log_enqueue: bool = True
    # Comma-separated browser origins allowed to call the API from another site.
    # Same-origin requests do not need CORS at all.
    cors_allowed_origins: str = "http://localhost:9900,http://127.0.0.1:9900"

    # 速率限制配置
    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 60      # 每个窗口最大请求数
    rate_limit_window_seconds: int = 60    # 窗口大小（秒）

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒

    # RAG 配置
    rag_top_k: int = 3
    rag_model: str = "qwen-max"  # 使用快速响应模型，不带扩展思考

    # 重排配置（阿里云百炼 qwen3-rerank 模型）
    # rerank_retrieval_k: 粗筛阶段从向量库检索的候选文档数（应大于 rerank_top_n）
    # rerank_top_n: 精排后返回的最相关文档数
    rerank_model: str = "qwen3-rerank"
    rerank_retrieval_k: int = 10
    rerank_top_n: int = 3

    # 上下文自动压缩配置
    # 当对话 token 数超过 context_window_tokens * compression_threshold 时，
    # 自动用 LLM 将早期对话压缩为摘要，保留最近 compression_keep_recent 条消息原文
    context_compression_enabled: bool = True
    context_window_tokens: int = 32768       # qwen-max 上下文窗口大小
    compression_threshold: float = 0.7        # 触发压缩的阈值（70%）
    compression_keep_recent: int = 6          # 压缩后保留最近 N 条消息原文
    compression_summary_max_tokens: int = 800 # 压缩摘要的最大 token 数

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # 腾讯云 CLS MCP 配置
    # 当配置了 TENCENTCLOUD_SECRET_ID 时，自动使用腾讯云官方 CLS MCP Server；
    # 否则回退到本地 cls_server.py 读取本地日志文件。
    tencentcloud_secret_id: str = ""
    tencentcloud_secret_key: str = ""
    tencentcloud_region: str = "ap-guangzhou"

    # MCP 服务配置（transport: stdio | sse | streamable-http）
    # CLS: 优先使用腾讯云 CLS MCP (stdio via npx)，否则用本地日志读取
    # Monitor: 使用本地 FastMCP (streamable-http)，读取真实系统指标
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # Prometheus
    prometheus_base_url: str = "http://127.0.0.1:9090"
    prometheus_request_timeout: float = 10.0

    @property
    def cls_use_tencent_cloud(self) -> bool:
        """是否使用腾讯云 CLS MCP Server（需要配置 SecretId/SecretKey）"""
        return bool(self.tencentcloud_secret_id and self.tencentcloud_secret_key)

    @property
    def cors_origins(self) -> list[str]:
        """Return clean CORS origins from the simple .env-friendly setting."""
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        """获取完整的 MCP 服务器配置

        CLS MCP Server:
        - 若配置了腾讯云密钥 → 使用官方 cls-mcp-server (npx + stdio)
        - 否则 → 使用本地 cls_server.py (streamable-http)

        Monitor MCP Server:
        - 始终使用本地 monitor_server.py (基于 psutil 读取真实系统指标)
        """
        servers: dict[str, dict[str, Any]] = {
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }

        if self.cls_use_tencent_cloud:
            # 腾讯云官方 CLS MCP Server (stdio + npx)
            servers["cls"] = {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "cls-mcp-server@latest"],
                "env": {
                    "TENCENTCLOUD_SECRET_ID": self.tencentcloud_secret_id,
                    "TENCENTCLOUD_SECRET_KEY": self.tencentcloud_secret_key,
                    "TENCENTCLOUD_REGION": self.tencentcloud_region,
                    "TRANSPORT": "stdio",
                    "TZ": "Asia/Shanghai",
                },
            }
        else:
            # 本地日志读取（无需外部依赖）
            servers["cls"] = {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            }

        return servers


# 全局配置实例
config = Settings()
