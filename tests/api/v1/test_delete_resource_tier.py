import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.resource_tier import delete_resource_tier_api


def setup_mock_db(mock_tier):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_tier)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_delete_success():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    mock_db = setup_mock_db(mock_tier)

    result = await delete_resource_tier_api("id-1", mock_db)

    assert result["message"] == "Resource tier deleted successfully"


@pytest.mark.asyncio
async def test_delete_not_found():
    mock_db = setup_mock_db(None)

    with pytest.raises(Exception) as exc:
        await delete_resource_tier_api("invalid", mock_db)

    assert exc.value.status_code == 404

@pytest.mark.asyncio
async def test_delete_already_inactive():
    mock_tier = MagicMock()
    mock_tier.is_active = False

    mock_db = setup_mock_db(mock_tier)

    with pytest.raises(Exception) as exc:
        await delete_resource_tier_api("id", mock_db)

    assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_delete_internal_error():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    mock_db = setup_mock_db(mock_tier)
    mock_db.commit.side_effect = Exception("DB error")

    with pytest.raises(Exception) as exc:
        await delete_resource_tier_api("id", mock_db)

    assert exc.value.status_code == 500