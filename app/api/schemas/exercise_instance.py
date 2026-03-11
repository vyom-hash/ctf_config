from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator


SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,80}$")


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ValidationTargetCreate(_Base):
    label: str = Field(min_length=2, max_length=120)
    flag_template: str = Field(min_length=1)
    custom_evaluator: Optional[str] = None
    target_units: List[str] = Field(default_factory=list)


class ValidationTargetResponse(ValidationTargetCreate):
    id: UUID4


class GuidanceStepCreate(_Base):
    order: int = Field(ge=1)
    type: str
    content: str = Field(min_length=10)
    penalty_points: int = Field(ge=0)
    unlock_after_minutes: Optional[int] = Field(default=None, ge=1)


class GuidanceStepResponse(GuidanceStepCreate):
    id: UUID4


class ExerciseAttachmentResponse(_Base):
    id: UUID4
    filename: str
    sha256: str
    size_bytes: int
    visibility: str


class PointCheckpointCreate(_Base):
    label: str
    points: int = Field(ge=1)


class PointCheckpointResponse(PointCheckpointCreate):
    id: UUID4


class ExerciseScoringConfig(_Base):
    """Scoring configuration for a single exercise instance."""

    scoring_type: str = Field(..., pattern=r"^(flat|decay|milestone)$")
    reward_points: int = Field(..., ge=1, le=5000)
    point_checkpoints: List[PointCheckpointCreate] = Field(default_factory=list)


class ExerciseScoringResponse(_Base):
    """Current scoring configuration for an exercise instance."""

    scoring_type: str
    reward_points: int
    point_checkpoints: List[PointCheckpointResponse] = Field(default_factory=list)


class ExerciseInstanceCreate(_Base):
    instance_slug: str
    recipe_version_id: UUID4
    title: str = Field(min_length=3, max_length=120)
    domain_tags: List[str] = Field(min_length=1)
    difficulty: str
    reward_points: int = Field(ge=1, le=5000)
    health_status: str = "draft"
    description: str = Field(min_length=20)
    lab_environment_ref: Optional[str] = None
    scoring_type: str = "flat"
    experience_mode: Optional[str] = Field(None, max_length=50)
    progression_mode: Optional[str] = Field(
        None, pattern=r"^(independent|sequential)$"
    )
    resource_scope: str = Field(
        "per_user", pattern=r"^(per_user|per_team|shared)$"
    )
    sub_category: Optional[str] = Field(
        None, pattern=r"^(selfpaced|event)$"
    )
    point_checkpoints: List[PointCheckpointCreate] = Field(default_factory=list)
    validation_targets: List[ValidationTargetCreate] = Field(default_factory=list)
    guidance_steps: List[GuidanceStepCreate] = Field(default_factory=list)
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


class ExerciseInstanceUpdate(_Base):
    instance_slug: Optional[str] = None
    recipe_version_id: Optional[UUID4] = None
    title: Optional[str] = None
    domain_tags: Optional[List[str]] = None
    difficulty: Optional[str] = None
    reward_points: Optional[int] = None
    health_status: Optional[str] = None
    description: Optional[str] = None
    lab_environment_ref: Optional[str] = None
    scoring_type: Optional[str] = None
    point_checkpoints: Optional[List[PointCheckpointCreate]] = None
    validation_targets: Optional[List[ValidationTargetCreate]] = None
    guidance_steps: Optional[List[GuidanceStepCreate]] = None
    dependencies: Optional[List[UUID4]] = None
    experience_mode: Optional[str] = Field(None, max_length=50)
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


class ExerciseInstanceResponse(_Base):
    id: UUID4
    recipe_version_id: UUID4
    instance_slug: str
    title: str
    domain_tags: List[str]
    difficulty: str
    reward_points: int
    health_status: str
    description: str
    lab_environment_ref: Optional[str]
    scoring_type: str
    experience_mode: Optional[str]
    progression_mode: Optional[str]
    resource_scope: str
    sub_category: Optional[str]
    created_by: uuid.UUID
    reviewed_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    validation_targets: List[ValidationTargetResponse] = Field(default_factory=list)
    guidance_steps: List[GuidanceStepResponse] = Field(default_factory=list)
    attachments: List[ExerciseAttachmentResponse] = Field(default_factory=list)
    point_checkpoints: List[PointCheckpointResponse] = Field(default_factory=list)
    dependencies: List[UUID4] = Field(default_factory=list)


class RecipeSubset(_Base):
    """Minimal recipe metadata embedded inside each exercise response."""
    recipe_id: Optional[UUID4] = None
    name: str
    category: Optional[str] = None
    version_number: int
    recipe_version_id: UUID4


class ExerciseWithRecipeResponse(ExerciseInstanceResponse):
    """ExerciseInstance (superset) with embedded recipe details as a subset."""
    recipe: Optional[RecipeSubset] = None


class PaginatedResponse(_Base):
    data: List[ExerciseInstanceResponse]
    meta: Dict[str, int]
