"""日志查询 CLS MCP Server

本地实现的日志查询服务 MCP Server，提供：
- 实时读取本机日志文件
- 按级别/关键词过滤
- 按服务名称自动发现日志 topic

日志来源：项目 logs/ 目录下的 Loguru 日志文件。
"""

import logging
import functools
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CLS_MCP_Server")

# 默认日志目录（相对于该 mcp_server 文件所在目录）
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"

mcp = FastMCP("CLS")


def log_tool_call(func):
    """装饰器：记录工具调用的日志"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__
        logger.info("=" * 80)
        logger.info(f"调用方法: {method_name}")
        if kwargs:
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")
        try:
            result = func(*args, **kwargs)
            logger.info(f"返回状态: SUCCESS")
            if isinstance(result, dict):
                summary = {
                    k: v if not isinstance(v, (list, dict))
                    else f"<{type(v).__name__} with {len(v)} items>"
                    for k, v in list(result.items())[:5]
                }
                logger.info(f"返回结果摘要: {json.dumps(summary, ensure_ascii=False)}")
            logger.info("=" * 80)
            return result
        except Exception as e:
            logger.error(f"返回状态: ERROR")
            logger.error(f"错误信息: {str(e)}")
            logger.error("=" * 80)
            raise
    return wrapper


# ============================================================
# 日志文件发现
# ============================================================

def _discover_log_files(log_dir: Optional[str] = None) -> List[Path]:
    """扫描日志目录，发现所有可用的日志文件"""
    base = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    if not base.exists():
        return []
    return sorted(
        [p for p in base.iterdir() if p.is_file() and p.suffix in ('.log', '.txt')],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )


def _log_file_to_topic(log_path: Path) -> Dict[str, Any]:
    """将日志文件映射为 CLS topic 对象"""
    stat = log_path.stat()
    return {
        "topic_id": log_path.stem,
        "topic_name": log_path.name,
        "service_name": _infer_service_name(log_path.name),
        "region_code": "local",
        "create_time": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        "log_count": _count_lines(log_path),
        "file_size_kb": round(stat.st_size / 1024, 1),
        "description": f"本地日志文件: {log_path}",
    }


def _infer_service_name(filename: str) -> str:
    """从日志文件名推断服务名"""
    # app_2026-06-20.log -> 主应用服务
    # mcp_cls.log -> CLS MCP 服务
    # mcp_monitor.log -> Monitor MCP 服务
    name = filename.rsplit('.', 1)[0]
    if name.startswith("app_"):
        return "super-biz-agent"
    if name.startswith("mcp_"):
        return name.replace("mcp_", "") + "-mcp-service"
    return name + "-service"


def _count_lines(filepath: Path) -> int:
    """快速估算文件行数"""
    try:
        with open(filepath, 'rb') as f:
            return sum(1 for _ in f)
    except (OSError, PermissionError):
        return 0


def _parse_loguru_line(line: str) -> Optional[Dict[str, Any]]:
    """解析 Loguru 格式的日志行

    Loguru 默认格式:
    2026-06-20 18:19:16 | INFO | module.func:line | message

    Returns:
        解析后的日志条目，或 None（如果无法解析）
    """
    # Loguru 格式: time | LEVEL | location | message
    pattern = r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(\w+)\s*\|\s*([^|]+)\s*\|\s*(.+)$'
    match = re.match(pattern, line.strip())
    if match:
        time_str, level, location, message = match.groups()
        return {
            "timestamp": time_str.strip(),
            "level": level.strip(),
            "location": location.strip(),
            "message": message.strip(),
        }

    # 尝试宽松匹配（有些日志行格式不同）
    loose = r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
    if re.match(loose, line.strip()):
        return {
            "timestamp": line[:19],
            "level": "UNKNOWN",
            "location": "",
            "message": line[19:].strip().lstrip('|').strip(),
        }

    return None


# ============================================================
# 日志查询工具
# ============================================================

@mcp.tool()
@log_tool_call
def get_current_timestamp() -> int:
    """获取当前时间戳（以毫秒为单位）。

    Returns:
        int: 当前时间戳（毫秒）
    """
    return int(datetime.now().timestamp() * 1000)


@mcp.tool()
@log_tool_call
def get_region_code_by_name(region_name: str) -> Dict[str, Any]:
    """根据地区名称搜索对应的地区参数（本地版）。

    Args:
        region_name: 地区名称

    Returns:
        Dict: 地区信息，本地服务统一返回 "local"
    """
    # 本地版：所有日志都在本机，返回固定信息
    known = {
        "local": {"region_code": "local", "region_name": "本地", "available": True},
        "北京": {"region_code": "local", "region_name": "本地（北京）", "available": True},
        "上海": {"region_code": "local", "region_name": "本地（上海）", "available": True},
    }

    result = known.get(region_name)
    if result:
        return result
    return {
        "region_code": "local",
        "region_name": region_name,
        "available": True,
        "note": "本地 CLS Server — 所有日志均为本地文件",
    }


@mcp.tool()
@log_tool_call
def get_topic_info_by_name(
    topic_name: str,
    region_code: Optional[str] = None,
) -> Dict[str, Any]:
    """根据主题名称搜索相关的日志主题。

    从 logs/ 目录自动发现匹配的日志文件。

    Args:
        topic_name: 主题名称（日志文件名，如 "app_2026-06-20.log"）
        region_code: 地区代码（可选，本地版忽略）

    Returns:
        Dict: 主题信息
    """
    for log_path in _discover_log_files():
        topic = _log_file_to_topic(log_path)
        if topic["topic_name"] == topic_name or topic["topic_id"] == topic_name:
            return topic

    return {
        "topic_id": None,
        "topic_name": topic_name,
        "error": f"未找到日志文件: {topic_name}",
    }


@mcp.tool()
@log_tool_call
def search_topic_by_service_name(
    service_name: str,
    region_code: Optional[str] = None,
    fuzzy: bool = True,
) -> Dict[str, Any]:
    """根据服务名称搜索相关的日志主题。

    从 logs/ 目录扫描所有日志文件，按服务名匹配。

    Args:
        service_name: 服务名称（如 "super-biz-agent", "cls-mcp-service"）
        region_code: 地区代码（可选）
        fuzzy: 是否启用模糊搜索

    Returns:
        Dict: 匹配的 topic 列表
    """
    all_topics = [_log_file_to_topic(p) for p in _discover_log_files()]
    matched = []

    for topic in all_topics:
        if fuzzy:
            if (service_name.lower() in topic["service_name"].lower() or
                    topic["service_name"].lower() in service_name.lower()):
                matched.append(topic)
        else:
            if topic["service_name"].lower() == service_name.lower():
                matched.append(topic)

    return {
        "total": len(matched),
        "topics": matched,
        "query": {
            "service_name": service_name,
            "region_code": region_code,
            "fuzzy": fuzzy,
        },
        "message": (
            f"找到 {len(matched)} 个匹配的日志主题"
            if matched
            else f"未找到服务 '{service_name}' 的日志主题"
        ),
    }


@mcp.tool()
@log_tool_call
def search_log(
    topic_id: str,
    start_time: int,
    end_time: int,
    query: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """根据查询参数搜索日志。

    从本地日志文件中读取真实日志内容，支持按级别和关键词过滤。

    Args:
        topic_id: 日志文件名（不含扩展名），如 "app_2026-06-20"
        start_time: 开始时间戳，毫秒
        end_time: 结束时间戳，毫秒
        query: 查询过滤条件（可选）
            - "level:ERROR" — 只返回 ERROR 级别日志
            - "level:WARNING" — 只返回 WARNING 级别日志
            - "message:关键词" — 按消息内容过滤
            - "level:ERROR message:超时" — 组合过滤
        limit: 返回结果数量限制

    Returns:
        Dict: 搜索结果，包含 logs 列表
    """
    # 查找匹配的日志文件
    log_files = _discover_log_files()
    target_path = None
    for p in log_files:
        if p.stem == topic_id or p.name == topic_id:
            target_path = p
            break

    if target_path is None:
        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "end_time": end_time,
            "query": query,
            "limit": limit,
            "total": 0,
            "logs": [],
            "error": f"日志文件不存在: {topic_id}",
            "available_topics": [p.stem for p in log_files],
        }

    # 解析过滤条件
    level_filter = None
    message_filter = None
    if query:
        for part in query.split():
            if part.startswith("level:"):
                level_filter = part.split(":", 1)[1].upper()
            elif part.startswith("message:"):
                message_filter = part.split(":", 1)[1]

    # 解析时间范围
    start_dt = datetime.fromtimestamp(start_time / 1000)
    end_dt = datetime.fromtimestamp(end_time / 1000)

    # 读取日志文件并过滤
    logs = []
    try:
        with open(target_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if len(logs) >= limit:
                    break

                parsed = _parse_loguru_line(line)
                if parsed is None:
                    continue

                # 时间过滤
                try:
                    log_time = datetime.strptime(
                        parsed["timestamp"], "%Y-%m-%d %H:%M:%S"
                    )
                    if log_time < start_dt or log_time > end_dt:
                        continue
                except ValueError:
                    pass  # 如果无法解析时间，保留该日志

                # 级别过滤
                if level_filter and parsed["level"].upper() != level_filter:
                    continue

                # 消息关键词过滤
                if message_filter and message_filter not in parsed["message"]:
                    continue

                logs.append(parsed)

    except (OSError, PermissionError) as e:
        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "end_time": end_time,
            "query": query,
            "limit": limit,
            "total": 0,
            "logs": [],
            "error": f"读取日志文件失败: {e}",
        }

    return {
        "topic_id": topic_id,
        "start_time": start_time,
        "end_time": end_time,
        "query": query,
        "limit": limit,
        "total": len(logs),
        "logs": logs,
        "source_file": str(target_path),
        "took_ms": 50,
        "message": f"从 {target_path.name} 成功查询 {len(logs)} 条日志",
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8003, path="/mcp")
