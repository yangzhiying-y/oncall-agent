"""文件上传接口模块

支持文件上传并自动创建向量索引，大文件使用异步任务队列处理。
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.task_queue import TaskStatus, task_queue
from app.services.vector_index_service import vector_index_service
from app.utils.file_utils import get_file_extension, sanitize_filename

router = APIRouter()

# 文件上传后存储的路径
UPLOAD_DIR = Path("./uploads")
# 支持的文件类型
ALLOWED_EXTENSIONS = ["txt", "md", "markdown", "pdf", "docx", "doc"]
# 单个文件支持最大大小
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
# 超过此大小的文件使用异步索引（不阻塞 HTTP 响应）
ASYNC_INDEX_THRESHOLD = 1 * 1024 * 1024  # 1MB


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    上传文件并自动创建向量索引

    小文件（<1MB）同步索引，大文件异步索引。
    异步任务可通过 GET /api/task/{task_id} 查询进度。

    Args:
        file: 上传的文件

    Returns:
        JSONResponse: 上传结果，包含 task_id（如果异步索引）
    """
    try:
        # 1. 验证文件
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        # 2. 规范化文件名
        safe_filename = sanitize_filename(file.filename)

        # 3. 验证文件扩展名
        file_extension = get_file_extension(safe_filename)
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        # 4. 创建上传目录
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # 5. 读取并验证文件
        file_path = UPLOAD_DIR / safe_filename
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="不能上传空文件")
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）",
            )

        file_path.write_bytes(content)
        logger.info(f"文件上传成功: {file_path} ({len(content)} bytes)")

        # 6. 创建向量索引（大文件异步处理）
        use_async = len(content) > ASYNC_INDEX_THRESHOLD
        task_id = None

        if use_async:
            # 异步索引：不阻塞 HTTP 响应
            async def _index_async():
                logger.info(f"异步索引开始: {file_path}")
                vector_index_service.index_single_file(str(file_path))
                logger.info(f"异步索引完成: {file_path}")

            task_id = await task_queue.submit(
                name=f"index:{safe_filename}",
                coro=_index_async(),
            )
            logger.info(f"文件 {safe_filename} 已提交异步索引任务: {task_id}")
            indexed = None  # 未知，需要查询任务状态
        else:
            # 小文件同步索引
            try:
                vector_index_service.index_single_file(str(file_path))
                indexed = True
                logger.info(f"同步索引完成: {file_path}")
            except Exception as e:
                indexed = False
                logger.error(f"同步索引失败: {file_path}, 错误: {e}")

        # 7. 返回响应
        response_data = {
            "filename": safe_filename,
            "size": len(content),
            "indexed": indexed,
        }
        if task_id:
            response_data["task_id"] = task_id
            response_data["index_mode"] = "async"

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": (
                    "indexed" if indexed is True
                    else "async_indexing" if task_id
                    else "saved_but_not_indexed"
                ),
                "data": response_data,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}") from e


@router.post("/index_directory")
async def index_directory(
    directory_path: str = None,
    background_tasks: BackgroundTasks = None,
):
    """
    索引指定目录下的所有文件（异步处理）

    Args:
        directory_path: 目录路径（可选，默认使用 uploads 目录）

    Returns:
        JSONResponse: 包含 task_id 的响应
    """
    try:
        target_dir = directory_path or str(UPLOAD_DIR)
        logger.info(f"开始索引目录（异步）: {target_dir}")

        async def _index_dir_async():
            vector_index_service.index_directory(target_dir)

        task_id = await task_queue.submit(
            name=f"index_dir:{target_dir}",
            coro=_index_dir_async(),
        )

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "async_indexing",
                "data": {
                    "directory": target_dir,
                    "task_id": task_id,
                },
            },
        )

    except Exception as e:
        logger.error(f"索引目录失败: {e}")
        raise HTTPException(status_code=500, detail=f"索引目录失败: {e}") from e


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """查询异步任务状态

    Args:
        task_id: 任务 ID（由 upload/index_directory 返回）

    Returns:
        任务状态信息
    """
    task = task_queue.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "error": task.error,
            },
        },
    )


@router.get("/tasks")
async def list_tasks(limit: int = Query(default=20, le=100)):
    """列出最近的任务

    Args:
        limit: 返回数量（默认 20，最大 100）
    """
    tasks = task_queue.list_tasks(limit)
    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": {
                "total": len(tasks),
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "name": t.name,
                        "status": t.status.value,
                        "created_at": t.created_at,
                        "error": t.error,
                    }
                    for t in tasks
                ],
            },
        },
    )
