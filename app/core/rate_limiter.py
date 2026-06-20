"""API 速率限制中间件

基于滑动窗口的轻量级速率限制器，无需外部依赖。
使用 IP + 端点作为限流键，支持可配置的窗口大小和请求上限。

配置通过环境变量:
    RATE_LIMIT_ENABLED=true
    RATE_LIMIT_MAX_REQUESTS=60    # 每个窗口最大请求数
    RATE_LIMIT_WINDOW_SECONDS=60  # 窗口大小（秒）
"""

import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request, status
from loguru import logger

from app.config import config


class SlidingWindowRateLimiter:
    """滑动窗口速率限制器"""

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
        cleanup_interval: int = 300,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.cleanup_interval = cleanup_interval
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def _cleanup_old_windows(self):
        now = time.monotonic()
        if now - self._last_cleanup < self.cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - self.window_seconds * 2
        expired = [k for k, v in self._windows.items() if v and v[-1] < cutoff]
        for k in expired:
            del self._windows[k]
        if expired:
            logger.debug(f"速率限制器清理了 {len(expired)} 个过期窗口")

    def is_allowed(self, key: str) -> tuple[bool, dict]:
        self._cleanup_old_windows()
        now = time.monotonic()
        window_start = now - self.window_seconds
        window = self._windows[key]
        while window and window[0] < window_start:
            window.pop(0)

        current_count = len(window)
        remaining = max(0, self.max_requests - current_count - 1)
        reset_time = int(window_start + self.window_seconds) if window else int(now + self.window_seconds)

        if current_count >= self.max_requests:
            retry_after = max(1, int(window[0] + self.window_seconds - now))
            return False, {
                "limit": self.max_requests,
                "remaining": 0,
                "reset": reset_time,
                "retry_after": retry_after,
            }

        window.append(now)
        return True, {
            "limit": self.max_requests,
            "remaining": remaining,
            "reset": reset_time,
        }


_rate_limiter: Optional[SlidingWindowRateLimiter] = None


def get_rate_limiter() -> Optional[SlidingWindowRateLimiter]:
    global _rate_limiter
    if not config.rate_limit_enabled:
        return None
    if _rate_limiter is None:
        _rate_limiter = SlidingWindowRateLimiter(
            max_requests=config.rate_limit_max_requests,
            window_seconds=config.rate_limit_window_seconds,
        )
    return _rate_limiter


RATE_LIMIT_EXEMPT_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/static",
    "/redoc",
)

STRICT_LIMIT_PREFIXES = (
    "/api/chat",
    "/api/chat_stream",
    "/api/aiops",
)


async def rate_limit_middleware(request: Request, call_next):
    limiter = get_rate_limiter()
    if limiter is None:
        return await call_next(request)

    path = request.url.path
    if path.startswith(RATE_LIMIT_EXEMPT_PREFIXES):
        return await call_next(request)

    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "")
        or request.client.host if request.client
        else "unknown"
    )

    if path.startswith(STRICT_LIMIT_PREFIXES):
        route_key = f"{client_ip}:chat"
    else:
        route_key = f"{client_ip}:api"

    allowed, info = limiter.is_allowed(route_key)
    response = await call_next(request)

    response.headers["X-RateLimit-Limit"] = str(info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(info["reset"])

    if not allowed:
        logger.warning(
            f"速率限制触发: {client_ip} -> {path} "
            f"(retry_after={info.get('retry_after', 'N/A')}s)"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "请求过于频繁，请稍后再试",
                "retry_after": info.get("retry_after", 60),
                "limit": info["limit"],
            },
            headers={
                "Retry-After": str(info.get("retry_after", 60)),
                "X-RateLimit-Limit": str(info["limit"]),
                "X-RateLimit-Remaining": "0",
            },
        )

    return response
