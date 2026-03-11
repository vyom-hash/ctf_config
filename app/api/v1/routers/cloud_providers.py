from __future__ import annotations

import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.cloud_provider import CloudProviderCreate, CloudProviderResponse
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.services import cloud_provider_service as _provider_svc

router = APIRouter(prefix="/cloud-providers", tags=["Cloud Providers"])

# ── Dependency aliases ────────────────────────────────────────────────────────
DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]


@router.post(
    "",
    response_model=CloudProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new cloud provider",
)
async def create_provider(
    payload: CloudProviderCreate,
    db: DB,
    _: CurrentUser,
) -> CloudProviderResponse:
    return await _provider_svc.create_provider(db, payload)


@router.get(
    "/{provider_key}",
    response_model=CloudProviderResponse,
    summary="Get a cloud provider by key",
)
async def get_provider(
    provider_key: str,
    db: DB,
    _: CurrentUser,
) -> CloudProviderResponse:
    return await _provider_svc.get_provider(db, provider_key)
