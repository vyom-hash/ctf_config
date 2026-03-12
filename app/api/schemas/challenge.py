from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator


SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,80}$")


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ─────────────────────────────── Flag store (flat structure) ─────────────────

class FlagStore(_Base):
    """Flat flag store config — stored as JSONB in validation_targets."""
    category: str
    location: str
    file_permission: str
    file_owner: str
    file_group: str
    mkdir: bool
    type: str = Field(pattern="^(rewrite|add)$")


# ─────────────────────────────── Validation target ───────────────────────────

class ValidationTargetCreate(_Base):
    label: str = Field(min_length=2, max_length=120)
    flag_template: str = Field(min_length=1)
    custom_evaluator: Optional[str] = None
    target_units: List[str] = Field(default_factory=list)
    flag_store: Optional[FlagStore] = None


class ValidationTargetResponse(ValidationTargetCreate):
    id: UUID4


# ─────────────────────────────── Hint (replaces GuidanceStep) ────────────────

class HintCreate(_Base):
    hint: str = Field(min_length=1)
    points_impacted: int = Field(ge=0)


class HintResponse(HintCreate):
    id: UUID4


# ─────────────────────────────── Objective (replaces PointCheckpoint) ────────

class ObjectiveCreate(_Base):
    goal: str = Field(min_length=1)
    points_impacted: int = Field(ge=1)


class ObjectiveResponse(ObjectiveCreate):
    id: UUID4


# ─────────────────────────────── Scoring config ──────────────────────────────

class ChallengeScoringConfig(_Base):
    """Scoring configuration for a single challenge."""
    scoring_type: str = Field(..., pattern=r"^(flat|decay|milestone)$")
    reward_points: int = Field(..., ge=1, le=5000)
    objectives: List[ObjectiveCreate] = Field(default_factory=list)


class ChallengeScoringResponse(_Base):
    """Current scoring configuration for a challenge."""
    scoring_type: str
    reward_points: int
    objectives: List[ObjectiveResponse] = Field(default_factory=list)


# ─────────────────────────────── Challenge CRUD ──────────────────────────────

class ChallengeCreate(_Base):
    instance_slug: str
    recipe_version_id: UUID4
    title: str = Field(min_length=3, max_length=120)
    domain_tags: List[str] = Field(min_length=1)
    difficulty: str
    reward_points: int = Field(ge=1, le=5000)
    health_status: str = "draft"
    description: str = Field(min_length=20)
    verification_automation: Optional[str] = None
    type: Optional[str] = Field(None, pattern=r"^(jeopardy|guided)$")
    scoring_type: str = "flat"
    progression_mode: Optional[str] = Field(
        None, pattern=r"^(independent|sequential)$"
    )
    resource_scope: str = Field(
        "per_user", pattern=r"^(per_user|per_team|shared)$"
    )
    sub_category: Optional[str] = Field(
        None, pattern=r"^(selfpaced|event)$"
    )
    objectives: List[ObjectiveCreate] = Field(default_factory=list)
    validation_targets: List[ValidationTargetCreate] = Field(default_factory=list)
    hints: List[HintCreate] = Field(default_factory=list)
    dependencies: List[UUID4] = Field(default_factory=list)

    @field_validator("instance_slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                "Slug must be lowercase alphanumeric and hyphens only, max 80 chars"
            )
        return v

    @field_validator("domain_tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        if len(v) < 1:
            raise ValueError("At least one domain tag is required")
        return v


class ChallengeUpdate(_Base):
    instance_slug: Optional[str] = None
    recipe_version_id: Optional[UUID4] = None
    title: Optional[str] = None
    domain_tags: Optional[List[str]] = None
    difficulty: Optional[str] = None
    reward_points: Optional[int] = None
    health_status: Optional[str] = None
    description: Optional[str] = None
    verification_automation: Optional[str] = None
    type: Optional[str] = Field(None, pattern=r"^(jeopardy|guided)$")
    scoring_type: Optional[str] = None
    objectives: Optional[List[ObjectiveCreate]] = None
    validation_targets: Optional[List[ValidationTargetCreate]] = None
    hints: Optional[List[HintCreate]] = None
    dependencies: Optional[List[UUID4]] = None
    progression_mode: Optional[str] = Field(
        None, pattern=r"^(independent|sequential)$"
    )
    resource_scope: Optional[str] = Field(
        None, pattern=r"^(per_user|per_team|shared)$"
    )
    sub_category: Optional[str] = Field(
        None, pattern=r"^(selfpaced|event)$"
    )

    @field_validator("instance_slug")
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        if v and not SLUG_PATTERN.match(v):
            raise ValueError("Invalid slug format")
        return v


class ChallengeResponse(_Base):
    """Full challenge response (CRUD endpoints)."""
    id: UUID4
    recipe_version_id: UUID4
    instance_slug: str
    title: str
    domain_tags: List[str]
    difficulty: str
    reward_points: int
    health_status: str
    description: str
    verification_automation: Optional[str]
    type: Optional[str]
    scoring_type: str
    progression_mode: Optional[str]
    resource_scope: str
    sub_category: Optional[str]
    created_by: uuid.UUID
    reviewed_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    validation_targets: List[ValidationTargetResponse] = Field(default_factory=list)
    hints: List[HintResponse] = Field(default_factory=list)
    attachments: List["ChallengeAttachmentResponse"] = Field(default_factory=list)
    objectives: List[ObjectiveResponse] = Field(default_factory=list)
    dependencies: List[UUID4] = Field(default_factory=list)


class ChallengeAttachmentResponse(_Base):
    id: UUID4
    filename: str
    sha256: str
    size_bytes: int
    visibility: str


# ─────────────────────────────── Recipe subset (embedded) ────────────────────

class RecipeSubset(_Base):
    """Minimal recipe metadata embedded inside each challenge response."""
    recipe_id: Optional[UUID4] = None
    name: str
    category: Optional[str] = None
    version_number: int
    recipe_version_id: UUID4


class ChallengeWithRecipeResponse(ChallengeResponse):
    """Challenge (superset) with embedded recipe details as a subset."""
    recipe: Optional[RecipeSubset] = None


# ─────────────────────────────── Deployment challenge response ───────────────

class FlagResponse(_Base):
    """Flag data derived from first validation target."""
    label: str
    flag_template: str
    custom_evaluator: Optional[str] = None
    target_units: List[str] = Field(default_factory=list)


class DeploymentHintResponse(_Base):
    """Hint entry in deployment challenge_specs — no id."""
    hint: str
    points_impacted: int


class DeploymentMilestoneResponse(_Base):
    """Milestone (objective) entry in deployment challenge_specs — no id."""
    goal: str
    points_impacted: int


class DeploymentChallengeResponse(_Base):
    """Challenge entry in deployment challenge_specs."""
    id: uuid.UUID
    type: Optional[str] = None
    flag_template: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    flag_store: Optional[FlagStore] = None
    target_units: List[str] = Field(default_factory=list)
    title: str
    points: int
    level: str
    description: str
    verification_automation: Optional[str] = None
    hints: List[DeploymentHintResponse] = Field(default_factory=list)
    objectives: List[DeploymentMilestoneResponse] = Field(default_factory=list)


class PaginatedChallengeResponse(_Base):
    data: List[ChallengeResponse]
    meta: Dict[str, int]
