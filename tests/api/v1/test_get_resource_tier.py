import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.resource_tier import ResourceTier
from app.services.resource_tier import get_resource_tier_api
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_get_resource_tier_success():
    mock_db = AsyncMock()

    tier = ResourceTier(
        id=1,
        cpu_cores=2,
        memory_mb=4096,
        storage_gb=40,
        region="us-east",
        provider_reference="flavor-1",
        provider_type="openstack",
        is_active=True,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = tier

    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_resource_tier_api(1, mock_db)

    assert result.id == 1
    assert result.cpu_cores == 2


@pytest.mark.asyncio
async def test_get_resource_tier_not_found():
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc:
        await get_resource_tier_api(999, mock_db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_resource_tier_inactive():
    mock_db = AsyncMock()

    # API filters is_active=True
    # so returning None simulates inactive
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc:
        await get_resource_tier_api(2, mock_db)

    assert exc.value.status_code == 404