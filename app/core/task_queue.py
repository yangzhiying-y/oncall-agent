"""异步任务队列

基于 asyncio.Queue 的轻量级任务队列，
用于处理文件上传索引、批量导入等耗时操作，
避免阻塞 HTTP 请求响应。

设计原则：
- 文件索引任务按 FIFO 顺序执行
- 支持查询任务状态
- 失败任务自动记录错误信息
"""

import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from loguru import logger


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """异步任务"""
    task_id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None


class TaskQueue:
    """轻量级异步任务队列

    Usage:
        queue = TaskQueue(worker_count=2)
        await queue.start()

        task_id = await queue.submit(
            "index_file",
            some_async_func("file.pdf")
        )

        status = queue.get_task(task_id)
    """

    def __init__(self, worker_count: int = 1, max_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._worker_count = worker_count
        self._workers: list[asyncio.Task] = []
        self._tasks: dict[str, Task] = {}
        self._running = False

    async def start(self):
        """启动 worker 协程"""
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._worker_count)
        ]
        logger.info(f"任务队列已启动，worker 数量: {self._worker_count}")

    async def stop(self):
        """停止所有 worker"""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("任务队列已停止")

    async def submit(
        self,
        name: str,
        coro: Coroutine,
        task_id: Optional[str] = None,
    ) -> str:
        """提交一个异步任务

        Args:
            name: 任务名称（用于日志）
            coro: 要执行的协程
            task_id: 任务 ID（可选，不传则自动生成）

        Returns:
            任务 ID，可用于查询状态
        """
        import uuid

        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        task = Task(task_id=task_id, name=name)
        self._tasks[task_id] = task

        await self._queue.put((task_id, name, coro))
        logger.info(f"任务已入队: [{task_id}] {name}")

        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """查询任务状态"""
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[Task]:
        """列出最近的任务"""
        tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def _worker(self, worker_id: int):
        """Worker 协程：从队列中取出任务并执行"""
        logger.debug(f"Worker-{worker_id} 已启动")
        while self._running:
            try:
                task_id, name, coro = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            task = self._tasks.get(task_id)
            if task is None:
                self._queue.task_done()
                continue

            try:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now().isoformat()
                logger.info(f"Worker-{worker_id} 开始执行任务: [{task_id}] {name}")

                result = await coro

                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.now().isoformat()
                logger.info(f"Worker-{worker_id} 任务完成: [{task_id}] {name}")

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.now().isoformat()
                logger.error(
                    f"Worker-{worker_id} 任务失败: [{task_id}] {name}\n"
                    f"{traceback.format_exc()}"
                )
            finally:
                self._queue.task_done()


# 全局单例（1 个 worker，避免并发写入 Milvus 冲突）
task_queue = TaskQueue(worker_count=1, max_size=50)
