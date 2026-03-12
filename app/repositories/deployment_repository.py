"""
Deployment repository — count (RUNNING + ALLOCATING) and insert.

Used for concurrency enforcement and creation; no recipe mutation.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deployment import Deployment, DeploymentStatus


class DeploymentRepository:
    """Data access for deployments."""

    async def acquire_deployment_lock(self, session: AsyncSession) -> None:
        """Acquire a transaction-level advisory lock for deployment creation."""
        # Use a deterministic 64-bit integer for the global deployment lock
        lock_id = 42424242
        await session.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))

    async def count_running_and_allocating(self, session: AsyncSession) -> int:
        """Count deployments that contribute to maximum_concurrent_deployments."""
        result = await session.execute(
            select(func.count(Deployment.id)).where(
                Deployment.status.in_(DeploymentStatus.COUNTED_FOR_CONCURRENCY)
            )
        )
        return result.scalar_one() or 0

    async def create(
        self,
        session: AsyncSession,
        *,
        recipe_version_id: uuid.UUID,
        status: str,
        expires_at: datetime,
        team_size: int,
        participant_id: Optional[uuid.UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        created_by: Optional[uuid.UUID] = None,
        access: Optional[dict[str, Any]] = None,
        access_method: Optional[str] = None,
        recipe_spec: Optional[dict[str, Any]] = None,
        recipe_id: Optional[uuid.UUID] = None,
        experience_type: Optional[str] = None,
        duration_hours: Optional[int] = None,
        target_env: Optional[str] = None,
        exercises: Optional[list[dict[str, Any]]] = None,
    ) -> Deployment:
        """Insert one deployment; caller must enforce concurrency limit."""
        deployment = Deployment(
            recipe_version_id=recipe_version_id,
            status=status,
            expires_at=expires_at,
            team_size=team_size,
            participant_id=participant_id,
            name=name,
            description=description,
            created_by=created_by,
            access=access,
            access_method=access_method,
            recipe_spec=recipe_spec,
            recipe_id=recipe_id,
            experience_type=experience_type,
            duration_hours=duration_hours,
            target_env=target_env,
            exercises=exercises,
        )
        session.add(deployment)
        await session.flush()
        await session.refresh(deployment)
        return deployment

    async def update(
        self,
        session: AsyncSession,
        deployment_id: uuid.UUID,
        updates: dict[str, Any],
    ) -> Optional[Deployment]:
        """Partial update. Keys: name, access, target_env, recipe_spec, exercises. None clears the field."""
        allowed = {"name", "access", "target_env", "recipe_spec", "exercises"}
        values = {k: v for k, v in updates.items() if k in allowed}
        if not values:
            return await self.get_by_id(session, deployment_id)
        stmt = (
            update(Deployment)
            .where(Deployment.id == deployment_id)
            .values(**values)
        )
        await session.execute(stmt)
        await session.flush()
        return await self.get_by_id(session, deployment_id)

    async def get_by_id(
        self, session: AsyncSession, deployment_id: uuid.UUID
    ) -> Optional[Deployment]:
        """Fetch deployment by primary key."""
        result = await session.execute(
            select(Deployment).where(Deployment.id == deployment_id)
        )
        return result.scalar_one_or_none()

    async def delete_by_id(
        self, session: AsyncSession, deployment_id: uuid.UUID
    ) -> bool:
        """Delete deployment by primary key. Returns True if a row was deleted."""
        stmt = delete(Deployment).where(Deployment.id == deployment_id)
        result = await session.execute(stmt)
        return result.rowcount > 0

    async def count_by_recipe_version_ids(
        self, session: AsyncSession, version_ids: list[uuid.UUID]
    ) -> int:
        """Count deployments that reference any of the given recipe version IDs."""
        if not version_ids:
            return 0
        result = await session.execute(
            select(func.count(Deployment.id)).where(
                Deployment.recipe_version_id.in_(version_ids)
            )
        )
        return result.scalar_one() or 0

    async def list_deployments(
        self,
        session: AsyncSession,
        *,
        recipe_version_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """List deployments with optional recipe_version_id filter; returns rows and total."""
        q = select(Deployment)
        if recipe_version_id is not None:
            q = q.where(Deployment.recipe_version_id == recipe_version_id)
        count_q = select(func.count()).select_from(q.subquery())
        total = (await session.execute(count_q)).scalar_one() or 0
        sort_col = getattr(Deployment, sort_by, Deployment.created_at)
        if sort_order == "desc":
            q = q.order_by(sort_col.desc())
        else:
            q = q.order_by(sort_col.asc())
        q = q.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(q)).scalars().all()
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}
