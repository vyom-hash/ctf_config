"""
Deployment API schemas — request, response, validation errors.

Recipe is not mutated; request accepts only recipe_version_id (no draft_id, no infra).
Access config: access field.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.challenge import DeploymentChallengeResponse, ChallengeWithRecipeResponse


# ─────────────────────────────── Access config ───────────────────────────────

class AccessConfig(BaseModel):
    """Entry and SSH/console access for the deployment (jumphost)."""
    model_config = ConfigDict(extra="forbid")

    entry_method: str = Field(..., description="e.g. gateway")
    ssh_public_key_ref: str = Field(..., max_length=512)
    floating_ip_enabled: bool = False
    remote_console_enabled: bool = True


# ─────────────────────────────── Request ────────────────────────────────────

class DeploymentCreateRequest(BaseModel):
    """
    POST /api/v1/deployments — single endpoint, two modes:

    Mode 1 (by version id): recipe_version_id + optional name, participant_id, access.
    Mode 2 (by recipe): recipe_id, recipe_version, initiator_user,
    experience_type, duration_hours, access_method + optional name, access.
    """
    model_config = ConfigDict(extra="forbid")

    # Mode 1: create by recipe_version_id
    recipe_version_id: Optional[uuid.UUID] = None
    # Mode 2: create by recipe + version number
    recipe_id: Optional[uuid.UUID] = None
    recipe_version: Optional[int] = Field(None, ge=1)
    initiator_user: Optional[uuid.UUID] = None
    experience_type: Optional[str] = Field(None, max_length=100)
    duration_hours: Optional[int] = Field(None, ge=1, le=720)
    # Common
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    participant_id: Optional[uuid.UUID] = None
    access_method: Optional[str] = Field(
        None, max_length=50,
        description="Jumphost access method (e.g. guacamole, vpn, direct)"
    )
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def require_one_mode(self) -> "DeploymentCreateRequest":
        by_version = self.recipe_version_id is not None
        by_recipe = self.recipe_id is not None and self.recipe_version is not None
        if by_version and by_recipe:
            raise ValueError("Provide either recipe_version_id or (recipe_id + recipe_version), not both")
        if not by_version and not by_recipe:
            raise ValueError("Provide either recipe_version_id or (recipe_id + recipe_version)")
        if by_recipe:
            if self.initiator_user is None or self.experience_type is None or self.duration_hours is None:
                raise ValueError("When using recipe_id + recipe_version, initiator_user, experience_type, duration_hours are required")
        return self


class DeploymentCreateFromDraftRequest(BaseModel):
    """Internal: from-draft payload for service layer."""
    model_config = ConfigDict(extra="forbid")

    recipe_id: uuid.UUID
    recipe_version: int = Field(..., ge=1)
    initiator_user: uuid.UUID
    experience_type: str = Field(..., max_length=100)
    duration_hours: int = Field(..., ge=1, le=720)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    participant_id: Optional[uuid.UUID] = None
    access_method: Optional[str] = Field(None, max_length=50)
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, max_length=255)


# ─────────────────────────────── Update (partial) ──────────────────────────────

class DeploymentUpdateRequest(BaseModel):
    """PATCH /api/v1/deployments/{id} — partial update."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = Field(None, max_length=255)
    access_method: Optional[str] = Field(None, max_length=50)
    recipe_spec: Optional[Dict[str, Any]] = None
    exercises: Optional[List[Dict[str, Any]]] = None


# ─────────────────────────────── Success response ────────────────────────────

class DeploymentCreateResponse(BaseModel):
    """201 Created — deployment created, status ALLOCATING."""
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    message: str = Field(default="Deployment created successfully.")
    recipe_version_id: uuid.UUID
    status: str
    expires_at: datetime
    team_size: int
    created_at: datetime
    access: Optional[AccessConfig] = None
    target_env: Optional[str] = None


class DeploymentResponse(BaseModel):
    """Full deployment response — new format with recipe_specs and challenge_specs."""
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    dep_name: Optional[str] = None
    desc: Optional[str] = None
    target_env: Optional[str] = None
    participant_id: Optional[uuid.UUID] = None
    access_method: Optional[str] = None
    recipe_specs: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured recipe specs: global_domain, domains, workload_units, gateway, access_box",
    )
    challenge_specs: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Challenge specs: challenges list + execution_type",
    )


class DeploymentListItem(BaseModel):
    """Summarized deployment for list endpoints."""
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    recipe_version_id: uuid.UUID
    status: str
    expires_at: datetime
    team_size: int
    dep_name: Optional[str] = None
    participant_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    recipe_id: Optional[uuid.UUID] = None
    experience_type: Optional[str] = None
    duration_hours: Optional[int] = None
    access_method: Optional[str] = None
    target_env: Optional[str] = None


class PaginatedDeploymentResponse(BaseModel):
    """Paginated list of deployments."""
    model_config = ConfigDict(from_attributes=True)

    data: List[DeploymentListItem]
    meta: Dict[str, Any]


# ─────────────────────────────── Error bodies ─────────────────────────────────

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
