"""
Deployment creation service — enforces constraints and concurrency.

Flow:
  1. Validate recipe_version (exists, published, approved).
  2. Redis INCR gate (optional fast reject).
  3. In one transaction: count RUNNING+ALLOCATING, check limit, insert deployment.
  4. Return deployment response; expiration is enforced by a separate job.
"""
from __future__ import annotations

import copy
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.deployment import (
    AccessConfig,
    DeploymentCreateRequest,
    DeploymentCreateFromDraftRequest,
    DeploymentResponse,
    DeploymentListItem,
    DeploymentUpdateRequest,
    PaginatedDeploymentResponse,
)
from app.core.constraints import get_deployment_constraints
from app.core.config import get_settings
from app.core.deployment_constants import PROVIDER_PROFILE
from app.models.recipe import ApprovalStatus
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.recipe_repository import RecipeRepository
from app.models.deployment import Deployment, DeploymentStatus
from app.models.challenge import Challenge
from app.api.schemas.challenge import (
    DeploymentChallengeResponse,
    DeploymentHintResponse,
    DeploymentMilestoneResponse,
    ChallengeResponse,
    ChallengeWithRecipeResponse,
    FlagStore,
    RecipeSubset,
)
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

_settings = get_settings()
_repo = DeploymentRepository()
_recipe_repo = RecipeRepository()

# Redis key for fast concurrency gate (can reconcile from DB periodically)
REDIS_KEY = _settings.REDIS_KEY_ACTIVE_DEPLOYMENT_COUNT


def _expires_at(constraints) -> datetime:
    """expires_at = now() + auto_expire_minutes."""
    return datetime.now(timezone.utc) + timedelta(
        minutes=constraints.auto_expire_minutes
    )


async def _check_recipe_version(
    session: AsyncSession,
    recipe_version_id: uuid.UUID,
) -> None:
    """Ensure version exists, is published, and approved. Raises HTTPException."""
    version = await _recipe_repo.get_version_by_id(session, recipe_version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Recipe version not found",
                "recipe_version_id": str(recipe_version_id),
            },
        )
    if not version.is_published:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Recipe version not published",
                "recipe_version_id": str(recipe_version_id),
            },
        )
    if version.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Recipe version not approved for deployment",
                "recipe_version_id": str(recipe_version_id),
                "approval_status": version.approval_status,
            },
        )


async def _ensure_recipe_approved(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    context: str = "recipe_id",
) -> None:
    """Ensure the recipe is approved; raise 403 or 404 otherwise."""
    recipe = await _recipe_repo.get_full_recipe(session, recipe_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Recipe not found",
                context: str(recipe_id),
            },
        )
    if recipe.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Recipe not approved for deployment",
                context: str(recipe_id),
                "approval_status": recipe.approval_status,
                "message": "Submit the recipe for approval and get it approved before creating a deployment.",
            },
        )


async def _redis_incr_gate(redis: aioredis.Redis) -> bool:
    """
    Increment Redis counter. If new value > limit, decrement and return False.
    Caller should return 429. If True, caller proceeds to DB transaction.
    """
    constraints = get_deployment_constraints()
    limit = constraints.maximum_concurrent_deployments
    new_count = await redis.incr(REDIS_KEY)
    if new_count > limit:
        await redis.decr(REDIS_KEY)
        return False
    return True


async def _redis_decr(redis: aioredis.Redis) -> None:
    """Decrement counter (e.g. after failed insert or when deployment leaves RUNNING/ALLOCATING)."""
    await redis.decr(REDIS_KEY)


async def _load_exercises_json_for_version(
    session: AsyncSession,
    recipe_version_id: uuid.UUID,
) -> Optional[List[Dict[str, Any]]]:
    """Load challenges for the recipe version and return as list of dicts for JSONB storage."""
    instances = (
        await session.execute(
            select(Challenge)
            .options(
                selectinload(Challenge.validation_targets),
                selectinload(Challenge.hints),
                selectinload(Challenge.attachments),
                selectinload(Challenge.objectives),
                selectinload(Challenge.dependencies),
            )
            .where(
                and_(
                    Challenge.recipe_version_id == recipe_version_id,
                    Challenge.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    if not instances:
        return None
    return [ChallengeResponse.model_validate(ei).model_dump(mode="json") for ei in instances]


async def create_deployment_unified(
    session: AsyncSession,
    request: DeploymentCreateRequest,
    created_by: Optional[uuid.UUID],
    redis: Optional[aioredis.Redis] = None,
) -> DeploymentResponse:
    """
    Single entry for POST /api/v1/deployments. Dispatches to create by recipe_version_id
    or create by recipe_id + recipe_version (from-recipe) based on request shape.
    """
    if request.recipe_version_id is not None:
        return await create_deployment(session, request, created_by, redis)
    # From-recipe mode (validator ensures these are set)
    from_recipe = DeploymentCreateFromDraftRequest(
        recipe_id=request.recipe_id,
        recipe_version=request.recipe_version,
        initiator_user=request.initiator_user,
        experience_type=request.experience_type,
        duration_hours=request.duration_hours,
        access_method=request.access_method,
        name=request.name,
        description=request.description,
        participant_id=request.participant_id,
        access=request.access,
        target_env=request.target_env,
    )
    return await create_deployment_from_draft(session, from_recipe, redis)


async def create_deployment(
    session: AsyncSession,
    request: DeploymentCreateRequest,
    created_by: Optional[uuid.UUID],
    redis: Optional[aioredis.Redis] = None,
) -> DeploymentResponse:
    """
    Create deployment by recipe_version_id (mode 1). Call only when request.recipe_version_id is set.
    """
    if request.recipe_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "recipe_version_id is required for this flow"},
        )
    constraints = get_deployment_constraints()

    # 1) Recipe version (exists, published, approved)
    await _check_recipe_version(session, request.recipe_version_id)

    # 1a) Ensure recipe is approved (version belongs to a recipe)
    version = await _recipe_repo.get_version_by_id(session, request.recipe_version_id)
    if version is not None and version.recipe_id is not None:
        await _ensure_recipe_approved(
            session, version.recipe_id, context="recipe_id"
        )

    # 1b) Load immutable recipe spec (snapshot) for this version
    recipe_spec = await _recipe_repo.get_snapshot_by_version_id(
        session, request.recipe_version_id
    )
    if recipe_spec is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "recipe_snapshot_missing",
                "message": "No snapshot found for the specified recipe version id.",
            },
        )

    # 2) Redis fast gate (optional; skip if redis not injected)
    if redis is not None:
        if not await _redis_incr_gate(redis):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "maximum_concurrent_deployments",
                    "message": (
                        f"Concurrent deployment limit reached ({constraints.maximum_concurrent_deployments}). "
                        "Try again later."
                    ),
                    "code": "DEPLOYMENT_LIMIT_EXCEEDED",
                },
            )

    try:
        # 3) Transactional count + insert
        await _repo.acquire_deployment_lock(session)
        count = await _repo.count_running_and_allocating(session)
        if count >= constraints.maximum_concurrent_deployments:
            if redis is not None:
                await _redis_decr(redis)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "maximum_concurrent_deployments",
                    "message": (
                        f"Concurrent deployment limit reached ({constraints.maximum_concurrent_deployments}). "
                        "Try again later."
                    ),
                    "code": "DEPLOYMENT_LIMIT_EXCEEDED",
                },
            )

        expires_at = _expires_at(constraints)
        access_dict = request.access.model_dump() if request.access else None
        exercises_data = await _load_exercises_json_for_version(
            session, request.recipe_version_id
        )
        deployment = await _repo.create(
            session,
            recipe_version_id=request.recipe_version_id,
            recipe_id=version.recipe_id if version else None,
            status=DeploymentStatus.ALLOCATING,
            expires_at=expires_at,
            team_size=1,
            participant_id=request.participant_id,
            name=request.name,
            description=request.description,
            created_by=created_by,
            access=access_dict,
            access_method=request.access_method,
            recipe_spec=copy.deepcopy(recipe_spec),
            target_env=request.target_env,
            exercises=exercises_data,
        )
    except HTTPException:
        raise
    except Exception:
        if redis is not None:
            await _redis_decr(redis)
        raise

    return _to_response(deployment)


async def create_deployment_from_draft(
    session: AsyncSession,
    request: DeploymentCreateFromDraftRequest,
    redis: Optional[aioredis.Redis] = None,
) -> DeploymentResponse:
    """
    Create a deployment from recipe_id + recipe_version (version number).
    Resolves recipe_version_id, loads recipe_spec, sets expires_at from duration_hours.
    """
    constraints = get_deployment_constraints()

    # 1) Ensure recipe is approved
    await _ensure_recipe_approved(
        session, request.recipe_id, context="recipe_id"
    )

    # 2) Resolve recipe version by recipe_id + version_number
    version = await _recipe_repo.get_version_by_draft_and_number(
        session,
        request.recipe_id,
        request.recipe_version,
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Recipe version not found",
                "recipe_id": str(request.recipe_id),
                "recipe_version": request.recipe_version,
            },
        )
    recipe_version_id = version.id

    # 3) Validate version is published and approved
    await _check_recipe_version(session, recipe_version_id)

    # 4) Load recipe spec (snapshot JSON)
    recipe_spec = await _recipe_repo.get_snapshot_by_version_id(
        session, recipe_version_id
    )
    if recipe_spec is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "recipe_snapshot_missing",
                "message": "No snapshot found for the specified recipe version.",
            },
        )

    # 5) Redis gate
    if redis is not None:
        if not await _redis_incr_gate(redis):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "maximum_concurrent_deployments",
                    "message": (
                        f"Concurrent deployment limit reached ({constraints.maximum_concurrent_deployments}). "
                        "Try again later."
                    ),
                    "code": "DEPLOYMENT_LIMIT_EXCEEDED",
                },
            )

    try:
        await _repo.acquire_deployment_lock(session)
        count = await _repo.count_running_and_allocating(session)
        if count >= constraints.maximum_concurrent_deployments:
            if redis is not None:
                await _redis_decr(redis)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "maximum_concurrent_deployments",
                    "message": (
                        f"Concurrent deployment limit reached ({constraints.maximum_concurrent_deployments}). "
                        "Try again later."
                    ),
                    "code": "DEPLOYMENT_LIMIT_EXCEEDED",
                },
            )

        expires_at = datetime.now(timezone.utc) + timedelta(hours=request.duration_hours)
        access_dict = request.access.model_dump() if request.access else None
        exercises_data = await _load_exercises_json_for_version(
            session, recipe_version_id
        )
        deployment = await _repo.create(
            session,
            recipe_version_id=recipe_version_id,
            status=DeploymentStatus.ALLOCATING,
            expires_at=expires_at,
            team_size=1,
            participant_id=request.participant_id,
            name=request.name,
            description=request.description,
            created_by=request.initiator_user,
            access=access_dict,
            access_method=request.access_method,
            recipe_spec=copy.deepcopy(recipe_spec),
            recipe_id=request.recipe_id,
            experience_type=request.experience_type,
            duration_hours=request.duration_hours,
            target_env=request.target_env,
            exercises=exercises_data,
        )
    except HTTPException:
        raise
    except Exception:
        if redis is not None:
            await _redis_decr(redis)
        raise

    return _to_response(deployment)


def _build_recipe_subset(d: Deployment) -> Optional[RecipeSubset]:
    """Build RecipeSubset from the deployment's stored recipe_spec snapshot."""
    spec = getattr(d, "recipe_spec", None)
    if not isinstance(spec, dict) or not spec:
        return None
    meta = spec.get("metadata") or {}
    return RecipeSubset(
        recipe_id=getattr(d, "recipe_id", None),
        name=meta.get("name") or "",
        category=meta.get("category"),
        version_number=spec.get("version_number", 0),
        recipe_version_id=d.recipe_version_id,
    )


def _build_challenge(item: Dict[str, Any]) -> DeploymentChallengeResponse:
    """Convert a stored challenge dict to DeploymentChallengeResponse for deployment output."""
    validation_targets = item.get("validation_targets") or []
    flag_template: Optional[str] = None
    flag_store: Optional[FlagStore] = None
    target_units: List[str] = []
    if validation_targets:
        vt = validation_targets[0]
        flag_template = vt.get("flag_template")
        target_units = vt.get("target_units") or []
        raw_fs = vt.get("flag_store")
        if isinstance(raw_fs, dict) and raw_fs:
            flag_store = FlagStore.model_validate(raw_fs)

    hints = [
        DeploymentHintResponse(hint=h["hint"], points_impacted=h["points_impacted"])
        for h in (item.get("hints") or [])
    ]
    milestones = [
        DeploymentMilestoneResponse(goal=o["goal"], points_impacted=o["points_impacted"])
        for o in (item.get("objectives") or [])
    ]

    return DeploymentChallengeResponse(
        id=item["id"],
        type=item.get("type"),
        flag_template=flag_template,
        tags=item.get("domain_tags") or [],
        flag_store=flag_store,
        target_units=target_units,
        title=item["title"],
        points=item["reward_points"],
        level=item["difficulty"],
        description=item["description"],
        verification_automation=item.get("verification_automation"),
        hints=hints,
        objectives=milestones,
    )


def _build_recipe_specs(d: Deployment) -> Optional[Dict[str, Any]]:
    """Build recipe_specs dict from stored recipe_spec snapshot."""
    spec = getattr(d, "recipe_spec", None)
    if not isinstance(spec, dict) or not spec:
        return None

    workload_units = copy.deepcopy(spec.get("workload_units") or [])

    # Build unit_id → unit name map for ingress_policies resolution
    wu_id_to_name: Dict[str, str] = {
        str(wu.get("id")): wu.get("name") or str(wu.get("id"))
        for wu in workload_units
        if wu.get("id") is not None
    }

    # Normalise workload_units: strip id, rename description→desc, assigned_domain→domain
    for wu in workload_units:
        wu.pop("id", None)
        if "description" in wu:
            wu["desc"] = wu.pop("description")
        if "assigned_domain" in wu:
            wu["domain"] = wu.pop("assigned_domain")

    # Strip id from domains
    domains = [{k: v for k, v in d.items() if k != "id"} for d in copy.deepcopy(spec.get("domains") or [])]

    # Take first gateway from gateways list; resolve unit_id → wl_unit in ingress_policies
    gateways = spec.get("gateways") or []
    gateway = None
    if gateways:
        gw = copy.deepcopy(gateways[0])
        gw.pop("id", None)
        resolved_policies = []
        for p in (gw.get("ingress_policies") or []):
            p = dict(p)
            uid = p.pop("unit_id", None)
            p["wl_unit"] = wu_id_to_name.get(str(uid), str(uid)) if uid is not None else None
            resolved_policies.append(p)
        gw["ingress_policies"] = resolved_policies
        gateway = gw

    return {
        "global_domain": copy.deepcopy(spec.get("global_domain")),
        "domains": domains,
        "workload_units": workload_units,
        "gateway": gateway,
        "access_box": copy.deepcopy(spec.get("access_box")),
    }


def _build_challenge_specs(
    d: Deployment,
    challenges: Optional[List[ChallengeResponse]] = None,
) -> Optional[Dict[str, Any]]:
    """Build challenge_specs dict with challenges list and execution_type."""
    stored = getattr(d, "exercises", None)
    if isinstance(stored, list) and stored:
        source = stored
        challenge_list = [_build_challenge(item) for item in stored]
    elif challenges:
        source = [c.model_dump(mode="json") for c in challenges]
        challenge_list = [_build_challenge(item) for item in source]
    else:
        return None

    # execution_type is sub_category promoted to wrapper level (from first challenge)
    execution_type: Optional[str] = None
    if source:
        execution_type = source[0].get("sub_category")

    return {
        "challenges": [c.model_dump(mode="json") for c in challenge_list],
        "execution_type": execution_type,
    }


def _to_response(
    d: Deployment,
    challenges: Optional[List[ChallengeResponse]] = None,
) -> DeploymentResponse:
    """Build DeploymentResponse from ORM deployment."""
    return DeploymentResponse(
        dep_id=d.id,
        dep_name=d.name,
        desc=d.description,
        target_env=getattr(d, "target_env", None),
        participant_id=getattr(d, "participant_id", None),
        access_method=getattr(d, "access_method", None),
        recipe_specs=_build_recipe_specs(d),
        challenge_specs=_build_challenge_specs(d, challenges),
    )


async def get_deployment(
    session: AsyncSession,
    deployment_id: uuid.UUID,
) -> DeploymentResponse:
    """Fetch deployment by id; 404 if not found."""
    deployment = await _repo.get_by_id(session, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Deployment not found",
                "deployment_id": str(deployment_id),
            },
        )
    # Load all challenges bound to this deployment's recipe_version_id
    instances = (
        await session.execute(
            select(Challenge)
            .options(
                selectinload(Challenge.validation_targets),
                selectinload(Challenge.hints),
                selectinload(Challenge.attachments),
                selectinload(Challenge.objectives),
                selectinload(Challenge.dependencies),
            )
            .where(
                and_(
                    Challenge.recipe_version_id == deployment.recipe_version_id,
                    Challenge.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    instance_responses = [
        ChallengeResponse.model_validate(ei) for ei in instances
    ]
    return _to_response(deployment, instance_responses)


async def update_deployment(
    session: AsyncSession,
    deployment_id: uuid.UUID,
    payload: DeploymentUpdateRequest,
) -> DeploymentResponse:
    """Partial update of deployment. Can update name, access, target_env, recipe_spec, exercises."""
    deployment = await _repo.get_by_id(session, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Deployment not found",
                "deployment_id": str(deployment_id),
            },
        )
    updates = payload.model_dump(exclude_unset=True)
    updated = await _repo.update(session, deployment_id, updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Deployment not found", "deployment_id": str(deployment_id)},
        )
    # Recompute challenges for the (unchanged) recipe_version_id
    instances = (
        await session.execute(
            select(Challenge)
            .options(
                selectinload(Challenge.validation_targets),
                selectinload(Challenge.hints),
                selectinload(Challenge.attachments),
                selectinload(Challenge.objectives),
                selectinload(Challenge.dependencies),
            )
            .where(
                and_(
                    Challenge.recipe_version_id == updated.recipe_version_id,
                    Challenge.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    instance_responses = [
        ChallengeResponse.model_validate(ei) for ei in instances
    ]
    return _to_response(updated, instance_responses)


async def delete_deployment(
    session: AsyncSession,
    deployment_id: uuid.UUID,
) -> None:
    """Delete deployment by id. Raises 404 if not found."""
    deployment = await _repo.get_by_id(session, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Deployment not found",
                "deployment_id": str(deployment_id),
            },
        )
    await _repo.delete_by_id(session, deployment_id)


async def list_deployments(
    session: AsyncSession,
    *,
    recipe_version_id: Optional[uuid.UUID] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> PaginatedDeploymentResponse:
    """List deployments with optional recipe_version_id filter. Returns paginated list."""
    result = await _repo.list_deployments(
        session,
        recipe_version_id=recipe_version_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows = result["rows"]
    total = result["total"]
    items = [
        DeploymentListItem(
            dep_id=d.id,
            recipe_version_id=d.recipe_version_id,
            status=d.status,
            expires_at=d.expires_at,
            team_size=d.team_size,
            dep_name=d.name,
            participant_id=getattr(d, "participant_id", None),
            created_at=d.created_at,
            updated_at=d.updated_at,
            recipe_id=getattr(d, "recipe_id", None),
            experience_type=getattr(d, "experience_type", None),
            duration_hours=getattr(d, "duration_hours", None),
            access_method=getattr(d, "access_method", None),
            target_env=getattr(d, "target_env", None),
        )
        for d in rows
    ]
    return PaginatedDeploymentResponse(
        data=items,
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if page_size else 0,
        },
    )
