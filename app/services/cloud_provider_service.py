from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.cloud_provider import CloudProviderCreate, CloudProviderResponse
from app.repositories.cloud_provider_repository import CloudProviderRepository

from app.core.security import encrypt_json, decrypt_json

_repo = CloudProviderRepository()


async def create_provider(
    session: AsyncSession,
    payload: CloudProviderCreate,
) -> CloudProviderResponse:
    # Check if provider_key already exists
    existing = await _repo.get_provider_by_key(session, payload.provider_key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cloud provider with key '{payload.provider_key}' already exists",
        )

    # Encrypt credentials before saving
    encrypted_credentials = {"encrypted": encrypt_json(payload.credentials)}

    provider = await _repo.create_provider(
        session,
        type=payload.type,
        endpoint=payload.endpoint,
        credentials=encrypted_credentials,
        provider_key=payload.provider_key,
    )
    return CloudProviderResponse.model_validate(provider)


async def get_provider(
    session: AsyncSession,
    provider_key: str,
) -> CloudProviderResponse:
    provider = await _repo.get_provider_by_key(session, provider_key)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cloud provider with key '{provider_key}' not found",
        )
    return CloudProviderResponse.model_validate(provider)
