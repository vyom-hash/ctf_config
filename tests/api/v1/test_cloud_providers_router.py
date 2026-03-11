from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from app.api.schemas.cloud_provider import CloudProviderResponse
from app.models.cloud_provider import ProviderType

@pytest.mark.asyncio
class TestCloudProvidersRouter:
    """API tests for /api/v1/cloud-providers."""

    async def test_create_provider_endpoint(self, async_client: AsyncClient, auth_headers: dict) -> None:
        payload = {
            "type": "OPENSTACK",
            "endpoint": "https://openstack.endpoint",
            "credentials": {"secret": "abc"},
            "provider_key": "api-test-key"
        }
        
        mock_response = CloudProviderResponse(
            id=1,
            type=ProviderType.OPENSTACK,
            endpoint=payload["endpoint"],
            credentials=payload["credentials"],
            provider_key=payload["provider_key"],
            created_at="2024-01-01T12:00:00Z"
        )
        
        with patch("app.api.v1.routers.cloud_providers._provider_svc.create_provider", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = mock_response
            
            resp = await async_client.post("/api/v1/cloud-providers", json=payload, headers=auth_headers)
            
            assert resp.status_code == 201
            assert resp.json()["provider_key"] == "api-test-key"

    async def test_get_provider_endpoint(self, async_client: AsyncClient, auth_headers: dict) -> None:
        provider_key = "test-key-123"
        
        mock_response = CloudProviderResponse(
            id=10,
            type=ProviderType.OPENSTACK,
            endpoint="https://openstack.url",
            credentials={},
            provider_key=provider_key,
            created_at="2024-01-01T12:00:00Z"
        )
        
        with patch("app.api.v1.routers.cloud_providers._provider_svc.get_provider", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = mock_response
            
            resp = await async_client.get(f"/api/v1/cloud-providers/{provider_key}", headers=auth_headers)
            
            assert resp.status_code == 200
            assert resp.json()["provider_key"] == provider_key
