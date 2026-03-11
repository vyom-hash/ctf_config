import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.resource_tier import list_resource_tiers_api


@pytest.mark.asyncio
async def test_list_resource_tiers_success():
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = ["tier1", "tier2"]

    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await list_resource_tiers_api(1, 10, mock_db)

    assert len(result) == 2

@pytest.mark.asyncio
async def test_list_empty_result():
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await list_resource_tiers_api(1, 10, mock_db)

    assert result == []

@pytest.mark.asyncio
async def test_list_pagination_offset():
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = ["tier3"]

    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await list_resource_tiers_api(2, 2, mock_db)

    assert isinstance(result, list)