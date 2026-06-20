"""智能运维监控 MCP Server

本地实现的监控服务 MCP Server，提供：
- 实时系统监控数据查询（CPU、内存、磁盘、进程）
- 基于 psutil 读取真实系统指标

用于支持运维 Agent 的故障排查场景。
"""

import logging
import functools
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

import psutil
from fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Monitor_MCP_Server")

mcp = FastMCP("Monitor")


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
# 辅助函数
# ============================================================

def parse_time_or_default(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """解析时间字符串或返回默认时间"""
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now() + timedelta(hours=default_offset_hours)


def _detect_service_process(service_name: str) -> Optional[psutil.Process]:
    """在运行中的进程中查找匹配服务名的进程

    支持匹配：
    - 命令行参数中包含服务名
    - 进程名中包含服务名
    """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            info = proc.info
            cmdline = ' '.join(info.get('cmdline') or [])
            if service_name.lower() in cmdline.lower():
                return proc
            if service_name.lower() in (info.get('name') or '').lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


# ============================================================
# 监控数据查询工具
# ============================================================

@mcp.tool()
@log_tool_call
def query_cpu_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的 CPU 使用率监控数据。

    读取本机真实 CPU 指标。如果找到匹配的服务进程，返回该进程的 CPU 占用；
    否则返回系统整体 CPU 使用率作为参考。

    Args:
        service_name: 服务名称（必填）
        start_time: 开始时间（可选，格式 "YYYY-MM-DD HH:MM:SS"）
        end_time: 结束时间（可选，格式 "YYYY-MM-DD HH:MM:SS"）
        interval: 数据聚合间隔（可选，"1m"/"5m"/"1h"，默认 "1m"）

    Returns:
        Dict: CPU 监控数据，包含 data_points、statistics、alert_info
    """
    # 尝试找到对应服务的进程
    proc = _detect_service_process(service_name)

    # 采集当前 CPU 数据（多次采样取平均以获得更准确的值）
    cpu_samples = []
    for _ in range(3):
        if proc:
            try:
                cpu_samples.append(proc.cpu_percent(interval=0.1))
            except psutil.NoSuchProcess:
                proc = None
                cpu_samples.append(psutil.cpu_percent(interval=0.1))
        else:
            cpu_samples.append(psutil.cpu_percent(interval=0.1))

    current_cpu = round(sum(cpu_samples) / len(cpu_samples), 1)
    cpu_count = psutil.cpu_count()
    cpu_per_core = round(current_cpu / cpu_count, 1) if cpu_count else current_cpu

    # 构建数据点
    data_points = [
        {
            "timestamp": datetime.now().strftime("%H:%M"),
            "value": current_cpu,
            "per_core": cpu_per_core,
            "cpu_count": cpu_count,
        }
    ]

    return {
        "service_name": service_name,
        "metric_name": "cpu_usage_percent",
        "interval": interval,
        "source": "psutil (real-time)",
        "process_found": proc is not None,
        "data_points": data_points,
        "statistics": {
            "avg": current_cpu,
            "max": current_cpu,
            "min": current_cpu,
            "cpu_count": cpu_count,
            "per_core_avg": cpu_per_core,
        },
        "alert_info": {
            "triggered": current_cpu > 80.0,
            "threshold": 80.0,
            "message": (
                f"CPU 使用率 {current_cpu}% 超过 80% 阈值"
                if current_cpu > 80.0
                else f"CPU 使用率 {current_cpu}%，正常"
            ),
        },
    }


@mcp.tool()
@log_tool_call
def query_memory_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的内存使用监控数据。

    读取本机真实内存指标。如果找到匹配的服务进程，返回该进程的内存占用；
    否则返回系统整体内存使用率作为参考。

    Args:
        service_name: 服务名称（必填）
        start_time: 开始时间（可选）
        end_time: 结束时间（可选）
        interval: 数据聚合间隔（可选，默认 "1m"）

    Returns:
        Dict: 内存监控数据
    """
    # 系统整体内存
    mem = psutil.virtual_memory()
    total_gb = round(mem.total / (1024 ** 3), 1)
    available_gb = round(mem.available / (1024 ** 3), 1)

    # 尝试找到对应服务的进程
    proc = _detect_service_process(service_name)
    if proc:
        try:
            proc_mem = proc.memory_info()
            proc_rss_gb = round(proc_mem.rss / (1024 ** 3), 2)
            proc_percent = round(proc.memory_percent(), 1)
            used_gb = proc_rss_gb
            memory_value = proc_percent
        except psutil.NoSuchProcess:
            proc = None
            used_gb = round(mem.used / (1024 ** 3), 1)
            memory_value = round(mem.percent, 1)
    else:
        used_gb = round(mem.used / (1024 ** 3), 1)
        memory_value = round(mem.percent, 1)

    data_points = [
        {
            "timestamp": datetime.now().strftime("%H:%M"),
            "value": memory_value,
            "used_gb": used_gb,
            "total_gb": total_gb,
            "available_gb": available_gb,
        }
    ]

    return {
        "service_name": service_name,
        "metric_name": "memory_usage_percent",
        "interval": interval,
        "source": "psutil (real-time)",
        "process_found": proc is not None,
        "data_points": data_points,
        "statistics": {
            "avg": memory_value,
            "max": memory_value,
            "min": memory_value,
            "total_gb": total_gb,
            "used_gb": used_gb,
        },
        "alert_info": {
            "triggered": memory_value > 70.0,
            "threshold": 70.0,
            "message": (
                f"内存使用率 {memory_value}% 超过 70% 阈值"
                if memory_value > 70.0
                else f"内存使用率 {memory_value}%，正常"
            ),
        },
    }


@mcp.tool()
@log_tool_call
def query_disk_metrics(
    service_name: str = "system",
    mount_point: Optional[str] = None,
) -> Dict[str, Any]:
    """查询磁盘使用情况。

    读取本机真实磁盘指标，默认返回所有分区的使用情况。

    Args:
        service_name: 服务名称（可选，用于日志标记）
        mount_point: 指定挂载点（可选），不传则返回所有分区

    Returns:
        Dict: 磁盘使用数据
    """
    partitions = psutil.disk_partitions()
    disk_data = []

    for part in partitions:
        if mount_point and part.mountpoint != mount_point:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_data.append({
                "device": part.device,
                "mount_point": part.mountpoint,
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
                "percent": usage.percent,
                "fstype": part.fstype,
            })
        except PermissionError:
            continue

    if not disk_data:
        return {
            "service_name": service_name,
            "metric_name": "disk_usage_percent",
            "error": "无法读取磁盘信息",
        }

    # 找出使用率最高的分区
    max_usage = max(disk_data, key=lambda d: d["percent"])

    return {
        "service_name": service_name,
        "metric_name": "disk_usage_percent",
        "source": "psutil (real-time)",
        "partitions": disk_data,
        "statistics": {
            "worst_device": max_usage["device"],
            "worst_mount": max_usage["mount_point"],
            "worst_percent": max_usage["percent"],
        },
        "alert_info": {
            "triggered": max_usage["percent"] > 85.0,
            "threshold": 85.0,
            "message": (
                f"磁盘 {max_usage['mount_point']} 使用率 {max_usage['percent']}% 超过 85% 阈值"
                if max_usage["percent"] > 85.0
                else "磁盘使用率正常"
            ),
        },
    }


@mcp.tool()
@log_tool_call
def query_process_info(
    service_name: Optional[str] = None,
    pid: Optional[int] = None,
) -> Dict[str, Any]:
    """查询运行中进程的详细信息。

    可通过服务名称（模糊匹配）或 PID 查找进程。

    Args:
        service_name: 服务名称（可选），模糊匹配命令行
        pid: 进程 PID（可选）

    Returns:
        Dict: 进程信息，包含 PID、CPU、内存、运行时间等
    """
    processes = []

    if pid:
        try:
            proc = psutil.Process(pid)
            processes = [proc]
        except psutil.NoSuchProcess:
            return {"error": f"进程 PID={pid} 不存在"}

    elif service_name:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                info = proc.info
                cmdline = ' '.join(info.get('cmdline') or [])
                proc_name = info.get('name') or ''
                if (service_name.lower() in cmdline.lower() or
                        service_name.lower() in proc_name.lower()):
                    processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    else:
        # 返回占用最高的几个进程
        processes = sorted(
            [p for p in psutil.process_iter(['pid', 'name'])],
            key=lambda p: (p.info.get('pid') or 0),
        )[-10:]

    if not processes:
        return {
            "query": {"service_name": service_name, "pid": pid},
            "total": 0,
            "message": f"未找到匹配的进程",
        }

    result = []
    for proc in processes[:20]:  # 最多返回 20 个
        try:
            info = proc.as_dict(attrs=[
                'pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent',
                'create_time', 'status', 'num_threads',
            ])
            mem_info = proc.memory_info()
            info['memory_rss_mb'] = round(mem_info.rss / (1024 ** 2), 1)
            info['memory_vms_mb'] = round(mem_info.vms / (1024 ** 2), 1)

            create_time = datetime.fromtimestamp(info['create_time'])
            info['create_time_str'] = create_time.strftime("%Y-%m-%d %H:%M:%S")
            info['running_seconds'] = round(
                (datetime.now() - create_time).total_seconds()
            )

            result.append(info)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            continue

    return {
        "query": {"service_name": service_name, "pid": pid},
        "total": len(result),
        "source": "psutil (real-time)",
        "processes": result,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8004, path="/mcp")
