from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import cloud_provider_service as _svc
from app.api.schemas.cloud_provider import CloudProviderCreate, CloudProviderResponse
from app.models.cloud_provider import ProviderType

@pytest.mark.asyncio
class TestCloudProviderService:
    """Unit tests for CloudProviderService with repo mocking."""

    async def test_create_provider_success(self, mock_db_session: AsyncSession) -> None:
        from app.core.security import encrypt_json
        payload = CloudProviderCreate(
            type=ProviderType.OPENSTACK,
            endpoint="https://openstack.url",
            credentials={"id": "project-123"},
            provider_key="svc-success-key"
        )
        
        provider_orm = AsyncMock()
        provider_orm.id = 1
        provider_orm.type = ProviderType.OPENSTACK
        provider_orm.endpoint = payload.endpoint
        provider_orm.credentials = {"encrypted": encrypt_json(payload.credentials)}
        provider_orm.provider_key = payload.provider_key
        provider_orm.created_at = "2024-01-01T00:00:00"

        with patch("app.services.cloud_provider_service._repo") as mock_repo:
            mock_repo.get_provider_by_key = AsyncMock(return_value=None)
            mock_repo.create_provider = AsyncMock(return_value=provider_orm)
            
            result = await _svc.create_provider(mock_db_session, payload)
            
            assert isinstance(result, CloudProviderResponse)
            assert result.provider_key == "svc-success-key"
            assert result.credentials == provider_orm.credentials
            
            # Verify repository was called with encrypted data
            _, kwargs = mock_repo.create_provider.call_args
            assert "encrypted" in kwargs["credentials"]

    async def test_create_provider_conflict(self, mock_db_session: AsyncSession) -> None:
        payload = CloudProviderCreate(
            type=ProviderType.OPENSTACK,
            endpoint="https://openstack.com",
            credentials={},
            provider_key="existing-key"
        )
        
        with patch("app.services.cloud_provider_service._repo") as mock_repo:
            mock_repo.get_provider_by_key = AsyncMock(return_value=AsyncMock())
            
            with pytest.raises(HTTPException) as exc:
                await _svc.create_provider(mock_db_session, payload)
            
            assert exc.value.status_code == 409
            assert "already exists" in exc.value.detail

    async def test_get_provider_not_found(self, mock_db_session: AsyncSession) -> None:
        with patch("app.services.cloud_provider_service._repo") as mock_repo:
            mock_repo.get_provider_by_key = AsyncMock(return_value=None)
            
            with pytest.raises(HTTPException) as exc:
                await _svc.get_provider(mock_db_session, "missing-key")
            
            assert exc.value.status_code == 404

    async def test_get_provider_success(self, mock_db_session: AsyncSession) -> None:
        from app.core.security import encrypt_json
        provider_key = "svc-get-success"
        raw_creds = {"api_key": "secret"}
        
        provider_orm = AsyncMock()
        provider_orm.id = 1
        provider_orm.type = ProviderType.OPENSTACK
        provider_orm.endpoint = "https://openstack.com"
        provider_orm.credentials = {"encrypted": encrypt_json(raw_creds)}
        provider_orm.provider_key = provider_key
        provider_orm.created_at = "2024-01-01T00:00:00"

        with patch("app.services.cloud_provider_service._repo") as mock_repo:
            mock_repo.get_provider_by_key = AsyncMock(return_value=provider_orm)
            
            result = await _svc.get_provider(mock_db_session, provider_key)
            
            assert isinstance(result, CloudProviderResponse)
            assert result.provider_key == provider_key
            assert result.credentials == provider_orm.credentials
