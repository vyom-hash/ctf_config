import hashlib
import json
from typing import Any, Dict, Optional

import redis.asyncio as aioredis


LIST_TTL = 30
DETAIL_TTL = 60
LIST_NS = "ei:list"
DETAIL_NS = "ei:detail"


def _list_key(params: Dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return f"{LIST_NS}:{hashlib.md5(raw.encode()).hexdigest()}"


def _detail_key(instance_id: str) -> str:
    return f"{DETAIL_NS}:{instance_id}"


async def get_cached_list(
    redis: aioredis.Redis, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    val = await redis.get(_list_key(params))
    return json.loads(val) if val else None


async def set_cached_list(
    redis: aioredis.Redis, params: Dict[str, Any], data: Dict[str, Any]
) -> None:
    await redis.setex(_list_key(params), LIST_TTL, json.dumps(data, default=str))


async def get_cached_detail(
    redis: aioredis.Redis, instance_id: str
) -> Optional[Dict[str, Any]]:
    val = await redis.get(_detail_key(instance_id))
    return json.loads(val) if val else None


async def set_cached_detail(
    redis: aioredis.Redis, instance_id: str, data: Dict[str, Any]
) -> None:
    await redis.setex(_detail_key(instance_id), DETAIL_TTL, json.dumps(data, default=str))


async def invalidate_instance(redis: aioredis.Redis, instance_id: str) -> None:
    keys_to_delete = [_detail_key(instance_id)]
    async for key in redis.scan_iter(f"{LIST_NS}:*"):
        keys_to_delete.append(key)
    
    if keys_to_delete:
        await redis.delete(*keys_to_delete)

