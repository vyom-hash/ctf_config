"""
Deployment creation service — enforces constraints and concurrency.

Flow:
  1. Validate team_configuration (member_ids vs min/max / teams disabled).
  2. Validate recipe_version (exists, published, approved).
  3. Redis INCR gate (optional fast reject).
  4. In one transaction: count RUNNING+ALLOCATING, check limit, insert deployment.
  5. Return deployment response; expiration is enforced by a separate job.
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
    AccessGatewayConfig,
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
from app.models.exercise_instance import ExerciseInstance
from app.api.schemas.exercise_instance import (
    ExerciseInstanceResponse,
    ExerciseWithRecipeResponse,
    RecipeSubset,
)
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

_settings = get_settings()
_repo = DeploymentRepository()
_recipe_repo = RecipeRepository()

# Redis key for fast concurrency gate (can reconcile from DB periodically)
REDIS_KEY = _settings.REDIS_KEY_ACTIVE_DEPLOYMENT_COUNT


def _team_size_and_validate(
    request: DeploymentCreateRequest,
) -> int:
    """Resolve team_size and validate against platform team_configuration. Raises ValueError."""
    constraints = get_deployment_constraints()
    tc = constraints.team_configuration
    member_count = len(request.member_ids)
    tc.validate_team_size(member_count)
    return member_count if tc.enabled else 1


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
    """Load exercise instances for the recipe version and return as list of dicts for JSONB storage."""
    instances = (
        await session.execute(
            select(ExerciseInstance)
            .options(
                selectinload(ExerciseInstance.validation_targets),
                selectinload(ExerciseInstance.guidance_steps),
                selectinload(ExerciseInstance.attachments),
                selectinload(ExerciseInstance.point_checkpoints),
                selectinload(ExerciseInstance.dependencies),
            )
            .where(
                and_(
                    ExerciseInstance.recipe_version_id == recipe_version_id,
                    ExerciseInstance.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    if not instances:
        return None
    return [ExerciseInstanceResponse.model_validate(ei).model_dump(mode="json") for ei in instances]


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
        access_mode=request.access_mode,
        name=request.name,
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

    # 1) Team configuration
    try:
        team_size = _team_size_and_validate(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "team_configuration",
                "message": str(e),
                "code": "TEAM_SIZE_VIOLATION",
            },
        )

    # 2) Recipe version (exists, published, approved)
    await _check_recipe_version(session, request.recipe_version_id)

    # 2a) Ensure recipe is approved (version belongs to a recipe)
    version = await _recipe_repo.get_version_by_id(session, request.recipe_version_id)
    if version is not None and version.recipe_id is not None:
        await _ensure_recipe_approved(
            session, version.recipe_id, context="recipe_id"
        )

    # 2b) Load immutable recipe spec (snapshot) for this version
    recipe_spec = await _recipe_repo.get_snapshot_by_version_id(
        session, request.recipe_version_id
    )
    if recipe_spec is None:
        # This should not happen for a published version; treat as server error.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "recipe_snapshot_missing",
                "message": "No snapshot found for the specified recipe version id.",
            },
        )

    # 3) Redis fast gate (optional; skip if redis not injected)
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
        # 4) Transactional count + insert
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
            team_size=team_size,
            member_ids=request.member_ids,
            name=request.name,
            created_by=created_by,
            access=access_dict,
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
    Resolves recipe_version_id, loads recipe_spec, sets expires_at from duration_hours,
    and stores initiator_user, experience_type, access_mode. provider_profile is a constant (not stored).
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

    # 4) Team: single initiator (team_size=1)
    member_ids = [request.initiator_user]
    constraints.team_configuration.validate_team_size(len(member_ids))
    team_size = 1

    # 5) Load recipe spec (snapshot JSON)
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

    # 6) Redis gate
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
            team_size=team_size,
            member_ids=member_ids,
            name=request.name,
            created_by=request.initiator_user,
            access=access_dict,
            recipe_spec=copy.deepcopy(recipe_spec),
            recipe_id=request.recipe_id,
            experience_type=request.experience_type,
            duration_hours=request.duration_hours,
            access_mode=request.access_mode,
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


def _build_recipe_from_spec(
    recipe_spec: Dict[str, Any],
    recipe_id: Optional[uuid.UUID],
) -> Dict[str, Any]:
    """
    Build recipe-style dict from stored recipe_spec (published snapshot).
    Flattens metadata, adds recipe_id and approval_status, converts gateway
    exposure_rules from unit_id to unit_key for API consistency.
    """
    out: Dict[str, Any] = {
        "recipe_id": str(recipe_id) if recipe_id else None,
        "name": None,
        "description": None,
        "category": None,
        "approval_status": "APPROVED",
        "network_profile": None,
        "domains": [],
        "workload_units": [],
        "gateways": [],
        "jumphost_unit": None,
    }
    meta = recipe_spec.get("metadata") or {}
    out["name"] = meta.get("name")
    out["description"] = meta.get("description")
    out["category"] = meta.get("category")
    out["network_profile"] = copy.deepcopy(recipe_spec.get("network_profile"))
    out["domains"] = copy.deepcopy(recipe_spec.get("domains") or [])
    out["workload_units"] = copy.deepcopy(recipe_spec.get("workload_units") or [])
    out["jumphost_unit"] = copy.deepcopy(recipe_spec.get("jumphost_unit"))

    # unit_id -> unit_key for exposure_rules
    id_to_key: Dict[str, str] = {}
    for w in out["workload_units"]:
        uid = w.get("id")
        if uid is not None:
            id_to_key[str(uid)] = w.get("unit_key") or str(uid)
    gateways_in = recipe_spec.get("gateways") or []
    gateways_out = []
    for gw in gateways_in:
        gw_copy = copy.deepcopy(gw)
        rules = gw_copy.get("exposure_rules") or []
        new_rules = []
        for r in rules:
            uid = r.get("unit_id")
            unit_key = id_to_key.get(str(uid), str(uid) if uid else None)
            new_rules.append({
                "id": r.get("id") or str(uuid.uuid4()),
                "unit_key": unit_key,
                "internal_port": r.get("internal_port"),
                "transport_protocol": r.get("transport_protocol"),
            })
        gw_copy["exposure_rules"] = new_rules
        if "is_active" not in gw_copy:
            gw_copy["is_active"] = True
        gateways_out.append(gw_copy)
    out["gateways"] = gateways_out
    return out


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


def _to_response(
    d: Deployment,
    exercise_instances: Optional[List[ExerciseInstanceResponse]] = None,
) -> DeploymentResponse:
    """Build DeploymentResponse from ORM. recipe_spec has no access_gateway key."""
    access = (
        AccessConfig.model_validate(d.access)
        if isinstance(d.access, dict) and d.access
        else None
    )
    spec = getattr(d, "recipe_spec", None)
    # Return recipe_spec without access_gateway key
    recipe_spec_out = copy.deepcopy(spec) if isinstance(spec, dict) else None
    if recipe_spec_out is not None:
        recipe_spec_out.pop("access_gateway", None)

    recipe_subset = _build_recipe_subset(d)
    # Prefer stored exercises JSONB; else use live exercise_instances
    stored = getattr(d, "exercises", None)
    if isinstance(stored, list) and stored:
        exercises = [
            ExerciseWithRecipeResponse(**item, recipe=recipe_subset)
            for item in stored
        ]
    else:
        exercises = [
            ExerciseWithRecipeResponse(**ei.model_dump(), recipe=recipe_subset)
            for ei in (exercise_instances or [])
        ]

    return DeploymentResponse(
        deployment_id=d.id,
        recipe_version_id=d.recipe_version_id,
        status=d.status,
        expires_at=d.expires_at,
        team_size=d.team_size,
        name=d.name,
        member_ids=d.member_ids or [],
        created_at=d.created_at,
        updated_at=d.updated_at,
        access=access,
        recipe_id=getattr(d, "recipe_id", None),
        experience_type=getattr(d, "experience_type", None),
        duration_hours=getattr(d, "duration_hours", None),
        access_mode=getattr(d, "access_mode", None),
        target_env=getattr(d, "target_env", None),
        recipe_spec=recipe_spec_out,
        exercises=exercises,
        provider_profile=None if getattr(d, "target_env", None) else dict(PROVIDER_PROFILE),
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
    # Load all exercise instances bound to this deployment's recipe_version_id
    instances = (
        await session.execute(
            select(ExerciseInstance)
            .options(
                selectinload(ExerciseInstance.validation_targets),
                selectinload(ExerciseInstance.guidance_steps),
                selectinload(ExerciseInstance.attachments),
                selectinload(ExerciseInstance.point_checkpoints),
                selectinload(ExerciseInstance.dependencies),
            )
            .where(
                and_(
                    ExerciseInstance.recipe_version_id == deployment.recipe_version_id,
                    ExerciseInstance.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    instance_responses = [
        ExerciseInstanceResponse.model_validate(ei) for ei in instances
    ]
    return _to_response(deployment, instance_responses)


async def update_deployment(
    session: AsyncSession,
    deployment_id: uuid.UUID,
    payload: DeploymentUpdateRequest,
) -> DeploymentResponse:
    """Partial update of deployment. Can update name, access, target_env, recipe_spec (deployment JSON), exercises."""
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
    # Recompute exercise instances for the (unchanged) recipe_version_id
    instances = (
        await session.execute(
            select(ExerciseInstance)
            .options(
                selectinload(ExerciseInstance.validation_targets),
                selectinload(ExerciseInstance.guidance_steps),
                selectinload(ExerciseInstance.attachments),
                selectinload(ExerciseInstance.point_checkpoints),
                selectinload(ExerciseInstance.dependencies),
            )
            .where(
                and_(
                    ExerciseInstance.recipe_version_id == updated.recipe_version_id,
                    ExerciseInstance.deleted_at.is_(None),
                )
            )
        )
    ).scalars().all()
    instance_responses = [
        ExerciseInstanceResponse.model_validate(ei) for ei in instances
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
    """List deployments with optional recipe_version_id filter. Returns paginated list (no recipe or exercise_instances)."""
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
            deployment_id=d.id,
            recipe_version_id=d.recipe_version_id,
            status=d.status,
            expires_at=d.expires_at,
            team_size=d.team_size,
            name=d.name,
            member_ids=d.member_ids or [],
            created_at=d.created_at,
            updated_at=d.updated_at,
            recipe_id=getattr(d, "recipe_id", None),
            experience_type=getattr(d, "experience_type", None),
            duration_hours=getattr(d, "duration_hours", None),
            access_mode=getattr(d, "access_mode", None),
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

