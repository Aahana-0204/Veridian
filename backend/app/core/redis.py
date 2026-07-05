"""Async Redis client — lifecycle helpers and FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)

_redis: Any = None  # aioredis.Redis[str] at runtime


async def init_redis(url: str) -> None:
    """Open the Redis connection pool. Called once at app startup."""
    global _redis
    _redis = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    await _redis.ping()
    logger.info("redis_connected", url=url)


async def close_redis() -> None:
    """Close the Redis connection pool. Called once at app shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    logger.info("redis_disconnected")


async def get_redis() -> AsyncGenerator[Any, None]:
    """FastAPI dependency — yields the shared Redis client."""
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() at startup.")
    yield _redis
