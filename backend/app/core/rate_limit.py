"""Sliding-window rate limiter implemented as a FastAPI dependency.

Uses the request-scoped Redis client (already injected by get_redis) so it
works transparently in tests with fakeredis — no global state, no monkey-patching.

Usage
-----
    _login_limit = make_rate_limiter(max_calls=5, window_seconds=60)

    @router.post("/login")
    async def login(
        ...,
        _rl: None = Depends(_login_limit),
    ) -> ...:
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import Depends, HTTPException, Request, status

from app.core.redis import get_redis
from app.schemas.common import ErrorResponse

logger = structlog.get_logger(__name__)


def make_rate_limiter(max_calls: int, window_seconds: int) -> Callable:
    """Return a FastAPI dependency that enforces *max_calls* per *window_seconds*
    using a Redis sorted-set sliding window, keyed by ``path:client_ip``."""

    async def _rate_limit(
        request: Request,
        redis: Any = Depends(get_redis),
    ) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:{request.url.path}:{client_ip}"
        now = time.time()
        window_start = now - window_seconds

        # Atomic pipeline: prune old entries → add current → count → set TTL
        pipe = redis.pipeline(transaction=True)
        await pipe.zremrangebyscore(key, 0, window_start)
        await pipe.zadd(key, {str(now): now})
        await pipe.zcard(key)
        await pipe.expire(key, window_seconds)
        results = await pipe.execute()

        count: int = results[2]
        if count > max_calls:
            logger.warning(
                "rate_limit_exceeded",
                path=request.url.path,
                client_ip=client_ip,
                count=count,
                limit=max_calls,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=ErrorResponse(
                    error="rate_limit_exceeded",
                    detail=f"Too many requests. Limit: {max_calls} per {window_seconds}s.",
                    code="RATE_LIMIT_EXCEEDED",
                ).model_dump(),
            )

    return _rate_limit
