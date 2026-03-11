"""
Unit tests for recipe service delete operations.

Covers: delete_draft, delete_domain, delete_unit, delete_gateway.
Challenges are defined by exercise instance; delete_challenge was removed.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import recipe_service as svc


class TestDeleteDraft:
    """delete_draft(session, draft_id)."""

    @pytest.mark.asyncio
    async def test_404_when_draft_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.delete_draft(session, uuid.uuid4())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_deployments_use_version(self) -> None:
        session = AsyncMock()
        draft_id = uuid.uuid4()
        draft = MagicMock(id=draft_id)
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=draft):
            with patch.object(
                svc._repo,
                "get_version_ids_by_draft_id",
                new_callable=AsyncMock,
                return_value=[uuid.uuid4()],
            ):
                with patch.object(
                    svc._deployment_repo,
                    "count_by_recipe_version_ids",
                    new_callable=AsyncMock,
                    return_value=1,
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await svc.delete_draft(session, draft_id)
                    assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deletes_when_no_deployments(self) -> None:
        session = AsyncMock()
        draft_id = uuid.uuid4()
        draft = MagicMock(id=draft_id)
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=draft):
            with patch.object(
                svc._repo,
                "get_version_ids_by_draft_id",
                new_callable=AsyncMock,
                return_value=[uuid.uuid4()],
            ):
                with patch.object(
                    svc._deployment_repo,
                    "count_by_recipe_version_ids",
                    new_callable=AsyncMock,
                    return_value=0,
                ):
                    with patch.object(svc._repo, "delete_draft", new_callable=AsyncMock):
                        await svc.delete_draft(session, draft_id)


class TestDeleteDomain:
    """delete_domain(session, draft_id, domain_id)."""

    @pytest.mark.asyncio
    async def test_404_when_domain_not_found(self) -> None:
        session = AsyncMock()
        draft_id = uuid.uuid4()
        domain_id = uuid.uuid4()
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=MagicMock()):
            with patch.object(
                svc._repo,
                "delete_domain_by_id",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.delete_domain(session, draft_id, domain_id)
                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_success_when_deleted(self) -> None:
        session = AsyncMock()
        draft_id = uuid.uuid4()
        domain_id = uuid.uuid4()
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=MagicMock()):
            with patch.object(
                svc._repo,
                "delete_domain_by_id",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await svc.delete_domain(session, draft_id, domain_id)


class TestDeleteUnit:
    """delete_unit(session, draft_id, unit_id)."""

    @pytest.mark.asyncio
    async def test_404_when_unit_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=MagicMock()):
            with patch.object(
                svc._repo,
                "delete_unit_by_id",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.delete_unit(session, uuid.uuid4(), uuid.uuid4())
                assert exc_info.value.status_code == 404


class TestDeleteGateway:
    """delete_gateway(session, draft_id, gateway_id)."""

    @pytest.mark.asyncio
    async def test_404_when_gateway_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_draft_by_id", new_callable=AsyncMock, return_value=MagicMock()):
            with patch.object(
                svc._repo,
                "delete_gateway_by_id",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.delete_gateway(session, uuid.uuid4(), uuid.uuid4())
                assert exc_info.value.status_code == 404
