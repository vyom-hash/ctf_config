"""
Deployment API schemas — request, response, validation errors.

Recipe is not mutated; request accepts only recipe_version_id (no draft_id, no infra).
Jumphost/access config: access.
provider_profile: hardcoded constant in responses (not stored in DB).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.exercise_instance import ExerciseWithRecipeResponse


# ─────────────────────────────── Jumphost / access config ───────────────────

class AccessConfig(BaseModel):
    """Entry and SSH/console access for the deployment (jumphost)."""
    model_config = ConfigDict(extra="forbid")

    entry_method: str = Field(..., description="e.g. gateway")
    ssh_public_key_ref: str = Field(
        ...,
        description="e.g. secret://org/default-ssh-key",
        max_length=512,
    )
    floating_ip_enabled: bool = False
    remote_console_enabled: bool = True


class AccessGatewayConfig(BaseModel):
    """Access gateway (jumphost) instance configuration."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    attached_segment: str = Field(..., max_length=255)
    image_profile: str = Field(..., max_length=255)
    vnc_enabled: bool = True
    floating_ip_enabled: bool = True
    host_offset: int = Field(..., ge=0, le=255)
    flavor_profile: str = Field(..., max_length=255)


# ─────────────────────────────── Request ────────────────────────────────────

class DeploymentCreateRequest(BaseModel):
    """
    POST /api/v1/deployments — single endpoint, two modes:

    Mode 1 (by version id): recipe_version_id + optional name, member_ids, access.
    Mode 2 (by recipe): recipe_id, recipe_version, initiator_user,
    experience_type, duration_hours, access_mode + optional name, access.
    """
    model_config = ConfigDict(extra="forbid")

    # Mode 1: create by recipe_version_id
    recipe_version_id: Optional[uuid.UUID] = None
    # Mode 2: create by recipe + version number
    recipe_id: Optional[uuid.UUID] = None
    recipe_version: Optional[int] = Field(None, ge=1, description="Recipe version number (e.g. 1, 2)")
    initiator_user: Optional[uuid.UUID] = None
    experience_type: Optional[str] = Field(None, max_length=100)
    duration_hours: Optional[int] = Field(None, ge=1, le=720)
    access_mode: Optional[str] = Field(None, max_length=50)
    # Common
    name: Optional[str] = Field(None, max_length=255)
    member_ids: List[uuid.UUID] = Field(default_factory=list, max_length=32)
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(
        None,
        max_length=255,
        description="Target cloud name (e.g. openstack-dev, aws-prod); appears in deployment JSON",
    )

    @model_validator(mode="after")
    def require_one_mode(self) -> "DeploymentCreateRequest":
        by_version = self.recipe_version_id is not None
        by_recipe = self.recipe_id is not None and self.recipe_version is not None
        if by_version and by_recipe:
            raise ValueError("Provide either recipe_version_id or (recipe_id + recipe_version), not both")
        if not by_version and not by_recipe:
            raise ValueError("Provide either recipe_version_id or (recipe_id + recipe_version)")
        if by_recipe:
            if self.initiator_user is None or self.experience_type is None or self.duration_hours is None or self.access_mode is None:
                raise ValueError("When using recipe_id + recipe_version, initiator_user, experience_type, duration_hours, and access_mode are required")
        return self


class DeploymentCreateFromDraftRequest(BaseModel):
    """Internal: from-draft payload for service layer."""
    model_config = ConfigDict(extra="forbid")

    recipe_id: uuid.UUID
    recipe_version: int = Field(..., ge=1)
    initiator_user: uuid.UUID
    experience_type: str = Field(..., max_length=100)
    duration_hours: int = Field(..., ge=1, le=720)
    access_mode: str = Field(..., max_length=50)
    name: Optional[str] = Field(None, max_length=255)
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, max_length=255, description="Target cloud name")


# ─────────────────────────────── Update (partial) ──────────────────────────────

class DeploymentUpdateRequest(BaseModel):
    """PATCH /api/v1/deployments/{id} — partial update of name, access, target_env, and stored deployment JSON (recipe_spec, exercises)."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=255)
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, max_length=255, description="Target cloud name")
    # Stored deployment JSON: replace recipe snapshot and/or exercises snapshot in DB
    recipe_spec: Optional[Dict[str, Any]] = Field(
        None,
        description="Full recipe snapshot (metadata, network_profile, domains, workload_units, gateways, jumphost_unit) to store; replaces existing recipe_spec",
    )
    exercises: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Exercise snapshot list to store; replaces existing exercises JSON",
    )


# ─────────────────────────────── Success response ────────────────────────────

class DeploymentCreateResponse(BaseModel):
    """201 Created — deployment created, status ALLOCATING."""
    model_config = ConfigDict(from_attributes=True)

    deployment_id: uuid.UUID
    message: str = Field(
        default="Deployment created successfully.",
        description="Success message for deployment creation",
    )
    recipe_version_id: uuid.UUID
    status: str
    expires_at: datetime
    team_size: int
    created_at: datetime
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, description="Target cloud name")
    provider_profile: Optional[Dict[str, Any]] = Field(
        None,
        description="Hardcoded provider config; omitted when target_env is set",
    )


class DeploymentResponse(BaseModel):
    """Full deployment (GET/POST) — single standard shape; recipe_spec only (no duplicate recipe)."""
    model_config = ConfigDict(from_attributes=True)

    deployment_id: uuid.UUID
    recipe_version_id: uuid.UUID
    status: str
    expires_at: datetime
    team_size: int
    name: Optional[str] = None
    member_ids: List[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    access: Optional[AccessConfig] = None
    recipe_id: Optional[uuid.UUID] = None
    experience_type: Optional[str] = None
    duration_hours: Optional[int] = None
    access_mode: Optional[str] = None
    target_env: Optional[str] = Field(None, description="Target cloud name")
    provider_profile: Optional[Dict[str, Any]] = Field(
        None,
        description="Hardcoded provider config; omitted when target_env is set",
    )
    recipe_spec: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Stored recipe snapshot (metadata, network_profile, domains, workload_units, gateways, jumphost_unit)",
    )
    exercises: List[ExerciseWithRecipeResponse] = Field(
        default_factory=list,
        description="Exercises (superset) bound to this deployment, with embedded recipe subset",
    )


class DeploymentListItem(BaseModel):
    """Summarized deployment for list endpoints."""
    model_config = ConfigDict(from_attributes=True)

    deployment_id: uuid.UUID
    recipe_version_id: uuid.UUID
    status: str
    expires_at: datetime
    team_size: int
    name: Optional[str] = None
    member_ids: List[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    recipe_id: Optional[uuid.UUID] = None
    experience_type: Optional[str] = None
    duration_hours: Optional[int] = None
    access_mode: Optional[str] = None
    target_env: Optional[str] = None


class PaginatedDeploymentResponse(BaseModel):
    """Paginated list of deployments."""
    model_config = ConfigDict(from_attributes=True)

    data: List[DeploymentListItem]
    meta: Dict[str, Any]


# ─────────────────────────────── Error bodies (for OpenAPI / clients) ─────────

class DeploymentLimitExceededDetail(BaseModel):
    error: str = "maximum_concurrent_deployments"
    message: str = "Concurrent deployment limit reached (1000). Try again later."
    code: str = "DEPLOYMENT_LIMIT_EXCEEDED"


class TeamSizeViolationDetail(BaseModel):
    error: str = "team_configuration"
    message: str = "Teams are disabled; only one member allowed"
    code: str = "TEAM_SIZE_VIOLATION"


class RecipeVersionNotFoundDetail(BaseModel):
    error: str = "Recipe version not found"
    recipe_version_id: str


class RecipeVersionNotPublishedDetail(BaseModel):
    error: str = "Recipe version not published"
    recipe_version_id: str


class RecipeVersionNotApprovedDetail(BaseModel):
    error: str = "Recipe version not approved for deployment"
    recipe_version_id: str
    approval_status: str
