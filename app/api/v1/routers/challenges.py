from __future__ import annotations

import math
import uuid
from typing import Annotated, List

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.challenge import (
    ChallengeCreate,
    ChallengeResponse,
    ChallengeUpdate,
    ChallengeScoringConfig,
    ChallengeScoringResponse,
    ChallengeWithRecipeResponse,
    PaginatedChallengeResponse,
)
from app.api.schemas.recipe import LeaderboardResponse
from app.core.database import get_db
from app.core.rate_limit import rate_limit_writes
from app.core.redis_client import get_redis
from app.core.security import get_current_user_id
from app.core.challenge_cache import (
    get_cached_detail,
    get_cached_list,
    invalidate_instance,
    set_cached_detail,
    set_cached_list,
)
from app.services import challenge_service as svc
from app.services.leaderboard_service import leaderboard_service


router = APIRouter(prefix="/challenges", tags=["Challenges"])


DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]


@router.get("", response_model=PaginatedChallengeResponse)
async def list_challenges(
    db: DB,
    redis: Redis,
    _: CurrentUser,
    difficulty: List[str] | None = Query(default=None),
    health_status: List[str] | None = Query(default=None),
    domain_tags: List[str] | None = Query(default=None),
    scoring_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
) -> PaginatedChallengeResponse:
    # TODO: enforce RBAC when role system is implemented
    params = {
        "difficulty": difficulty,
        "health_status": health_status,
        "domain_tags": domain_tags,
        "scoring_type": scoring_type,
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }

    cached = await get_cached_list(redis, params)
    if cached:
        return PaginatedChallengeResponse.model_validate(cached)

    result = await svc.get_instances(
        db,
        difficulty=difficulty,
        health_status=health_status,
        domain_tags=domain_tags,
        scoring_type=scoring_type,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    data = [
        ChallengeResponse.model_validate(r) for r in result["rows"]
    ]
    response_dict = {
        "data": [d.model_dump() for d in data],
        "meta": {
            "page": page,
            "page_size": page_size,
            "total": result["total"],
            "total_pages": math.ceil(result["total"] / page_size),
        },
    }
    await set_cached_list(redis, params, response_dict)
    return PaginatedChallengeResponse.model_validate(response_dict)


@router.post(
    "",
    response_model=ChallengeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_challenge(
    body: ChallengeCreate,
    db: DB,
    redis: Redis,
    user_id: CurrentUser,
    _: None = Depends(rate_limit_writes),
) -> ChallengeResponse:
    # TODO: enforce RBAC when role system is implemented
    instance = await svc.create_instance(db, body, created_by=user_id)
    await invalidate_instance(redis, str(instance.id))
    return ChallengeResponse.model_validate(instance)


@router.get(
    "/{challenge_id}",
    response_model=ChallengeWithRecipeResponse,
)
async def get_challenge(
    challenge_id: uuid.UUID,
    db: DB,
    redis: Redis,
    _: CurrentUser,
) -> ChallengeWithRecipeResponse:
    # TODO: enforce RBAC when role system is implemented
    key = str(challenge_id)
    cached = await get_cached_detail(redis, key)
    if cached:
        return ChallengeWithRecipeResponse.model_validate(cached)
    response = await svc.get_instance_with_recipe(db, challenge_id)
    await set_cached_detail(redis, key, response.model_dump())
    return response


@router.patch(
    "/{challenge_id}",
    response_model=ChallengeResponse,
)
@router.put(
    "/{challenge_id}",
    response_model=ChallengeResponse,
)
async def update_challenge(
    challenge_id: uuid.UUID,
    body: ChallengeUpdate,
    db: DB,
    redis: Redis,
    _: CurrentUser,
    __: None = Depends(rate_limit_writes),
) -> ChallengeResponse:
    # TODO: enforce RBAC when role system is implemented
    instance = await svc.update_instance(db, challenge_id, body)
    await invalidate_instance(redis, str(challenge_id))
    return ChallengeResponse.model_validate(instance)


@router.delete(
    "/{challenge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_challenge(
    challenge_id: uuid.UUID,
    db: DB,
    redis: Redis,
    _: CurrentUser,
    __: None = Depends(rate_limit_writes),
) -> Response:
    # TODO: enforce RBAC when role system is implemented
    await svc.soft_delete_instance(db, challenge_id)
    await invalidate_instance(redis, str(challenge_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{challenge_id}/scoring",
    response_model=ChallengeScoringResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_scoring(
    challenge_id: uuid.UUID,
    body: ChallengeScoringConfig,
    db: DB,
    _: CurrentUser,
) -> ChallengeScoringResponse:
    """Set or replace scoring configuration for a single challenge."""
    return await svc.configure_scoring(db, challenge_id, body)


@router.get(
    "/{challenge_id}/scoring",
    response_model=ChallengeScoringResponse,
)
async def get_scoring(
    challenge_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> ChallengeScoringResponse:
    """Get scoring configuration for a single challenge."""
    return await svc.get_scoring(db, challenge_id)


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
)
async def get_leaderboard(
    redis: Redis,
    _: CurrentUser,
    n: int = 100,
) -> LeaderboardResponse:
    """Global leaderboard: user scores aggregated across challenges."""
    return await leaderboard_service.get_top_n(redis, n=min(n, 500))


@router.get(
    "/leaderboard/me",
)
async def get_my_rank(
    redis: Redis,
    user_id: CurrentUser,
) -> dict:
    """Current user's rank and score on the global leaderboard."""
    return await leaderboard_service.get_user_rank(redis, user_id=str(user_id))
