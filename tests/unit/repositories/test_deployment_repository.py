"""
Unit tests for deployment repository.

Uses mocked AsyncSession to avoid real DB; exercises all repository methods.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deployment import Deployment, DeploymentStatus
from app.repositories.deployment_repository import DeploymentRepository


@pytest.fixture
def repo() -> DeploymentRepository:
    return DeploymentRepository()


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


class TestDeploymentRepositoryCount:
    """count_running_and_allocating."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_rows(self, repo: DeploymentRepository, mock_session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 0
        mock_session.execute = AsyncMock(return_value=result_mock)
        count = await repo.count_running_and_allocating(mock_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_count_from_scalar(self, repo: DeploymentRepository, mock_session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 42
        mock_session.execute = AsyncMock(return_value=result_mock)
        count = await repo.count_running_and_allocating(mock_session)
        assert count == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_scalar_one_returns_none(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = None
        mock_session.execute = AsyncMock(return_value=result_mock)
        count = await repo.count_running_and_allocating(mock_session)
        assert count == 0


class TestDeploymentRepositoryGetById:
    """get_by_id."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=result_mock)
        out = await repo.get_by_id(mock_session, uuid.uuid4())
        assert out is None

    @pytest.mark.asyncio
    async def test_returns_deployment_when_found(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        deployment = Deployment(
            recipe_version_id=uuid.uuid4(),
            status=DeploymentStatus.ALLOCATING,
            expires_at=datetime.now(timezone.utc),
            team_size=1,
            member_ids=[],
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = deployment
        mock_session.execute = AsyncMock(return_value=result_mock)
        dep_id = deployment.id
        out = await repo.get_by_id(mock_session, dep_id)
        assert out is deployment


class TestDeploymentRepositoryCreate:
    """create."""

    @pytest.mark.asyncio
    async def test_adds_and_refreshes_deployment(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        recipe_version_id = uuid.uuid4()
        expires_at = datetime.now(timezone.utc)
        deployment = await repo.create(
            mock_session,
            recipe_version_id=recipe_version_id,
            status=DeploymentStatus.ALLOCATING,
            expires_at=expires_at,
            team_size=1,
            member_ids=[],
            name="Test",
            recipe_spec={"metadata": {"name": "x"}},
        )
        mock_session.add.assert_called_once()
        (added,) = mock_session.add.call_args[0]
        assert added.recipe_version_id == recipe_version_id
        assert added.status == DeploymentStatus.ALLOCATING
        assert added.name == "Test"
        assert added.recipe_spec == {"metadata": {"name": "x"}}
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(deployment)


class TestDeploymentRepositoryUpdate:
    """update."""

    @pytest.mark.asyncio
    async def test_returns_get_by_id_when_no_allowed_keys(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        deployment = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = deployment
        mock_session.execute = AsyncMock(return_value=result_mock)
        out = await repo.update(mock_session, uuid.uuid4(), {"other_key": "x"})
        # update calls get_by_id when no allowed keys (no update stmt)
        assert out is deployment

    @pytest.mark.asyncio
    async def test_updates_and_returns_refreshed(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        deployment = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = deployment
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_session.flush = AsyncMock()
        dep_id = uuid.uuid4()
        out = await repo.update(
            mock_session,
            dep_id,
            {"name": "New name", "access": {"entry_method": "gateway", "ssh_public_key_ref": "x"}},
        )
        assert mock_session.execute.call_count >= 1
        mock_session.flush.assert_awaited_once()
        assert out is deployment


class TestDeploymentRepositoryDeleteById:
    """delete_by_id."""

    @pytest.mark.asyncio
    async def test_returns_true_when_row_deleted(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_session.execute = AsyncMock(return_value=result_mock)
        out = await repo.delete_by_id(mock_session, uuid.uuid4())
        assert out is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_row(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_session.execute = AsyncMock(return_value=result_mock)
        out = await repo.delete_by_id(mock_session, uuid.uuid4())
        assert out is False


class TestDeploymentRepositoryCountByRecipeVersionIds:
    """count_by_recipe_version_ids."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        count = await repo.count_by_recipe_version_ids(mock_session, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_count_from_scalar(
        self, repo: DeploymentRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 3
        mock_session.execute = AsyncMock(return_value=result_mock)
        count = await repo.count_by_recipe_version_ids(
            mock_session, [uuid.uuid4(), uuid.uuid4()]
        )
        assert count == 3
