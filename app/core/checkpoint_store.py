"""SQLite 检查点持久化模块

替代 MemorySaver，将 LangGraph 会话状态持久化到 SQLite 文件，
确保服务重启后对话历史不丢失。

使用 langgraph-checkpoint-sqlite 提供的 SqliteSaver，
通过 context manager 管理连接生命周期。
"""

import os
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from loguru import logger

from app.config import config


class CheckpointStore:
    """SQLite 检查点存储管理器

    封装 SqliteSaver 的生命周期管理，在 FastAPI lifespan 中启动/关闭。

    Usage:
        store = CheckpointStore()
        store.connect()           # 在 lifespan startup 中调用
        saver = store.saver       # 传递给 LangGraph workflow.compile()
        store.close()             # 在 lifespan shutdown 中调用
    """

    def __init__(self):
        self._saver: Optional[SqliteSaver] = None
        self._ctx = None
        self._db_path: str = ""

    @property
    def saver(self) -> SqliteSaver:
        """获取 SqliteSaver 实例（必须在 connect() 之后调用）"""
        if self._saver is None:
            raise RuntimeError(
                "CheckpointStore 未连接，请先调用 connect()"
            )
        return self._saver

    @property
    def is_connected(self) -> bool:
        return self._saver is not None

    def connect(self, db_path: Optional[str] = None) -> SqliteSaver:
        """连接到 SQLite 数据库并初始化检查点表

        Args:
            db_path: SQLite 数据库文件路径，默认为 data/checkpoints.db

        Returns:
            SqliteSaver: 可用于 LangGraph workflow.compile() 的检查点保存器
        """
        if self._saver is not None:
            logger.warning("CheckpointStore 已连接，跳过重复连接")
            return self._saver

        if db_path is None:
            # 默认存储在项目 data 目录下
            data_dir = Path(__file__).parent.parent.parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "checkpoints.db")

        # 确保父目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db_path = db_path
        logger.info(f"正在连接 SQLite 检查点数据库: {db_path}")

        # SqliteSaver.from_conn_string 返回 context manager
        # 我们需要手动进入 context 并在服务生命周期内保持
        self._ctx = SqliteSaver.from_conn_string(db_path)
        self._saver = self._ctx.__enter__()

        logger.info("SQLite 检查点数据库连接成功")
        return self._saver

    def close(self):
        """关闭 SQLite 连接并释放资源"""
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
                logger.info("SQLite 检查点数据库连接已关闭")
            except Exception as e:
                logger.error(f"关闭 SQLite 检查点数据库时出错: {e}")
            finally:
                self._saver = None
                self._ctx = None

    def get_db_path(self) -> str:
        """获取当前数据库路径"""
        return self._db_path or "未连接"


# 全局单例
checkpoint_store = CheckpointStore()
