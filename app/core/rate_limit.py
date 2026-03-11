import time
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from app.core.redis_client import get_redis
from app.core.security import get_current_user_id


WRITE_LIMIT = 60
WINDOW_SECS = 60


async def rate_limit_writes(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
    current_user_id: Any = Depends(get_current_user_id),
) -> None:
    """
    Sliding-window rate limiter for write-heavy endpoints.

    Keyed by user_id + endpoint path. Uses Redis sorted set timestamps.
    """
    user_id = str(current_user_id)
    endpoint = request.url.path.replace("/", "_")
    key = f"rate_limit:{user_id}:{endpoint}"
    now = time.time()
    window_start = now - WINDOW_SECS

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    
    # Use UUID to prevent ZADD collisions for requests arriving in the same microsecond
    member_id = f"{now}:{uuid.uuid4()}"
    pipe.zadd(key, {member_id: now})
    
    pipe.zcard(key)
    pipe.expire(key, WINDOW_SECS)
    _, _, count, _ = await pipe.execute()

    if count > WRITE_LIMIT:
        retry_after = int(WINDOW_SECS)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. Retry after {retry_after}s.",
            },
            headers={"Retry-After": str(retry_after)},
        )

