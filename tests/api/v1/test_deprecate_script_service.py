import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from app.services.registry_metadata import deprecate_registry_service
from app.api.schemas.registry_metadata import ScriptStatus


def make_mock_db(existing_script=None):
    """Helper to build a mock db for deprecate operations."""
    mock_db = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = existing_script
    mock_db.execute = AsyncMock(return_value=fetch_result)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def make_mock_registry(**kwargs):
    defaults = {
        "id": uuid4(),
        "title": "Test Script",
        "status": ScriptStatus.APPROVED.value,  # plain string, as stored in DB
        "deprecated_at": None,
    }
    defaults.update(kwargs)
    registry = MagicMock()
    for k, v in defaults.items():
        setattr(registry, k, v)
    return registry


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deprecate_script_not_found():
    """Raises HTTP 404 when script does not exist."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deprecate_script_not_found_detail_message():
    """404 exception carries the correct detail message."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(uuid4(), mock_db)
    assert exc_info.value.detail == "Script not found."


@pytest.mark.asyncio
async def test_deprecate_script_no_commit_on_not_found():
    """db.commit() is NOT called when script is not found."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await deprecate_registry_service(uuid4(), mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Status guard — invalid statuses raise 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deprecate_script_draft_raises_400():
    """DRAFT scripts cannot be deprecated."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_deprecate_script_rejected_raises_400():
    """REJECTED scripts cannot be deprecated."""
    mock_registry = make_mock_registry(status=ScriptStatus.REJECTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_deprecate_script_already_deprecated_raises_400():
    """Already DEPRECATED scripts cannot be deprecated again."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_deprecate_script_invalid_status_detail_message():
    """400 detail message includes current status and mentions allowed statuses."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await deprecate_registry_service(mock_registry.id, mock_db)
    detail = exc_info.value.detail.lower()
    assert ScriptStatus.DRAFT.value in detail
    assert "submitted" in detail or "approved" in detail


@pytest.mark.asyncio
async def test_deprecate_script_invalid_status_no_commit():
    """db.commit() is NOT called when status transition is invalid."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await deprecate_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Successful deprecation — SUBMITTED and APPROVED are both allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deprecate_approved_script_success():
    """APPROVED script is successfully deprecated."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await deprecate_registry_service(mock_registry.id, mock_db)
    assert result == {"message": "Script deprecated successfully."}


@pytest.mark.asyncio
async def test_deprecate_submitted_script_success():
    """SUBMITTED script is successfully deprecated."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await deprecate_registry_service(mock_registry.id, mock_db)
    assert result == {"message": "Script deprecated successfully."}


@pytest.mark.asyncio
async def test_deprecate_script_sets_status():
    """Script status is updated to DEPRECATED on success."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    assert mock_registry.status == ScriptStatus.DEPRECATED


@pytest.mark.asyncio
async def test_deprecate_submitted_script_sets_status():
    """SUBMITTED script status is updated to DEPRECATED."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    assert mock_registry.status == ScriptStatus.DEPRECATED


@pytest.mark.asyncio
async def test_deprecate_script_sets_deprecated_at():
    """deprecated_at timestamp is set on successful deprecation."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    assert mock_registry.deprecated_at is not None


@pytest.mark.asyncio
async def test_deprecate_script_commits():
    """db.commit() is called once on successful deprecation."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deprecate_script_no_refresh():
    """db.refresh() is NOT called since service returns a message dict."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    mock_db.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deprecate_script_db_execute_called_once():
    """db.execute() is called exactly once to fetch the script."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(mock_registry.id, mock_db)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_deprecate_script_only_status_and_deprecated_at_change():
    """Only status and deprecated_at are mutated — no other fields touched."""
    script_id = uuid4()
    mock_registry = make_mock_registry(
        id=script_id,
        title="Original Title",
        status=ScriptStatus.APPROVED.value,
        revision=3,
    )
    mock_db = make_mock_db(existing_script=mock_registry)
    await deprecate_registry_service(script_id, mock_db)
    assert mock_registry.title == "Original Title"
    assert mock_registry.revision == 3
    assert mock_registry.status == ScriptStatus.DEPRECATED
    assert mock_registry.deprecated_at is not None