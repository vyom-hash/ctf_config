import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.resource_tier import update_resource_tier_api
from app.api.schemas.resource_tier import ReplaceResourceTierSchema


def setup_mock_db(mock_tier):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_tier)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_update_resource_tier_success():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    payload = ReplaceResourceTierSchema(
        tier_name="updated",
        description="updated desc",
        cpu_cores=4,
        memory_mb=4096,
        storage_gb=40,
        gpu_enabled=False,
        provider_type="openstack",
        provider_reference="ref-2",
        region="RegionOne",
        access_scope="private",
        is_active=True,
    )

    mock_db = setup_mock_db(mock_tier)

    result = await update_resource_tier_api("id-1", payload, mock_db)

    assert result.tier_name == "updated"


@pytest.mark.asyncio
async def test_update_resource_not_found():
    mock_db = setup_mock_db(None)

    payload = ReplaceResourceTierSchema(
        tier_name="x",
        description="x",
        cpu_cores=1,
        memory_mb=1,
        storage_gb=1,
        gpu_enabled=False,
        provider_type="x",
        provider_reference="x",
        region="x",
        access_scope="x",
        is_active=True,
    )

    with pytest.raises(Exception) as exc:
        await update_resource_tier_api("invalid", payload, mock_db)

    assert exc.value.status_code == 404

@pytest.mark.asyncio
async def test_update_inactive_resource():
    mock_tier = MagicMock()
    mock_tier.is_active = False

    mock_db = setup_mock_db(mock_tier)

    payload = ReplaceResourceTierSchema(
        tier_name="x",
        description="x",
        cpu_cores=1,
        memory_mb=1,
        storage_gb=1,
        gpu_enabled=False,
        provider_type="x",
        provider_reference="x",
        region="x",
        access_scope="x",
        is_active=True,
    )

    with pytest.raises(Exception) as exc:
        await update_resource_tier_api("id", payload, mock_db)

    assert exc.value.status_code == 404

from sqlalchemy.exc import IntegrityError

@pytest.mark.asyncio
async def test_update_duplicate_conflict():
    mock_tier = MagicMock()
    mock_tier.is_active = True

    mock_db = setup_mock_db(mock_tier)
    mock_db.commit.side_effect = IntegrityError(None, None, None)

    payload = ReplaceResourceTierSchema(
        tier_name="dup",
        description="dup",
        cpu_cores=2,
        memory_mb=2,
        storage_gb=2,
        gpu_enabled=False,
        provider_type="dup",
        provider_reference="dup",
        region="dup",
        access_scope="dup",
        is_active=True,
    )

    with pytest.raises(Exception) as exc:
        await update_resource_tier_api("id", payload, mock_db)

    assert exc.value.status_code == 409