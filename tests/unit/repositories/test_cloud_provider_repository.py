from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.cloud_provider_repository import CloudProviderRepository
from app.models.cloud_provider import ProviderType, CloudProvider

@pytest.mark.asyncio
class TestCloudProviderRepository:
    """Unit tests for CloudProviderRepository using a real session mock."""

    @pytest.fixture
    def repo(self) -> CloudProviderRepository:
        return CloudProviderRepository()

    async def test_create_provider(self, repo: CloudProviderRepository, mock_db_session: AsyncSession) -> None:
        provider = await repo.create_provider(
            mock_db_session,
            type=ProviderType.OPENSTACK,
            endpoint="https://openstack.url",
            credentials={"key": "test"},
            provider_key="repo-test-key"
        )
        assert isinstance(provider, CloudProvider)
        assert provider.type == ProviderType.OPENSTACK
        assert provider.provider_key == "repo-test-key"
        assert mock_db_session.add.called
        assert mock_db_session.flush.called

    async def test_get_provider_by_id(self, repo: CloudProviderRepository, mock_db_session: AsyncSession) -> None:
        mock_db_session.execute = AsyncMock()
        await repo.get_provider_by_id(mock_db_session, 1)
        mock_db_session.execute.assert_called_once()

    async def test_get_provider_by_key(self, repo: CloudProviderRepository, mock_db_session: AsyncSession) -> None:
        mock_db_session.execute = AsyncMock()
        await repo.get_provider_by_key(mock_db_session, "test-key")
        mock_db_session.execute.assert_called_once()
