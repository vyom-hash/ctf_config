from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.exercise_instance import (
    ExerciseInstanceCreate,
    ExerciseInstanceResponse,
    ExerciseInstanceUpdate,
    ExerciseScoringConfig,
    ExerciseScoringResponse,
    ExerciseWithRecipeResponse,
    PointCheckpointResponse,
    RecipeSubset,
)
from app.models.exercise_instance import (
    GuidanceStep,
    ExerciseInstance,
    HealthStatus,
    ValidationTarget,
    PointCheckpoint,
    ScoringType,
)
from app.models.recipe import Recipe, RecipeVersion
from app.services.approval_service import validate_version_for_exercise_instance


# ─────────────────────────────────────────────────
# Exercise Lifecycle — manages health status transitions
# ─────────────────────────────────────────────────


class ExerciseLifecycle:
    """
    Encapsulates status transition logic for exercise instances.

    Transition graph:
        draft → verified (requires validation guard)
        verified → degraded
        degraded → verified
        draft → retired
        verified → retired
        degraded → retired
        retired → draft
    """

    _TRANSITIONS = {
        (HealthStatus.draft, HealthStatus.verified): True,
        (HealthStatus.verified, HealthStatus.degraded): False,
        (HealthStatus.degraded, HealthStatus.verified): False,
        (HealthStatus.draft, HealthStatus.retired): False,
        (HealthStatus.verified, HealthStatus.retired): False,
        (HealthStatus.degraded, HealthStatus.retired): False,
        (HealthStatus.retired, HealthStatus.draft): False,
    }

    @classmethod
    def can_transition(cls, current: HealthStatus, target: HealthStatus) -> bool:
        """Check whether the transition is allowed."""
        return (current, target) in cls._TRANSITIONS

    @classmethod
    def needs_guard(cls, current: HealthStatus, target: HealthStatus) -> bool:
        """Return True when a pre-condition guard must be evaluated."""
        return cls._TRANSITIONS.get((current, target)) is True

    @classmethod
    def transition(cls, instance: ExerciseInstance, new_status_str: str) -> None:
        """
        Apply a health-status transition, raising on invalid moves
        or unmet guards.
        """
        current = HealthStatus(instance.health_status)
        target = HealthStatus(new_status_str)

        if not cls.can_transition(current, target):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "INVALID_HEALTH_TRANSITION",
                    "message": f"Cannot transition from {current} to {target}.",
                },
            )

        if cls.needs_guard(current, target):
            if (
                not instance.validation_targets
                or len(instance.description or "") < 20
            ):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "VERIFY_GUARD_FAILED",
                        "message": (
                            "Instance needs >= 1 validation target "
                            "and description >= 20 chars to verify."
                        ),
                    },
                )


# ─────────────────────────────────────────────────
# Exercise Builder — encapsulates creation / update of child entities
# ─────────────────────────────────────────────────


class ExerciseBuilder:
    """
    Assembles an ExerciseInstance together with its child entities
    (validation targets, guidance steps, point checkpoints, dependencies).
    """

    @staticmethod
    async def build(
        db: AsyncSession,
        data: ExerciseInstanceCreate,
        created_by: uuid.UUID,
    ) -> ExerciseInstance:
        """Create a brand-new ExerciseInstance from validated schema data."""

        # Ensure the referenced recipe version is published, approved, and latest.
        await validate_version_for_exercise_instance(db, data.recipe_version_id)

        if data.dependencies:
            await _detect_dependency_cycle(db, uuid.uuid4(), list(data.dependencies))

        instance = ExerciseInstance(
            recipe_version_id=data.recipe_version_id,
            instance_slug=data.instance_slug,
            title=data.title,
            domain_tags=data.domain_tags,
            difficulty=data.difficulty,
            reward_points=data.reward_points,
            health_status=data.health_status,
            description=data.description,
            lab_environment_ref=data.lab_environment_ref,
            scoring_type=data.scoring_type,
            experience_mode=data.experience_mode,
            progression_mode=data.progression_mode,
            resource_scope=data.resource_scope,
            sub_category=data.sub_category,
            created_by=created_by,
        )

        instance.validation_targets = [
            ValidationTarget(**vt.model_dump()) for vt in data.validation_targets
        ]
        instance.guidance_steps = [
            GuidanceStep(**gs.model_dump()) for gs in data.guidance_steps
        ]
        instance.point_checkpoints = [
            PointCheckpoint(**pc.model_dump()) for pc in data.point_checkpoints
        ]

        if data.dependencies:
            deps = (
                await db.execute(
                    select(ExerciseInstance).where(
                        ExerciseInstance.id.in_(list(data.dependencies))
                    )
                )
            ).scalars().all()
            instance.dependencies = deps

        db.add(instance)
        await db.flush()
        await db.refresh(instance)

        if data.sub_category is not None:
            await ExerciseBuilder._propagate_sub_category(db, instance.recipe_version_id, data.sub_category)

        return instance

    @staticmethod
    async def apply_updates(
        db: AsyncSession,
        instance: ExerciseInstance,
        data: ExerciseInstanceUpdate,
    ) -> ExerciseInstance:
        """Merge update fields into an existing instance."""

        if data.recipe_version_id and data.recipe_version_id != instance.recipe_version_id:
            await validate_version_for_exercise_instance(db, data.recipe_version_id)

        if data.health_status and data.health_status != instance.health_status:
            ExerciseLifecycle.transition(instance, data.health_status)

        if data.dependencies is not None:
            await _detect_dependency_cycle(db, instance.id, list(data.dependencies))

        # Apply scalar field updates
        _apply_scalar_fields(instance, data)

        # Merge child collections (replace-if-provided)
        if data.validation_targets is not None:
            instance.validation_targets = [
                ValidationTarget(**vt.model_dump()) for vt in data.validation_targets
            ]
        if data.guidance_steps is not None:
            instance.guidance_steps = [
                GuidanceStep(**gs.model_dump()) for gs in data.guidance_steps
            ]
        if data.point_checkpoints is not None:
            instance.point_checkpoints = [
                PointCheckpoint(**pc.model_dump()) for pc in data.point_checkpoints
            ]
        if data.dependencies is not None:
            deps = (
                await db.execute(
                    select(ExerciseInstance).where(
                        ExerciseInstance.id.in_(list(data.dependencies))
                    )
                )
            ).scalars().all()
            instance.dependencies = deps

        await db.flush()
        await db.refresh(instance)

        if data.sub_category is not None:
            await ExerciseBuilder._propagate_sub_category(db, instance.recipe_version_id, data.sub_category)

        return instance

    @classmethod
    async def _propagate_sub_category(
        cls, db: AsyncSession, recipe_version_id: uuid.UUID, sub_category: str
    ) -> None:
        """
        Propagate the sub_category to the RecipeVersionSnapshot metadata and
        any Deployments that were instantiated from this recipe version.
        """
        from app.models.recipe import RecipeVersionSnapshot
        from app.models.deployment import Deployment
        from sqlalchemy import update

        # 1. Update the RecipeVersionSnapshot JSON
        snapshot = (
            await db.execute(
                select(RecipeVersionSnapshot).where(
                    RecipeVersionSnapshot.version_id == recipe_version_id
                )
            )
        ).scalar_one_or_none()

        if snapshot and snapshot.snapshot_json:
            # We must create a new dict to trigger SQLAlchemy JSONB mutation detection
            new_json = dict(snapshot.snapshot_json)
            if "metadata" not in new_json:
                new_json["metadata"] = {}
            new_json["metadata"]["sub_category"] = sub_category
            snapshot.snapshot_json = new_json

            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(snapshot, "snapshot_json")
            db.add(snapshot)

        # 2. Update existing Deployments
        deployments = (
            await db.execute(
                select(Deployment).where(Deployment.recipe_version_id == recipe_version_id)
            )
        ).scalars().all()

        for dep in deployments:
            if dep.recipe_spec:
                new_spec = dict(dep.recipe_spec)
                if "metadata" not in new_spec:
                    new_spec["metadata"] = {}
                new_spec["metadata"]["sub_category"] = sub_category
                dep.recipe_spec = new_spec
                flag_modified(dep, "recipe_spec")
                db.add(dep)

        await db.flush()


# ─────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────

_SCALAR_FIELDS = [
    "instance_slug",
    "title",
    "domain_tags",
    "difficulty",
    "reward_points",
    "health_status",
    "description",
    "lab_environment_ref",
    "scoring_type",
    "experience_mode",
    "progression_mode",
    "resource_scope",
]


def _apply_scalar_fields(instance: ExerciseInstance, data: ExerciseInstanceUpdate) -> None:
    """Copy non-None scalar fields from *data* onto *instance*."""
    for field in _SCALAR_FIELDS:
        val = getattr(data, field, None)
        if val is not None:
            setattr(instance, field, val)


async def _detect_dependency_cycle(
    db: AsyncSession,
    instance_id: uuid.UUID,
    new_dep_ids: List[uuid.UUID],
) -> None:
    visited: set[uuid.UUID] = set()
    queue: List[uuid.UUID] = list(new_dep_ids)

    while queue:
        current_id = queue.pop(0)
        if current_id == instance_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "CIRCULAR_DEPENDENCY",
                    "message": "Dependency chain would create a circular dependency.",
                },
            )
        if current_id in visited:
            continue
        visited.add(current_id)

        result = await db.execute(
            select(ExerciseInstance)
            .options(selectinload(ExerciseInstance.dependencies))
            .where(ExerciseInstance.id == current_id)
        )
        row = result.scalar_one_or_none()
        if row:
            queue.extend([p.id for p in row.dependencies])


# ─────────────────────────────────────────────────
# Public service functions (called by router)
# ─────────────────────────────────────────────────


async def get_instances(
    db: AsyncSession,
    difficulty: List[str] | None = None,
    health_status: List[str] | None = None,
    domain_tags: List[str] | None = None,
    scoring_type: str | None = None,
    page: int = 1,
    page_size: int = 12,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> Dict[str, Any]:
    q = (
        select(ExerciseInstance)
        .options(
            selectinload(ExerciseInstance.validation_targets),
            selectinload(ExerciseInstance.guidance_steps),
            selectinload(ExerciseInstance.attachments),
            selectinload(ExerciseInstance.point_checkpoints),
            selectinload(ExerciseInstance.dependencies),
        )
        .where(ExerciseInstance.deleted_at.is_(None))
    )

    if difficulty:
        q = q.where(ExerciseInstance.difficulty.in_(difficulty))
    if health_status:
        q = q.where(ExerciseInstance.health_status.in_(health_status))
    if scoring_type:
        q = q.where(ExerciseInstance.scoring_type == scoring_type)
    if domain_tags:
        q = q.where(ExerciseInstance.domain_tags.overlap(domain_tags))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    sort_col = getattr(ExerciseInstance, sort_by, ExerciseInstance.created_at)
    if sort_order == "desc":
        q = q.order_by(sort_col.desc())
    else:
        q = q.order_by(sort_col.asc())

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {"rows": rows, "total": total, "page": page, "page_size": page_size}


async def get_instance_by_id(db: AsyncSession, instance_id: uuid.UUID) -> ExerciseInstance:
    result = await db.execute(
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
                ExerciseInstance.id == instance_id,
                ExerciseInstance.deleted_at.is_(None),
            )
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "INSTANCE_NOT_FOUND",
                "message": "Exercise instance not found.",
            },
        )
    return instance


async def get_instance_with_recipe(
    db: AsyncSession, instance_id: uuid.UUID
) -> ExerciseWithRecipeResponse:
    """Load an exercise instance and embed the linked recipe subset."""
    instance = await get_instance_by_id(db, instance_id)

    # Look up RecipeVersion → Recipe to build the recipe subset
    version_result = await db.execute(
        select(RecipeVersion).where(RecipeVersion.id == instance.recipe_version_id)
    )
    version = version_result.scalar_one_or_none()

    recipe_subset = None
    if version and version.recipe_id:
        recipe_result = await db.execute(
            select(Recipe).where(Recipe.id == version.recipe_id)
        )
        recipe = recipe_result.scalar_one_or_none()
        if recipe:
            recipe_subset = RecipeSubset(
                recipe_id=recipe.id,
                name=recipe.name,
                category=recipe.category,
                version_number=version.version_number,
                recipe_version_id=version.id,
            )

    base = ExerciseInstanceResponse.model_validate(instance)
    return ExerciseWithRecipeResponse(
        **base.model_dump(),
        recipe=recipe_subset,
    )


async def create_instance(
    db: AsyncSession, data: ExerciseInstanceCreate, created_by: uuid.UUID
) -> ExerciseInstance:
    """Delegate to ExerciseBuilder for construction."""
    return await ExerciseBuilder.build(db, data, created_by)


async def update_instance(
    db: AsyncSession,
    instance_id: uuid.UUID,
    data: ExerciseInstanceUpdate,
) -> ExerciseInstance:
    """Delegate to ExerciseBuilder for merge-based updates."""
    instance = await get_instance_by_id(db, instance_id)
    return await ExerciseBuilder.apply_updates(db, instance, data)


async def get_scoring(
    db: AsyncSession,
    instance_id: uuid.UUID,
) -> ExerciseScoringResponse:
    """Return scoring configuration (type, reward_points, point_checkpoints) for an instance."""
    instance = await get_instance_by_id(db, instance_id)
    return ExerciseScoringResponse(
        scoring_type=instance.scoring_type.value
        if hasattr(instance.scoring_type, "value")
        else str(instance.scoring_type),
        reward_points=instance.reward_points,
        point_checkpoints=[
            PointCheckpointResponse(
                id=pc.id,
                label=pc.label,
                points=pc.points,
            )
            for pc in instance.point_checkpoints
        ],
    )


async def configure_scoring(
    db: AsyncSession,
    instance_id: uuid.UUID,
    data: ExerciseScoringConfig,
) -> ExerciseScoringResponse:
    """Set scoring configuration (type, reward_points, point_checkpoints) for an instance."""
    instance = await get_instance_by_id(db, instance_id)

    # Update scalar fields
    instance.scoring_type = ScoringType(data.scoring_type)
    instance.reward_points = data.reward_points

    # Replace point checkpoints
    instance.point_checkpoints = [
        PointCheckpoint(label=pc.label, points=pc.points)
        for pc in data.point_checkpoints
    ]

    await db.flush()
    await db.refresh(instance)
    return await get_scoring(db, instance_id)


async def soft_delete_instance(db: AsyncSession, instance_id: uuid.UUID) -> None:
    instance = await get_instance_by_id(db, instance_id)
    instance.deleted_at = datetime.now(timezone.utc)
    await db.flush()
