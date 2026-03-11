from __future__ import annotations

import math
import uuid
from typing import Annotated, List

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.exercise_instance import (
    ExerciseInstanceCreate,
    ExerciseInstanceResponse,
    ExerciseInstanceUpdate,
    ExerciseScoringConfig,
    ExerciseScoringResponse,
    ExerciseWithRecipeResponse,
    PaginatedResponse,
)
from app.api.schemas.recipe import LeaderboardResponse
from app.core.database import get_db
from app.core.rate_limit import rate_limit_writes
from app.core.redis_client import get_redis
from app.core.security import get_current_user_id
from app.core.exercise_cache import (
    get_cached_detail,
    get_cached_list,
    invalidate_instance,
    set_cached_detail,
    set_cached_list,
)
from app.services import exercise_instance_service as svc
from app.services.leaderboard_service import leaderboard_service


router = APIRouter(prefix="/exercise-instances", tags=["Exercise Instances"])


DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]


@router.get("", response_model=PaginatedResponse)
async def list_instances(
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
) -> PaginatedResponse:
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
        return PaginatedResponse.model_validate(cached)

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
        ExerciseInstanceResponse.model_validate(r) for r in result["rows"]
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
    return PaginatedResponse.model_validate(response_dict)


@router.post(
    "",
    response_model=ExerciseInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_instance(
    body: ExerciseInstanceCreate,
    db: DB,
    redis: Redis,
    user_id: CurrentUser,
    _: None = Depends(rate_limit_writes),
) -> ExerciseInstanceResponse:
    # TODO: enforce RBAC when role system is implemented
    instance = await svc.create_instance(db, body, created_by=user_id)
    await invalidate_instance(redis, str(instance.id))
    return ExerciseInstanceResponse.model_validate(instance)


@router.get(
    "/{instance_id}",
    response_model=ExerciseWithRecipeResponse,
)
async def get_instance(
    instance_id: uuid.UUID,
    db: DB,
    redis: Redis,
    _: CurrentUser,
) -> ExerciseWithRecipeResponse:
    # TODO: enforce RBAC when role system is implemented
    key = str(instance_id)
    cached = await get_cached_detail(redis, key)
    if cached:
        return ExerciseWithRecipeResponse.model_validate(cached)
    response = await svc.get_instance_with_recipe(db, instance_id)
    await set_cached_detail(redis, key, response.model_dump())
    return response


@router.patch(
    "/{instance_id}",
    response_model=ExerciseInstanceResponse,
)
@router.put(
    "/{instance_id}",
    response_model=ExerciseInstanceResponse,
)
async def update_instance(
    instance_id: uuid.UUID,
    body: ExerciseInstanceUpdate,
    db: DB,
    redis: Redis,
    _: CurrentUser,
    __: None = Depends(rate_limit_writes),
) -> ExerciseInstanceResponse:
    # TODO: enforce RBAC when role system is implemented
    instance = await svc.update_instance(db, instance_id, body)
    await invalidate_instance(redis, str(instance_id))
    return ExerciseInstanceResponse.model_validate(instance)


@router.delete(
    "/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_instance(
    instance_id: uuid.UUID,
    db: DB,
    redis: Redis,
    _: CurrentUser,
    __: None = Depends(rate_limit_writes),
) -> Response:
    # TODO: enforce RBAC when role system is implemented
    await svc.soft_delete_instance(db, instance_id)
    await invalidate_instance(redis, str(instance_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{instance_id}/scoring",
    response_model=ExerciseScoringResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_scoring_for_instance(
    instance_id: uuid.UUID,
    body: ExerciseScoringConfig,
    db: DB,
    _: CurrentUser,
) -> ExerciseScoringResponse:
    """Set or replace scoring configuration for a single exercise instance."""
    return await svc.configure_scoring(db, instance_id, body)


@router.get(
    "/{instance_id}/scoring",
    response_model=ExerciseScoringResponse,
)
async def get_scoring_for_instance(
    instance_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> ExerciseScoringResponse:
    """Get scoring configuration for a single exercise instance."""
    return await svc.get_scoring(db, instance_id)


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
)
async def get_leaderboard(
    redis: Redis,
    _: CurrentUser,
    n: int = 100,
) -> LeaderboardResponse:
    """Global leaderboard: user scores aggregated across exercise instances."""
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
