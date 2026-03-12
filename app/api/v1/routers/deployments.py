"""
Deployments Router — creates a deployment record with constraint enforcement.

Endpoint
────────
  POST /api/v1/deployments  (single creation endpoint)
    Two modes (one of which must be used):
    - By version id: recipe_version_id + optional name, participant_id, access.
    - By recipe: recipe_id, recipe_version, initiator_user,
      experience_type, duration_hours, access_method + optional name, access.
    Responses include hardcoded provider_profile (not stored in DB).
    Validates version exists/published/approved, team_configuration, concurrency limit.
    On success → 201 with deployment record (status ALLOCATING).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.schemas.deployment import (
    DeploymentCreateRequest,
    DeploymentResponse,
    DeploymentUpdateRequest,
    PaginatedDeploymentResponse,
)
from app.core.database import get_db
from app.core.redis_client import get_redis_optional
from app.core.security import get_current_user_id
from app.services import deployment_service

router = APIRouter(prefix="/deployments", tags=["Deployments"])

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]
RedisOptional = Annotated[Optional[object], Depends(get_redis_optional)]


@router.get(
    "",
    response_model=PaginatedDeploymentResponse,
    summary="List deployments",
)
async def list_deployments(
    db: DB,
    _: CurrentUser,
    recipe_version_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Filter by recipe version ID; omit to list all deployments",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> PaginatedDeploymentResponse:
    """List all deployments. Optionally filter by recipe_version_id."""
    return await deployment_service.list_deployments(
        db,
        recipe_version_id=recipe_version_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.post(
    "",
    response_model=DeploymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a deployment",
    responses={
        400: {"description": "Invalid request (must provide recipe_version_id or recipe_id + recipe_version + params)"},
        404: {"description": "Recipe version not found"},
        403: {"description": "Recipe version not approved for deployment"},
        409: {"description": "Team configuration violation"},
        422: {"description": "Recipe version not published"},
        429: {"description": "Concurrent deployment limit reached"},
    },
)
async def create_deployment(
    payload: DeploymentCreateRequest,
    db: DB,
    user_id: CurrentUser,
    redis: RedisOptional,
) -> DeploymentResponse:
    """
    Create a deployment. One of two modes:

    - **By version id:** `recipe_version_id` + optional name, participant_id, access.
    - **By recipe:** `recipe_id`, `recipe_version`, `initiator_user`,
      `experience_type`, `duration_hours`, `access_method` + optional name, access.
    Response includes `provider_profile` (hardcoded constant).
    """
    return await deployment_service.create_deployment_unified(
        db,
        payload,
        created_by=user_id,
        redis=redis,
    )


@router.get(
    "/{deployment_id}",
    response_model=DeploymentResponse,
    summary="Get deployment by ID",
    responses={
        404: {
            "description": "Deployment not found",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Deployment not found",
                        "deployment_id": "uuid",
                    }
                }
            },
        },
    },
)
async def get_deployment(
    deployment_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> DeploymentResponse:
    """Get a deployment including access config."""
    return await deployment_service.get_deployment(db, deployment_id)


@router.delete(
    "/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a deployment",
    responses={404: {"description": "Deployment not found"}},
)
async def delete_deployment(
    deployment_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> Response:
    """Delete a deployment by ID. Returns 204 No Content on success."""
    await deployment_service.delete_deployment(db, deployment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{deployment_id}",
    response_model=DeploymentResponse,
    summary="Update deployment",
    responses={
        404: {
            "description": "Deployment not found",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Deployment not found",
                        "deployment_id": "uuid",
                    }
                }
            },
        },
    },
)
async def update_deployment(
    deployment_id: uuid.UUID,
    payload: DeploymentUpdateRequest,
    db: DB,
    _: CurrentUser,
) -> DeploymentResponse:
    """Partial update: name, access, target_env, recipe_spec (deployment JSON), or exercises. Send only fields to change; null clears that field."""
    return await deployment_service.update_deployment(db, deployment_id, payload)
