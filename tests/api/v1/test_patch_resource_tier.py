import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError
from app.services.resource_tier import patch_resource_tier_api
from app.api.schemas.resource_tier import PatchResourceTierSchema


def setup_mock_db(mock_tier):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_tier)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_patch_success():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    payload = PatchResourceTierSchema(tier_name="patched")

    mock_db = setup_mock_db(mock_tier)

    result = await patch_resource_tier_api("id-1", payload, mock_db)

    assert result.tier_name == "patched"


@pytest.mark.asyncio
async def test_patch_empty_body():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    payload = PatchResourceTierSchema()

    mock_db = setup_mock_db(mock_tier)

    with pytest.raises(Exception) as exc:
        await patch_resource_tier_api("id-1", payload, mock_db)

    assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_patch_inactive_resource():
    mock_tier = MagicMock()
    mock_tier.is_active = False

    mock_db = setup_mock_db(mock_tier)

    payload = PatchResourceTierSchema(tier_name="x")

    with pytest.raises(Exception) as exc:
        await patch_resource_tier_api("id", payload, mock_db)

    assert exc.value.status_code == 404

@pytest.mark.asyncio
async def test_patch_internal_failure():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    mock_db = setup_mock_db(mock_tier)
    mock_db.commit.side_effect = Exception("Unexpected")

    payload = PatchResourceTierSchema(tier_name="fail")

    with pytest.raises(Exception) as exc:
        await patch_resource_tier_api("id", payload, mock_db)

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_patch_duplicate_provider_reference():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    mock_db = setup_mock_db(mock_tier)
    mock_db.commit.side_effect = IntegrityError(None, None, None)

    payload = PatchResourceTierSchema(**{"provider_reference": "duplicate"})

    with pytest.raises(Exception) as exc:
        await patch_resource_tier_api("id", payload, mock_db)

    assert exc.value.status_code == 409

    