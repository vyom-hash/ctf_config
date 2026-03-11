"""
Deployment model — references immutable recipe_version only.

Lifecycle: ALLOCATING → RUNNING → TEARING_DOWN → ARCHIVED.
Only RUNNING and ALLOCATING count toward maximum_concurrent_deployments.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class DeploymentStatus:
    ALLOCATING = "ALLOCATING"
    RUNNING = "RUNNING"
    TEARING_DOWN = "TEARING_DOWN"
    ARCHIVED = "ARCHIVED"

    COUNTED_FOR_CONCURRENCY = (ALLOCATING, RUNNING)


class Deployment(Base):
    """
    One deployment instance of a published recipe version.

    - recipe_version_id: references recipe_versions.id (immutable); NOT draft_id.
    - No runtime infra details stored here; orchestrator owns provisioning.
    - expires_at: set at creation (now + auto_expire_minutes); scheduler triggers teardown.
    """
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DeploymentStatus.ALLOCATING
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    member_ids: Mapped[List[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Immutable snapshot of the published recipe version used for this deployment.
    # Contains metadata, network_profile, domains, workload_units, gateways, and recipe_spec.jumphost_unit.
    recipe_spec: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Entry/SSH access config (deployment-level override).
    access: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # When created via from-recipe flow: recipe and deployment params (stored for orchestrator/audit).
    recipe_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        "recipe_draft_id", UUID(as_uuid=True), nullable=True, index=True
    )
    experience_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    duration_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    access_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_env: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Target cloud name (e.g. openstack-dev, aws-prod)"
    )
    # Snapshot of exercise info for this deployment (JSONB list of exercise data).
    exercises: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Optional: if you need to navigate to version (read-only)
    # recipe_version: Mapped["RecipeVersion"] = relationship("RecipeVersion", back_populates="deployments")
