"""
API tests for deployments router.

Uses dependency overrides or service mocks so no real DB/Redis required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api.schemas.deployment import DeploymentResponse
from app.services import deployment_service as svc


class TestGetDeployment:
    """GET /api/v1/deployments/{deployment_id}."""

    @pytest.mark.asyncio
    async def test_401_without_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.get(
            f"/api/v1/deployments/{uuid.uuid4()}",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_200_returns_deployment(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        mock_deployment_orm: MagicMock,
    ) -> None:
        deployment_id = mock_deployment_orm.id
        with patch(
            "app.api.v1.routers.deployments.deployment_service.get_deployment",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = svc._to_response(mock_deployment_orm)
            resp = await async_client.get(
                f"/api/v1/deployments/{deployment_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == str(deployment_id)
        assert data["status"] == "ALLOCATING"
        assert "recipe_spec" in data
        assert "provider_profile" in data

    @pytest.mark.asyncio
    async def test_404_when_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        from fastapi import HTTPException

        dep_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.deployments.deployment_service.get_deployment",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = HTTPException(status_code=404, detail={"error": "Deployment not found", "deployment_id": str(dep_id)})
            resp = await async_client.get(
                f"/api/v1/deployments/{dep_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 404


class TestUpdateDeployment:
    """PATCH /api/v1/deployments/{deployment_id}."""

    @pytest.mark.asyncio
    async def test_401_without_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.patch(
            f"/api/v1/deployments/{uuid.uuid4()}",
            json={"name": "New name"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_200_returns_updated(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        mock_deployment_orm: MagicMock,
    ) -> None:
        deployment_id = mock_deployment_orm.id
        with patch(
            "app.api.v1.routers.deployments.deployment_service.update_deployment",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = svc._to_response(mock_deployment_orm)
            resp = await async_client.patch(
                f"/api/v1/deployments/{deployment_id}",
                headers=auth_headers,
                json={"name": "Updated deployment name"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == str(deployment_id)


class TestDeleteDeployment:
    """DELETE /api/v1/deployments/{deployment_id}."""

    @pytest.mark.asyncio
    async def test_401_without_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.delete(f"/api/v1/deployments/{uuid.uuid4()}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_204_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        dep_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.deployments.deployment_service.delete_deployment",
            new_callable=AsyncMock,
        ):
            resp = await async_client.delete(
                f"/api/v1/deployments/{dep_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_404_when_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        from fastapi import HTTPException

        dep_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.deployments.deployment_service.delete_deployment",
            new_callable=AsyncMock,
        ) as mock_del:
            mock_del.side_effect = HTTPException(
                status_code=404,
                detail={"error": "Deployment not found", "deployment_id": str(dep_id)},
            )
            resp = await async_client.delete(
                f"/api/v1/deployments/{dep_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 404


class TestCreateDeployment:
    """POST /api/v1/deployments."""

    @pytest.mark.asyncio
    async def test_401_without_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/deployments",
            json={
                "recipe_version_id": str(uuid.uuid4()),
                "member_ids": [],
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_422_when_invalid_body(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Neither recipe_version_id nor recipe_draft_id + recipe_version
        resp = await async_client.post(
            "/api/v1/deployments",
            headers=auth_headers,
            json={"member_ids": []},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_201_created(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        mock_deployment_orm: MagicMock,
    ) -> None:
        with patch(
            "app.api.v1.routers.deployments.deployment_service.create_deployment_unified",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = svc._to_response(mock_deployment_orm)
            resp = await async_client.post(
                "/api/v1/deployments",
                headers=auth_headers,
                json={
                    "recipe_version_id": str(mock_deployment_orm.recipe_version_id),
                    "member_ids": [],
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "deployment_id" in data
        assert data["status"] == "ALLOCATING"
        assert "recipe_spec" in data
        assert "provider_profile" in data
