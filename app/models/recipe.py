"""
SQLAlchemy 2.0 ORM models — mapped 1-to-1 to the provided DDL.

Design decision
───────────────
`recipe_drafts.id` and the corresponding `recipes.id` share the **same UUID**.
When a draft is first created we insert both rows with identical PKs.  This
lets every detail table (`recipe_network_profiles`, etc.) reference
`recipe_id` without an extra join to a draft pivot table.

On `publish`:
  1. Snapshot the current `recipe` + all child tables as JSONB.
  2. Insert a `recipe_versions` row (draft_id → recipe_drafts.id).
  3. Insert `recipe_version_snapshots` with the JSON blob.
  4. Increment `recipes.version`.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


# ─────────────────────────────── Approval status constants ───────────────────

class ApprovalStatus:
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ─────────────────────────────── Draft registry ──────────────────────────────

class RecipeDraft(Base):
    __tablename__ = "recipe_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    approval_status: Mapped[str] = mapped_column(String(50), nullable=False, default=ApprovalStatus.DRAFT, server_default=ApprovalStatus.DRAFT)


# ─────────────────────────────── Published recipe ────────────────────────────

class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    approval_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ApprovalStatus.DRAFT, server_default=ApprovalStatus.DRAFT
    )
    enable_jumphost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    jumphost_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ── child relationships ──────────────────────────────────────────────────
    network_profiles: Mapped[List["RecipeNetworkProfile"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    network_domains: Mapped[List["RecipeNetworkDomain"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    domain_routing_rules: Mapped[List["RecipeDomainRoutingRule"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    dns_resolvers: Mapped[List["RecipeDnsResolver"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    workload_units: Mapped[List["RecipeWorkloadUnit"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    challenges: Mapped[List["RecipeChallenge"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    scoring_rules: Mapped[Optional["RecipeScoringRules"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", uselist=False
    )
    access_gateways: Mapped[List["RecipeAccessGateway"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )


# ─────────────────────────────── Versioning ──────────────────────────────────

class RecipeVersion(Base):
    __tablename__ = "recipe_versions"
    __table_args__ = (UniqueConstraint("recipe_id", "version_number", name="uq_recipe_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id")
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(50), nullable=False, default=ApprovalStatus.APPROVED, server_default=ApprovalStatus.APPROVED)

    snapshot: Mapped[Optional["RecipeVersionSnapshot"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", uselist=False
    )


class RecipeVersionSnapshot(Base):
    __tablename__ = "recipe_version_snapshots"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_versions.id"), primary_key=True
    )
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    version: Mapped["RecipeVersion"] = relationship(back_populates="snapshot")


# ─────────────────────────────── Network layer ───────────────────────────────

class RecipeNetworkProfile(Base):
    """
    Stores global_domain config: gateway_offset and dns_resolvers (via RecipeDnsResolver).
    segmentation_strategy and default_subnet_mask removed.
    """
    __tablename__ = "recipe_network_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    gateway_offset: Mapped[int] = mapped_column(Integer, nullable=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="network_profiles")


class RecipeNetworkDomain(Base):
    __tablename__ = "recipe_network_domains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    enable_egress: Mapped[bool] = mapped_column(Boolean, default=False)
    domain_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    recipe: Mapped["Recipe"] = relationship(back_populates="network_domains")


class RecipeDomainRoutingRule(Base):
    __tablename__ = "recipe_domain_routing_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    source_domain: Mapped[Optional[str]] = mapped_column(String(100))
    destination_domain: Mapped[Optional[str]] = mapped_column(String(100))
    routing_policy: Mapped[Optional[str]] = mapped_column(String(50))

    recipe: Mapped["Recipe"] = relationship(back_populates="domain_routing_rules")


class RecipeDnsResolver(Base):
    __tablename__ = "recipe_dns_resolvers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    resolver_address: Mapped[str] = mapped_column(String(100), nullable=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="dns_resolvers")


# ─────────────────────────────── Workload layer ──────────────────────────────

class RecipeWorkloadUnit(Base):
    __tablename__ = "recipe_workload_units"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    allocation_index: Mapped[Optional[int]] = mapped_column(Integer)
    runtime_profile: Mapped[Optional[str]] = mapped_column(String(150))
    resource_tier: Mapped[Optional[str]] = mapped_column(String(100))
    assigned_domain: Mapped[Optional[str]] = mapped_column(String(100))
    access_method: Mapped[Optional[str]] = mapped_column(String(100))
    unit_control_active: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="workload_units")
    automation_profile: Mapped[Optional["RecipeAutomationProfile"]] = relationship(
        back_populates="workload_unit", cascade="all, delete-orphan", uselist=False
    )
    challenge_links: Mapped[List["RecipeChallengeUnitLink"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )


class RecipeAutomationProfile(Base):
    __tablename__ = "recipe_automation_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workload_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_workload_units.id", ondelete="CASCADE")
    )
    bootstrap_automation: Mapped[Optional[str]] = mapped_column(Text)
    preflight_automation: Mapped[Optional[str]] = mapped_column(Text)
    heartbeat_automation: Mapped[Optional[str]] = mapped_column(Text)

    workload_unit: Mapped["RecipeWorkloadUnit"] = relationship(back_populates="automation_profile")


# ─────────────────────────────── Challenge layer ─────────────────────────────

class RecipeChallenge(Base):
    __tablename__ = "recipe_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    challenge_key: Mapped[Optional[str]] = mapped_column(String(100))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    flag_validation_type: Mapped[Optional[str]] = mapped_column(String(50))
    difficulty: Mapped[Optional[str]] = mapped_column(String(50))
    base_score: Mapped[Optional[int]] = mapped_column(Integer)
    flag_pattern: Mapped[Optional[str]] = mapped_column(Text)

    recipe: Mapped["Recipe"] = relationship(back_populates="challenges")
    unit_links: Mapped[List["RecipeChallengeUnitLink"]] = relationship(
        back_populates="challenge", cascade="all, delete-orphan"
    )
    hints: Mapped[List["RecipeChallengeHint"]] = relationship(
        back_populates="challenge", cascade="all, delete-orphan"
    )


class RecipeChallengeUnitLink(Base):
    __tablename__ = "recipe_challenge_unit_links"

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_challenges.id", ondelete="CASCADE"), primary_key=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_workload_units.id", ondelete="CASCADE"), primary_key=True
    )

    challenge: Mapped["RecipeChallenge"] = relationship(back_populates="unit_links")
    unit: Mapped["RecipeWorkloadUnit"] = relationship(back_populates="challenge_links")


class RecipeChallengeHint(Base):
    __tablename__ = "recipe_challenge_hints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_challenges.id", ondelete="CASCADE")
    )
    hint_text: Mapped[Optional[str]] = mapped_column(Text)
    penalty_points: Mapped[Optional[int]] = mapped_column(Integer)
    display_order: Mapped[Optional[int]] = mapped_column(Integer)

    challenge: Mapped["RecipeChallenge"] = relationship(back_populates="hints")


# ─────────────────────────────── Scoring ─────────────────────────────────────

class RecipeScoringRules(Base):
    __tablename__ = "recipe_scoring_rules"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    dynamic_scoring: Mapped[bool] = mapped_column(Boolean, default=False)
    minimum_score_floor: Mapped[Optional[int]] = mapped_column(Integer)
    decay_strategy: Mapped[Optional[str]] = mapped_column(String(100))

    recipe: Mapped["Recipe"] = relationship(back_populates="scoring_rules")


# ─────────────────────────────── Gateway layer ───────────────────────────────

class RecipeAccessGateway(Base):
    __tablename__ = "recipe_access_gateways"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    gateway_key: Mapped[str] = mapped_column(String(100), nullable=False)
    gateway_type: Mapped[Optional[str]] = mapped_column(String(100))
    runtime_profile: Mapped[Optional[str]] = mapped_column(String(150))
    resource_tier: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    secure_shell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    egress_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="access_gateways")
    exposure_rules: Mapped[List["RecipeGatewayExposureRule"]] = relationship(
        back_populates="gateway", cascade="all, delete-orphan"
    )


class RecipeGatewayExposureRule(Base):
    __tablename__ = "recipe_gateway_exposure_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gateway_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_access_gateways.id")
    )
    wl_unit: Mapped[Optional[str]] = mapped_column(String(100))
    int_port: Mapped[Optional[int]] = mapped_column(Integer)
    proto: Mapped[Optional[str]] = mapped_column(String(20))
    rule_name: Mapped[Optional[str]] = mapped_column(String(100))
    rule_desc: Mapped[Optional[str]] = mapped_column(Text)
    ext_port: Mapped[Optional[int]] = mapped_column(Integer)

    gateway: Mapped["RecipeAccessGateway"] = relationship(back_populates="exposure_rules")


# ─────────────────────────────── Approval audit trail ────────────────────────

class RecipeApproval(Base):
    """
    Immutable audit record created each time a reviewer acts on a recipe.

    recipe_id references recipes(id) ON DELETE CASCADE.
    """
    __tablename__ = "recipe_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
