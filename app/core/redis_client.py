"""
Redis async connection-pool manager.

A single ConnectionPool is created at startup and reused for every request,
giving us the same "pool" ergonomics as the DB engine.  The pool size matches
the DB overflow capacity so neither side becomes a bottleneck.
"""
from collections.abc import AsyncGenerator
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import get_settings

settings = get_settings()

_pool: Optional[aioredis.ConnectionPool] = None


def _build_pool() -> aioredis.ConnectionPool:
    return aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_POOL_MAX_CONNECTIONS,
        decode_responses=True,
    )


async def init_redis_pool() -> None:
    """Call once at application startup."""
    global _pool
    _pool = _build_pool()


async def close_redis_pool() -> None:
    """Call once at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None


def get_redis_pool() -> aioredis.ConnectionPool:
    if _pool is None:
        raise RuntimeError("Redis pool not initialised — call init_redis_pool() first")
    return _pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency that yields a Redis client backed by the shared pool."""
    client = aioredis.Redis(connection_pool=get_redis_pool())
    try:
        yield client
    finally:
        await client.aclose()


async def get_redis_optional() -> AsyncGenerator[Optional[aioredis.Redis], None]:
    """Yields Redis client when pool is initialised; otherwise None (e.g. DB-only concurrency check)."""
    try:
        pool = get_redis_pool()
        client = aioredis.Redis(connection_pool=pool)
        try:
            yield client
        finally:
            await client.aclose()
    except RuntimeError:
        yield None
