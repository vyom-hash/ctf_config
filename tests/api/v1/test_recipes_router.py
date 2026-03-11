"""
API tests for recipes router delete endpoints.

Uses service mocks; no real DB/Redis required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestDeleteDraft:
    """DELETE /api/v1/recipes/{recipe_id}."""

    @pytest.mark.asyncio
    async def test_401_without_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.delete(
            f"/api/v1/recipes/{uuid.uuid4()}",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_204_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        recipe_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.recipes._recipe_svc.delete_draft",
            new_callable=AsyncMock,
        ):
            resp = await async_client.delete(
                f"/api/v1/recipes/{recipe_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204


class TestDeleteDomain:
    """DELETE /api/v1/recipes/{recipe_id}/domains/{domain_id}."""

    @pytest.mark.asyncio
    async def test_204_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        recipe_id = uuid.uuid4()
        domain_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.recipes._recipe_svc.delete_domain",
            new_callable=AsyncMock,
        ):
            resp = await async_client.delete(
                f"/api/v1/recipes/{recipe_id}/domains/{domain_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204


class TestDeleteUnit:
    """DELETE /api/v1/recipes/{recipe_id}/units/{unit_id}."""

    @pytest.mark.asyncio
    async def test_204_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        recipe_id = uuid.uuid4()
        unit_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.recipes._recipe_svc.delete_unit",
            new_callable=AsyncMock,
        ):
            resp = await async_client.delete(
                f"/api/v1/recipes/{recipe_id}/units/{unit_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204


class TestDeleteGateway:
    """DELETE /api/v1/recipes/{recipe_id}/gateways/{gateway_id}."""

    @pytest.mark.asyncio
    async def test_204_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        recipe_id = uuid.uuid4()
        gateway_id = uuid.uuid4()
        with patch(
            "app.api.v1.routers.recipes._recipe_svc.delete_gateway",
            new_callable=AsyncMock,
        ):
            resp = await async_client.delete(
                f"/api/v1/recipes/{recipe_id}/gateways/{gateway_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204
