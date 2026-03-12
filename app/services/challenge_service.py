from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.challenge import (
    ChallengeCreate,
    ChallengeResponse,
    ChallengeUpdate,
    ChallengeScoringConfig,
    ChallengeScoringResponse,
    ChallengeWithRecipeResponse,
    ObjectiveResponse,
    RecipeSubset,
)
from app.models.challenge import (
    Hint,
    Challenge,
    HealthStatus,
    ValidationTarget,
    Objective,
    ScoringType,
)
from app.models.recipe import Recipe, RecipeVersion
from app.services.approval_service import validate_version_for_challenge


# ─────────────────────────────────────────────────
# Challenge Lifecycle — manages health status transitions
# ─────────────────────────────────────────────────


class ChallengeLifecycle:
    """
    Encapsulates status transition logic for challenges.

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
        return (current, target) in cls._TRANSITIONS

    @classmethod
    def needs_guard(cls, current: HealthStatus, target: HealthStatus) -> bool:
        return cls._TRANSITIONS.get((current, target)) is True

    @classmethod
    def transition(cls, instance: Challenge, new_status_str: str) -> None:
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
                            "Challenge needs >= 1 validation target "
                            "and description >= 20 chars to verify."
                        ),
                    },
                )


# ─────────────────────────────────────────────────
# Challenge Builder — encapsulates creation / update of child entities
# ─────────────────────────────────────────────────


class ChallengeBuilder:
    """
    Assembles a Challenge together with its child entities
    (validation targets, hints, objectives, dependencies).
    """

    @staticmethod
    async def build(
        db: AsyncSession,
        data: ChallengeCreate,
        created_by: uuid.UUID,
    ) -> Challenge:
        """Create a brand-new Challenge from validated schema data."""
        await validate_version_for_challenge(db, data.recipe_version_id)

        if data.dependencies:
            await _detect_dependency_cycle(db, uuid.uuid4(), list(data.dependencies))

        instance = Challenge(
            recipe_version_id=data.recipe_version_id,
            instance_slug=data.instance_slug,
            title=data.title,
            domain_tags=data.domain_tags,
            difficulty=data.difficulty,
            reward_points=data.reward_points,
            health_status=data.health_status,
            description=data.description,
            verification_automation=data.verification_automation,
            scoring_type=data.scoring_type,
            type=data.type,
            progression_mode=data.progression_mode,
            resource_scope=data.resource_scope,
            sub_category=data.sub_category,
            created_by=created_by,
        )

        instance.validation_targets = [
            ValidationTarget(**vt.model_dump()) for vt in data.validation_targets
        ]
        instance.hints = [
            Hint(**h.model_dump()) for h in data.hints
        ]
        instance.objectives = [
            Objective(**o.model_dump()) for o in data.objectives
        ]

        if data.dependencies:
            deps = (
                await db.execute(
                    select(Challenge).where(
                        Challenge.id.in_(list(data.dependencies))
                    )
                )
            ).scalars().all()
            instance.dependencies = deps

        db.add(instance)
        await db.flush()
        await db.refresh(instance)

        if data.sub_category is not None:
            await ChallengeBuilder._propagate_sub_category(db, instance.recipe_version_id, data.sub_category)

        return instance

    @staticmethod
    async def apply_updates(
        db: AsyncSession,
        instance: Challenge,
        data: ChallengeUpdate,
    ) -> Challenge:
        """Merge update fields into an existing challenge."""
        if data.recipe_version_id and data.recipe_version_id != instance.recipe_version_id:
            await validate_version_for_challenge(db, data.recipe_version_id)

        if data.health_status and data.health_status != instance.health_status:
            ChallengeLifecycle.transition(instance, data.health_status)

        if data.dependencies is not None:
            await _detect_dependency_cycle(db, instance.id, list(data.dependencies))

        _apply_scalar_fields(instance, data)

        if data.validation_targets is not None:
            instance.validation_targets = [
                ValidationTarget(**vt.model_dump()) for vt in data.validation_targets
            ]
        if data.hints is not None:
            instance.hints = [
                Hint(**h.model_dump()) for h in data.hints
            ]
        if data.objectives is not None:
            instance.objectives = [
                Objective(**o.model_dump()) for o in data.objectives
            ]
        if data.dependencies is not None:
            deps = (
                await db.execute(
                    select(Challenge).where(
                        Challenge.id.in_(list(data.dependencies))
                    )
                )
            ).scalars().all()
            instance.dependencies = deps

        await db.flush()
        await db.refresh(instance)

        if data.sub_category is not None:
            await ChallengeBuilder._propagate_sub_category(db, instance.recipe_version_id, data.sub_category)

        return instance

    @classmethod
    async def _propagate_sub_category(
        cls, db: AsyncSession, recipe_version_id: uuid.UUID, sub_category: str
    ) -> None:
        from app.models.recipe import RecipeVersionSnapshot
        from app.models.deployment import Deployment
        from sqlalchemy.orm.attributes import flag_modified

        snapshot = (
            await db.execute(
                select(RecipeVersionSnapshot).where(
                    RecipeVersionSnapshot.version_id == recipe_version_id
                )
            )
        ).scalar_one_or_none()

        if snapshot and snapshot.snapshot_json:
            new_json = dict(snapshot.snapshot_json)
            if "metadata" not in new_json:
                new_json["metadata"] = {}
            new_json["metadata"]["sub_category"] = sub_category
            snapshot.snapshot_json = new_json
            flag_modified(snapshot, "snapshot_json")
            db.add(snapshot)

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
    "verification_automation",
    "type",
    "scoring_type",
    "progression_mode",
    "resource_scope",
]


def _apply_scalar_fields(instance: Challenge, data: ChallengeUpdate) -> None:
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
            select(Challenge)
            .options(selectinload(Challenge.dependencies))
            .where(Challenge.id == current_id)
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
        select(Challenge)
        .options(
            selectinload(Challenge.validation_targets),
            selectinload(Challenge.hints),
            selectinload(Challenge.attachments),
            selectinload(Challenge.objectives),
            selectinload(Challenge.dependencies),
        )
        .where(Challenge.deleted_at.is_(None))
    )

    if difficulty:
        q = q.where(Challenge.difficulty.in_(difficulty))
    if health_status:
        q = q.where(Challenge.health_status.in_(health_status))
    if scoring_type:
        q = q.where(Challenge.scoring_type == scoring_type)
    if domain_tags:
        q = q.where(Challenge.domain_tags.overlap(domain_tags))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    sort_col = getattr(Challenge, sort_by, Challenge.created_at)
    if sort_order == "desc":
        q = q.order_by(sort_col.desc())
    else:
        q = q.order_by(sort_col.asc())

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {"rows": rows, "total": total, "page": page, "page_size": page_size}


async def get_instance_by_id(db: AsyncSession, instance_id: uuid.UUID) -> Challenge:
    result = await db.execute(
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
                Challenge.id == instance_id,
                Challenge.deleted_at.is_(None),
            )
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "CHALLENGE_NOT_FOUND",
                "message": "Challenge not found.",
            },
        )
    return instance


async def get_instance_with_recipe(
    db: AsyncSession, instance_id: uuid.UUID
) -> ChallengeWithRecipeResponse:
    """Load a challenge and embed the linked recipe subset."""
    instance = await get_instance_by_id(db, instance_id)

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

    base = ChallengeResponse.model_validate(instance)
    return ChallengeWithRecipeResponse(
        **base.model_dump(),
        recipe=recipe_subset,
    )


async def create_instance(
    db: AsyncSession, data: ChallengeCreate, created_by: uuid.UUID
) -> Challenge:
    return await ChallengeBuilder.build(db, data, created_by)


async def update_instance(
    db: AsyncSession,
    instance_id: uuid.UUID,
    data: ChallengeUpdate,
) -> Challenge:
    instance = await get_instance_by_id(db, instance_id)
    return await ChallengeBuilder.apply_updates(db, instance, data)


async def get_scoring(
    db: AsyncSession,
    instance_id: uuid.UUID,
) -> ChallengeScoringResponse:
    instance = await get_instance_by_id(db, instance_id)
    return ChallengeScoringResponse(
        scoring_type=instance.scoring_type.value
        if hasattr(instance.scoring_type, "value")
        else str(instance.scoring_type),
        reward_points=instance.reward_points,
        objectives=[
            ObjectiveResponse(
                id=o.id,
                goal=o.goal,
                points_impacted=o.points_impacted,
            )
            for o in instance.objectives
        ],
    )


async def configure_scoring(
    db: AsyncSession,
    instance_id: uuid.UUID,
    data: ChallengeScoringConfig,
) -> ChallengeScoringResponse:
    instance = await get_instance_by_id(db, instance_id)

    instance.scoring_type = ScoringType(data.scoring_type)
    instance.reward_points = data.reward_points
    instance.objectives = [
        Objective(goal=o.goal, points_impacted=o.points_impacted)
        for o in data.objectives
    ]

    await db.flush()
    await db.refresh(instance)
    return await get_scoring(db, instance_id)


async def soft_delete_instance(db: AsyncSession, instance_id: uuid.UUID) -> None:
    instance = await get_instance_by_id(db, instance_id)
    instance.deleted_at = datetime.now(timezone.utc)
    await db.flush()
