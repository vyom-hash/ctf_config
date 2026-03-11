"""
Leaderboard Service — Redis Sorted Set (ZSET) implementation.

Architecture: Cache-Aside
─────────────────────────
Read path  → try Redis ZSET → on miss load from Postgres → write-back to Redis
Write path → ZADD / ZINCRBY atomically updates Redis; Postgres is source of truth

Why ZSET?
─────────
ZADD / ZINCRBY / ZREVRANGE are all O(log N) — with 50 000 participants the
leaderboard is still fetched in microseconds vs a full table scan in Postgres.

Redis key schema
────────────────
  ctf:leaderboard                  → ZSET  score → user_id
  ctf:leaderboard:cache:top{n}     → STRING  cached JSON of top-N (TTL = 30 s)
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis

from app.api.schemas.recipe import LeaderboardEntry, LeaderboardResponse
from app.core.config import get_settings

settings = get_settings()

_ZSET_KEY = settings.LEADERBOARD_KEY
_CACHE_PREFIX = "ctf:leaderboard:cache:top"


class LeaderboardService:
    """Stateless — instantiate once and inject into endpoints."""

    # ─────────────────────── Write operations ────────────────────────────────

    async def add_score(
        self,
        redis: aioredis.Redis,
        *,
        user_id: str,
        points: float,
    ) -> float:
        """
        Atomically increment a user's score and return the new total.
        ZINCRBY is O(log N).
        """
        new_score = await redis.zincrby(_ZSET_KEY, points, user_id)
        # Invalidate cached snapshots
        await redis.delete(f"{_CACHE_PREFIX}{settings.LEADERBOARD_TOP_N}")
        return new_score

    async def set_score(
        self,
        redis: aioredis.Redis,
        *,
        user_id: str,
        score: float,
    ) -> None:
        """Overwrite a user's score (useful for score corrections)."""
        await redis.zadd(_ZSET_KEY, {user_id: score})
        await redis.delete(f"{_CACHE_PREFIX}{settings.LEADERBOARD_TOP_N}")

    # ─────────────────────── Read operations ─────────────────────────────────

    async def get_top_n(
        self,
        redis: aioredis.Redis,
        *,
        n: int = 100,
    ) -> LeaderboardResponse:
        """
        Fetch top-N players with Cache-Aside.

        1. Try the JSON string cache (TTL = LEADERBOARD_CACHE_TTL seconds).
        2. On miss: read from the ZSET (O(log N + N)), rebuild JSON, cache it.
        """
        cache_key = f"{_CACHE_PREFIX}{n}"

        cached = await redis.get(cache_key)
        if cached:
            raw = json.loads(cached)
            return LeaderboardResponse(**raw)

        # Cache miss — read from ZSET
        entries = await self._fetch_from_zset(redis, n=n)
        total = await redis.zcard(_ZSET_KEY)

        response = LeaderboardResponse(entries=entries, total_participants=total)

        # Write-back with TTL
        await redis.set(
            cache_key,
            response.model_dump_json(),
            ex=settings.LEADERBOARD_CACHE_TTL,
        )
        return response

    async def get_user_rank(
        self,
        redis: aioredis.Redis,
        *,
        user_id: str,
    ) -> dict:
        """Return a user's rank (0-indexed from top) and score."""
        rank = await redis.zrevrank(_ZSET_KEY, user_id)
        score = await redis.zscore(_ZSET_KEY, user_id)
        return {
            "user_id": user_id,
            "rank": (rank + 1) if rank is not None else None,
            "score": score,
        }

    # ─────────────────────── Helpers ─────────────────────────────────────────

    async def _fetch_from_zset(
        self, redis: aioredis.Redis, *, n: int
    ) -> list[LeaderboardEntry]:
        """ZREVRANGE with scores — returns list[(member, score)] highest first."""
        raw: list[tuple[str, float]] = await redis.zrevrange(
            _ZSET_KEY, 0, n - 1, withscores=True
        )
        return [
            LeaderboardEntry(rank=idx + 1, user_id=member, score=score)
            for idx, (member, score) in enumerate(raw)
        ]


leaderboard_service = LeaderboardService()
