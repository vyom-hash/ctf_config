import enum
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Difficulty(str, enum.Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class HealthStatus(str, enum.Enum):
    draft = "draft"
    verified = "verified"
    degraded = "degraded"
    retired = "retired"


class ScoringType(str, enum.Enum):
    flat = "flat"
    decay = "decay"
    milestone = "milestone"


class AttachmentVisibility(str, enum.Enum):
    public = "public"
    on_solve = "on_solve"


challenge_dependencies = Table(
    "challenge_dependencies",
    Base.metadata,
    Column(
        "instance_id",
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        primary_key=True,
    ),
    Column(
        "prerequisite_id",
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        primary_key=True,
    ),
)


class Challenge(Base):
    __tablename__ = "challenges"
    __table_args__ = (
        Index("ix_ei_slug", "instance_slug"),
        Index("ix_ei_health_status", "health_status"),
        Index("ix_ei_difficulty", "difficulty"),
        Index("ix_ei_deleted_at", "deleted_at"),
        Index("ix_ei_created_by", "created_by"),
        Index("ix_ei_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    instance_slug: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    domain_tags: Mapped[List[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty), nullable=False
    )
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    health_status: Mapped[HealthStatus] = mapped_column(
        SAEnum(HealthStatus), nullable=False, default=HealthStatus.draft
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # verification_automation: name of the verification script (renamed from lab_environment_ref)
    verification_automation: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # type: jeopardy or guided (replaced experience_mode)
    type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    progression_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_scope: Mapped[str] = mapped_column(
        String(50), nullable=False, default="per_user"
    )
    sub_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scoring_type: Mapped[ScoringType] = mapped_column(
        SAEnum(ScoringType), nullable=False, default=ScoringType.flat
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    validation_targets: Mapped[List["ValidationTarget"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    hints: Mapped[List["Hint"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attachments: Mapped[List["ChallengeAttachment"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    objectives: Mapped[List["Objective"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    dependencies: Mapped[List["Challenge"]] = relationship(
        "Challenge",
        secondary=challenge_dependencies,
        primaryjoin="Challenge.id == challenge_dependencies.c.instance_id",
        secondaryjoin="Challenge.id == challenge_dependencies.c.prerequisite_id",
        lazy="selectin",
    )


class ValidationTarget(Base):
    __tablename__ = "validation_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    flag_template: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_evaluator: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_units: Mapped[List[str]] = mapped_column(ARRAY(String(100)), nullable=False, default=list)
    flag_store: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        nullable=False,
    )
    instance: Mapped[Challenge] = relationship(
        back_populates="validation_targets"
    )


class Hint(Base):
    """Replaces GuidanceStep — simplified structure with hint text and points_impacted."""
    __tablename__ = "hints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hint: Mapped[str] = mapped_column(Text, nullable=False)
    points_impacted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        nullable=False,
    )
    instance: Mapped[Challenge] = relationship(
        back_populates="hints"
    )


class ChallengeAttachment(Base):
    __tablename__ = "challenge_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    visibility: Mapped[AttachmentVisibility] = mapped_column(
        SAEnum(AttachmentVisibility),
        nullable=False,
        default=AttachmentVisibility.public,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        nullable=False,
    )
    instance: Mapped[Challenge] = relationship(back_populates="attachments")


class Objective(Base):
    """Replaces PointCheckpoint — goal with points_impacted."""
    __tablename__ = "objectives"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    goal: Mapped[str] = mapped_column(String(120), nullable=False)
    points_impacted: Mapped[int] = mapped_column(Integer, nullable=False)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        nullable=False,
    )
    instance: Mapped[Challenge] = relationship(back_populates="objectives")
