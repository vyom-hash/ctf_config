import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from app.services.resource_tier import create_resource_tier_api
from app.api.schemas.resource_tier import CreateResourceTierSchema


def setup_mock_db():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_create_resource_tier_success_no_flavor_match():
    payload = CreateResourceTierSchema(
        tier_name="small",
        description="small tier",
        cpu_cores=2,
        memory_mb=2048,
        storage_gb=20,
        gpu_enabled=False,
        provider_type="custom",
        provider_reference="manual",
        region="RegionOne",
        access_scope="public",
        is_active=True,
    )

    mock_db = setup_mock_db()

    # No matching OpenStack flavor
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await create_resource_tier_api(payload, mock_db)

    assert result.tier_name == "small"
    assert result.provider_reference == "manual"


@pytest.mark.asyncio
async def test_create_with_openstack_flavor_match():
    payload = CreateResourceTierSchema(
        tier_name="matched",
        description="matched tier",
        cpu_cores=2,
        memory_mb=2048,
        storage_gb=20,
        gpu_enabled=False,
        provider_type="",
        provider_reference="",
        region="RegionOne",
        access_scope="public",
        is_active=True,
    )

    mock_db = setup_mock_db()

    # Simulate DB returning a matching OpenStack flavor
    mock_flavor = MagicMock()
    mock_flavor.id = "flavor-123"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_flavor
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await create_resource_tier_api(payload, mock_db)

    assert result.provider_reference == "flavor-123"
    assert result.provider_type == "openstack"


@pytest.mark.asyncio
async def test_create_duplicate_provider_reference():
    payload = CreateResourceTierSchema(
        tier_name="dup",
        description="dup",
        cpu_cores=2,
        memory_mb=2048,
        storage_gb=20,
        gpu_enabled=False,
        provider_type="custom",
        provider_reference="duplicate",
        region="RegionOne",
        access_scope="public",
        is_active=True,
    )

    mock_db = setup_mock_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    # Simulate DB integrity error
    mock_db.commit.side_effect = IntegrityError(None, None, None)

    with pytest.raises(HTTPException) as exc:
        await create_resource_tier_api(payload, mock_db)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_unexpected_exception():
    payload = CreateResourceTierSchema(
        tier_name="error",
        description="error tier",
        cpu_cores=2,
        memory_mb=2048,
        storage_gb=20,
        gpu_enabled=False,
        provider_type="custom",
        provider_reference="err",
        region="RegionOne",
        access_scope="public",
        is_active=True,
    )

    mock_db = setup_mock_db()

    mock_db.execute = AsyncMock(side_effect=Exception("DB failure"))

    with pytest.raises(HTTPException) as exc:
        await create_resource_tier_api(payload, mock_db)

    assert exc.value.status_code == 500