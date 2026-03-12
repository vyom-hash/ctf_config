import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException

from app.services.registry_metadata import get_registry_detail_service


PATCH_GET_FILE = "app.services.registry_metadata.get_script_file"


def make_mock_db(registry_return=None, revision_return=None):
    """
    First execute()  → fetch registry by ID
    Second execute() → fetch revision by registry_id + revision_number
    """
    mock_db = AsyncMock()

    registry_result = MagicMock()
    registry_result.scalar_one_or_none.return_value = registry_return

    revision_result = MagicMock()
    revision_result.scalar_one_or_none.return_value = revision_return

    mock_db.execute = AsyncMock(side_effect=[registry_result, revision_result])
    return mock_db


def make_mock_registry(**kwargs):
    """Build a MagicMock mimicking a RegistryMetadata ORM object."""
    registry_id = uuid4()
    defaults = {
        "id": registry_id,
        "title": "Test Script",
        "summary": "A test summary",
        "execution_type": "batch",
        "revision": 1,
        "latest_revision": 1,
        "status": "approved",
        "deprecated_at": None,
    }
    defaults.update(kwargs)
    registry = MagicMock()
    for k, v in defaults.items():
        setattr(registry, k, v)
    return registry


def make_mock_revision(registry_id=None, **kwargs):
    """Build a MagicMock mimicking a RegistryRevision ORM object."""
    rid = registry_id or uuid4()
    defaults = {
        "id": uuid4(),
        "registry_id": rid,
        "revision_number": 1,
        "checksum": "abc123def456",
        "signature_reference": f"{rid}/{rid}_1",
        "status": "approved",
        "size": 256,
    }
    defaults.update(kwargs)
    revision = MagicMock()
    for k, v in defaults.items():
        setattr(revision, k, v)
    return revision


# ---------------------------------------------------------------------------
# Not found — registry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_registry_detail_not_found():
    """Raises HTTP 404 when registry does not exist."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_registry_detail_not_found_detail_message():
    """404 exception carries the correct detail message."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(uuid4(), mock_db)
    assert exc_info.value.detail == "Script not found."


@pytest.mark.asyncio
async def test_get_registry_detail_random_uuid_not_found():
    """Any random UUID that has no match raises 404."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_registry_detail_no_second_query_on_not_found():
    """If registry is not found, revision query is never executed."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException):
        await get_registry_detail_service(uuid4(), mock_db)
    assert mock_db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Not found — revision / signature_reference
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_registry_detail_revision_not_found():
    """Raises HTTP 404 when registry exists but revision row is missing."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_registry_detail_revision_not_found_detail():
    """404 detail message is correct when revision is missing."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(mock_registry.id, mock_db)
    assert exc_info.value.detail == "Script revision or file reference not found."


@pytest.mark.asyncio
async def test_get_registry_detail_signature_reference_none():
    """Raises HTTP 404 when revision exists but signature_reference is None."""
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        signature_reference=None,
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_detail_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Successful fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_success(mock_get_file):
    """Returns correct response dict on successful fetch."""
    mock_get_file.return_value = "echo hello"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(mock_registry.id, mock_db)

    assert result["id"] == mock_registry.id
    assert result["title"] == mock_registry.title
    assert result["script_content"] == "echo hello"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_returns_all_fields(mock_get_file):
    """Response dict contains all expected keys."""
    mock_get_file.return_value = "#!/bin/bash"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(mock_registry.id, mock_db)

    expected_keys = {
        "id", "title", "summary", "execution_type",
        "revision", "latest_revision", "status",
        "checksum", "signature_reference", "deprecated_at",
        "script_content",
    }
    assert expected_keys == set(result.keys())


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_correct_field_values(mock_get_file):
    """All fields in the response have correct values."""
    mock_get_file.return_value = "#!/bin/bash\necho deploy"
    registry_id = uuid4()
    mock_registry = make_mock_registry(
        id=registry_id,
        title="Deploy Script",
        summary="Deploys the app",
        execution_type="realtime",
        revision=2,
        latest_revision=3,
        status="approved",
        deprecated_at=None,
    )
    mock_revision = make_mock_revision(
        registry_id=registry_id,
        checksum="deadbeef1234",
        signature_reference=f"{registry_id}/{registry_id}_2",
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(registry_id, mock_db)

    assert result["title"] == "Deploy Script"
    assert result["summary"] == "Deploys the app"
    assert result["execution_type"] == "realtime"
    assert result["revision"] == 2
    assert result["latest_revision"] == 3
    assert result["status"] == "approved"
    assert result["checksum"] == "deadbeef1234"
    assert result["signature_reference"] == f"{registry_id}/{registry_id}_2"
    assert result["deprecated_at"] is None
    assert result["script_content"] == "#!/bin/bash\necho deploy"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_uses_live_revision_not_latest(mock_get_file):
    """
    Fetches revision matching registry.revision (live version),
    NOT registry.latest_revision which may be a pending draft.
    """
    mock_get_file.return_value = "v2 content"
    mock_registry = make_mock_registry(revision=2, latest_revision=3)
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        revision_number=2,
        signature_reference=f"{mock_registry.id}/{mock_registry.id}_2",
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(mock_registry.id, mock_db)

    assert result["revision"] == 2
    assert result["script_content"] == "v2 content"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_revision_fields_from_revision_model(mock_get_file):
    """checksum and signature_reference come from RegistryRevision, not RegistryMetadata."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        checksum="rev_checksum_xyz",
        signature_reference="uuid/uuid_1",
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(mock_registry.id, mock_db)

    assert result["checksum"] == "rev_checksum_xyz"
    assert result["signature_reference"] == "uuid/uuid_1"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_optional_fields_none(mock_get_file):
    """Optional fields summary and deprecated_at can be None."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry(summary=None, deprecated_at=None)
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_detail_service(mock_registry.id, mock_db)

    assert result["summary"] is None
    assert result["deprecated_at"] is None


# ---------------------------------------------------------------------------
# MinIO interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_calls_minio_with_signature_reference(mock_get_file):
    """get_script_file is called with the revision's signature_reference."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    sig_ref = f"{mock_registry.id}/{mock_registry.id}_1"
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        signature_reference=sig_ref,
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    await get_registry_detail_service(mock_registry.id, mock_db)

    mock_get_file.assert_called_once_with(sig_ref)


@pytest.mark.asyncio
async def test_get_registry_detail_no_minio_on_registry_not_found():
    """get_script_file is NOT called when registry is not found."""
    mock_db = make_mock_db(registry_return=None)
    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        with pytest.raises(HTTPException):
            await get_registry_detail_service(uuid4(), mock_db)
        mock_get_file.assert_not_called()


@pytest.mark.asyncio
async def test_get_registry_detail_no_minio_on_revision_not_found():
    """get_script_file is NOT called when revision is not found."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        with pytest.raises(HTTPException):
            await get_registry_detail_service(mock_registry.id, mock_db)
        mock_get_file.assert_not_called()


@pytest.mark.asyncio
async def test_get_registry_detail_minio_failure_propagates():
    """If get_script_file raises, the exception propagates to the caller."""
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        mock_get_file.side_effect = Exception("MinIO connection failed")
        with pytest.raises(Exception, match="MinIO connection failed"):
            await get_registry_detail_service(mock_registry.id, mock_db)


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_registry_detail_db_called_twice(mock_get_file):
    """db.execute() called twice: once for registry, once for revision."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    await get_registry_detail_service(mock_registry.id, mock_db)

    assert mock_db.execute.call_count == 2


@pytest.mark.asyncio
async def test_get_registry_detail_db_called_once_on_not_found():
    """db.execute() called only once when registry is not found."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException):
        await get_registry_detail_service(uuid4(), mock_db)
    assert mock_db.execute.call_count == 1