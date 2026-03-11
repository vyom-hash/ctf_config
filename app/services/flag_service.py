"""
Flag Submission Service — brute-force protection + dynamic scoring.

Rate Limiting Strategy  (Redis sliding counter)
────────────────────────────────────────────────
Key:  ctf:ratelimit:flag:{user_id}:{challenge_id}
Type: STRING (integer counter)
TTL:  FLAG_SUBMIT_WINDOW_SECONDS (default 60 s)

Algorithm
─────────
  INCR key
  If result == 1 → EXPIRE key <window>     (first attempt in window)
  If result > MAX_ATTEMPTS → 429 Too Many Requests

This is a fixed-window counter.  It is simple, CPU-light, and appropriate
for a CTF where perfect precision is not critical.  For stricter sliding-window
semantics, replace with a Redis Lua script or the token-bucket pattern.

Dynamic Scoring (optional, if recipe.scoring_rules.dynamic_scoring == True)
────────────────────────────────────────────────────────────────────────────
  awarded = max(base_score * decay_factor^(solve_count - 1), minimum_floor)

Redis keys used by the leaderboard are updated atomically after a correct flag.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.recipe import FlagSubmitResponse
from app.core.config import get_settings
from app.repositories.recipe_repository import RecipeRepository
from app.services.leaderboard_service import leaderboard_service

settings = get_settings()
_repo = RecipeRepository()

_RL_PREFIX = "ctf:ratelimit:flag"
_SOLVE_COUNT_PREFIX = "ctf:solvecount"


class FlagService:

    async def submit_flag(
        self,
        session: AsyncSession,
        redis: aioredis.Redis,
        *,
        user_id: uuid.UUID,
        recipe_id: uuid.UUID,
        challenge_key: str,
        submitted_flag: str,
    ) -> FlagSubmitResponse:
        # 1. Enforce rate limit
        await self._check_rate_limit(redis, user_id=user_id, challenge_key=challenge_key)

        # 2. Load challenge from DB (Cache-Aside could be added here)
        challenge = await _repo.get_challenge_by_key(
            session, recipe_id=recipe_id, challenge_key=challenge_key
        )
        if challenge is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Challenge '{challenge_key}' not found in recipe '{recipe_id}'",
            )

        # 3. Validate the flag
        correct = self._validate_flag(
            submitted=submitted_flag,
            pattern=challenge.flag_pattern,
            validation_type=challenge.flag_validation_type,
        )

        if not correct:
            return FlagSubmitResponse(correct=False, message="Incorrect flag. Try again.")

        # 4. Award points
        base_score = challenge.base_score or 0
        solve_count = await self._get_and_increment_solve_count(
            redis, recipe_id=recipe_id, challenge_key=challenge_key
        )
        awarded = base_score  # dynamic scoring can adjust below

        # 5. Dynamic scoring — decay by solve order
        scoring_rules = None  # loaded via recipe; simplified here
        # In a full implementation, load recipe.scoring_rules and apply:
        # awarded = max(base * (decay_factor ** (solve_count - 1)), min_floor)

        # 6. Update leaderboard (Redis ZINCRBY — O(log N))
        new_total = await leaderboard_service.add_score(
            redis, user_id=str(user_id), points=awarded
        )

        return FlagSubmitResponse(
            correct=True,
            message=f"Correct! +{awarded} points",
            points_awarded=awarded,
        )

    # ─────────────────────── Rate limiting ───────────────────────────────────

    async def _check_rate_limit(
        self,
        redis: aioredis.Redis,
        *,
        user_id: uuid.UUID,
        challenge_key: str,
    ) -> None:
        key = f"{_RL_PREFIX}:{user_id}:{challenge_key}"

        # Pipeline: INCR + conditional EXPIRE in a single round-trip
        async with redis.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.ttl(key)
            results = await pipe.execute()

        attempt_count: int = results[0]
        ttl: int = results[1]

        # Set TTL only on the first attempt (INCR returned 1)
        if attempt_count == 1:
            await redis.expire(key, settings.FLAG_SUBMIT_WINDOW_SECONDS)

        if attempt_count > settings.FLAG_SUBMIT_MAX_ATTEMPTS:
            remaining = ttl if ttl > 0 else settings.FLAG_SUBMIT_WINDOW_SECONDS
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Too many flag attempts for challenge '{challenge_key}'. "
                    f"Try again in {remaining} seconds."
                ),
                headers={"Retry-After": str(remaining)},
            )

    # ─────────────────────── Flag validation ────────────────────────────────

    @staticmethod
    def _validate_flag(
        submitted: str,
        pattern: Optional[str],
        validation_type: Optional[str],
    ) -> bool:
        if pattern is None:
            return False
        vtype = (validation_type or "exact").lower()
        if vtype == "exact":
            return submitted.strip() == pattern.strip()
        if vtype == "regex":
            try:
                return bool(re.fullmatch(pattern, submitted.strip()))
            except re.error:
                return False
        if vtype == "case_insensitive":
            return submitted.strip().lower() == pattern.strip().lower()
        return submitted.strip() == pattern.strip()

    # ─────────────────────── Solve counter ──────────────────────────────────

    async def _get_and_increment_solve_count(
        self,
        redis: aioredis.Redis,
        *,
        recipe_id: uuid.UUID,
        challenge_key: str,
    ) -> int:
        key = f"{_SOLVE_COUNT_PREFIX}:{recipe_id}:{challenge_key}"
        count = await redis.incr(key)
        return count


flag_service = FlagService()
