import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException

from app.services.registry_metadata import get_registry_by_title_service


PATCH_GET_FILE = "app.services.registry_metadata.get_script_file"


def make_mock_db(registry_return=None, revision_return=None):
    """
    First execute()  → fetch registry by title + tenant_id
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
        "title": "deploy.sh",
        "summary": "Deployment script",
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
    defaults = {
        "id": uuid4(),
        "registry_id": registry_id or uuid4(),
        "revision_number": 1,
        "checksum": "abc123def456",
        "signature_reference": f"{registry_id}/{registry_id}_1" if registry_id else "uuid/uuid_1",
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
async def test_get_by_title_registry_not_found():
    """Raises HTTP 404 when no registry matches title + tenant_id."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_by_title_service("missing.sh", uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_by_title_registry_not_found_detail():
    """404 detail message is correct when registry not found."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_by_title_service("missing.sh", uuid4(), mock_db)
    assert exc_info.value.detail == "Script not found."


@pytest.mark.asyncio
async def test_get_by_title_no_second_query_on_registry_not_found():
    """If registry is not found, revision query is never executed."""
    mock_db = make_mock_db(registry_return=None)
    with pytest.raises(HTTPException):
        await get_registry_by_title_service("missing.sh", uuid4(), mock_db)
    assert mock_db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Not found — revision / signature_reference
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_title_revision_not_found():
    """Raises HTTP 404 when registry exists but revision row is missing."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_by_title_revision_not_found_detail():
    """404 detail message is correct when revision is missing."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)
    assert exc_info.value.detail == "Script revision or file reference not found."


@pytest.mark.asyncio
async def test_get_by_title_signature_reference_none():
    """Raises HTTP 404 when revision exists but signature_reference is None."""
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        signature_reference=None,
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)
    with pytest.raises(HTTPException) as exc_info:
        await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Successful fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_success(mock_get_file):
    """Returns correct response dict on successful fetch."""
    mock_get_file.return_value = "echo hello"
    mock_registry = make_mock_registry(status="approved")
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert result["title"] == mock_registry.title
    assert result["script_content"] == "echo hello"
    assert result["status"] == "approved"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_returns_all_fields(mock_get_file):
    """Response dict contains all expected keys."""
    mock_get_file.return_value = "#!/bin/bash"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    expected_keys = {
        "id", "title", "summary", "execution_type",
        "revision", "latest_revision", "status",
        "checksum", "signature_reference", "deprecated_at",
        "script_content",
    }
    assert expected_keys == set(result.keys())


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_script_content_matches_minio(mock_get_file):
    """script_content in response matches what MinIO returns."""
    expected_content = "#!/bin/bash\necho deploy"
    mock_get_file.return_value = expected_content
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert result["script_content"] == expected_content


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_uses_live_revision_not_latest(mock_get_file):
    """
    Fetches revision matching registry.revision (live version),
    NOT registry.latest_revision which may be a pending draft.
    """
    mock_get_file.return_value = "v2 content"
    # revision=2 is live, latest_revision=3 is a pending draft
    mock_registry = make_mock_registry(revision=2, latest_revision=3)
    # revision returned by DB should be revision_number=2
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        revision_number=2,
        signature_reference=f"{mock_registry.id}/{mock_registry.id}_2",
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert result["revision"] == 2
    assert result["script_content"] == "v2 content"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_revision_fields_in_response(mock_get_file):
    """checksum and signature_reference come from RegistryRevision, not RegistryMetadata."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        checksum="deadbeef1234",
        signature_reference="uuid/uuid_1",
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert result["checksum"] == "deadbeef1234"
    assert result["signature_reference"] == "uuid/uuid_1"


@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_deprecated_at_none(mock_get_file):
    """deprecated_at is None for non-deprecated scripts."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry(deprecated_at=None)
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    result = await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert result["deprecated_at"] is None


# ---------------------------------------------------------------------------
# MinIO interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_calls_minio_with_signature_reference(mock_get_file):
    """get_script_file is called with the revision's signature_reference."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    sig_ref = f"{mock_registry.id}/{mock_registry.id}_1"
    mock_revision = make_mock_revision(
        registry_id=mock_registry.id,
        signature_reference=sig_ref,
    )
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    mock_get_file.assert_called_once_with(sig_ref)


@pytest.mark.asyncio
async def test_get_by_title_no_minio_call_on_registry_not_found():
    """get_script_file is NOT called when registry is not found."""
    mock_db = make_mock_db(registry_return=None)
    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        with pytest.raises(HTTPException):
            await get_registry_by_title_service("missing.sh", uuid4(), mock_db)
        mock_get_file.assert_not_called()


@pytest.mark.asyncio
async def test_get_by_title_no_minio_call_on_revision_not_found():
    """get_script_file is NOT called when revision is not found."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=None)
    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        with pytest.raises(HTTPException):
            await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)
        mock_get_file.assert_not_called()


@pytest.mark.asyncio
async def test_get_by_title_minio_failure_propagates():
    """If get_script_file raises, the exception propagates to the caller."""
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    with patch(PATCH_GET_FILE, new_callable=AsyncMock) as mock_get_file:
        mock_get_file.side_effect = Exception("MinIO connection failed")
        with pytest.raises(Exception, match="MinIO connection failed"):
            await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_GET_FILE, new_callable=AsyncMock)
async def test_get_by_title_db_execute_called_twice(mock_get_file):
    """db.execute() called twice: once for registry, once for revision."""
    mock_get_file.return_value = "content"
    mock_registry = make_mock_registry()
    mock_revision = make_mock_revision(registry_id=mock_registry.id)
    mock_db = make_mock_db(registry_return=mock_registry, revision_return=mock_revision)

    await get_registry_by_title_service(mock_registry.title, uuid4(), mock_db)

    assert mock_db.execute.call_count == 2