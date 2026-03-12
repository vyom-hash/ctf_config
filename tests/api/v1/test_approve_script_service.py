import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from app.services.registry_metadata import approve_registry_service
from app.api.schemas.registry_metadata import ScriptStatus


def make_mock_db(existing_script=None):
    """Helper to build a mock db for approve operations."""
    mock_db = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = existing_script
    mock_db.execute = AsyncMock(return_value=fetch_result)
    mock_db.commit = AsyncMock()
    return mock_db


def make_mock_registry(**kwargs):
    defaults = {
        "id": uuid4(),
        "title": "Test Script",
        "status": ScriptStatus.SUBMITTED.value,  # plain string, as stored in DB
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
async def test_approve_script_not_found():
    """Raises HTTP 404 when script does not exist."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await approve_registry_service(uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_script_not_found_detail_message():
    """404 exception carries the correct detail message."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await approve_registry_service(uuid4(), mock_db)
    assert exc_info.value.detail == "Script not found."


@pytest.mark.asyncio
async def test_approve_script_no_commit_on_not_found():
    """db.commit() is NOT called when script is not found."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await approve_registry_service(uuid4(), mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Already APPROVED — early return
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_already_approved_returns_message():
    """Already APPROVED script returns early with info message."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await approve_registry_service(mock_registry.id, mock_db)
    assert result == {"message": "Script is already in approved state."}


@pytest.mark.asyncio
async def test_approve_already_approved_no_commit():
    """db.commit() is NOT called when script is already approved."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# REJECTED / DEPRECATED — raises 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_rejected_script_raises_400():
    """REJECTED script raises HTTP 400."""
    mock_registry = make_mock_registry(status=ScriptStatus.REJECTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await approve_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_deprecated_script_raises_400():
    """DEPRECATED script raises HTTP 400."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await approve_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_rejected_detail_message():
    """400 detail message contains the current status."""
    mock_registry = make_mock_registry(status=ScriptStatus.REJECTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await approve_registry_service(mock_registry.id, mock_db)
    assert ScriptStatus.REJECTED.value in exc_info.value.detail


@pytest.mark.asyncio
async def test_approve_rejected_no_commit():
    """db.commit() is NOT called when script is REJECTED."""
    mock_registry = make_mock_registry(status=ScriptStatus.REJECTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await approve_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_approve_deprecated_no_commit():
    """db.commit() is NOT called when script is DEPRECATED."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await approve_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# SUBMITTED → APPROVED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_submitted_script_sets_approved():
    """SUBMITTED script status transitions to APPROVED."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    assert mock_registry.status == ScriptStatus.APPROVED


@pytest.mark.asyncio
async def test_approve_submitted_script_returns_success_message():
    """Returns approval success message for SUBMITTED script."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await approve_registry_service(mock_registry.id, mock_db)
    assert result == {"message": "Script approved successfully."}


@pytest.mark.asyncio
async def test_approve_submitted_script_commits():
    """db.commit() is called after approving a SUBMITTED script."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DRAFT → REJECTED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_draft_script_sets_rejected():
    """DRAFT script is automatically rejected."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    assert mock_registry.status == ScriptStatus.REJECTED


@pytest.mark.asyncio
async def test_approve_draft_script_returns_rejection_message():
    """Returns rejection message when script is DRAFT."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await approve_registry_service(mock_registry.id, mock_db)
    assert "message" in result
    assert "rejected" in result["message"].lower()


@pytest.mark.asyncio
async def test_approve_draft_rejection_message_contains_status():
    """Rejection message includes the script's original status."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await approve_registry_service(mock_registry.id, mock_db)
    assert ScriptStatus.DRAFT.value in result["message"]


@pytest.mark.asyncio
async def test_approve_draft_commits():
    """db.commit() is called after auto-rejecting a DRAFT script."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_script_db_execute_called_once():
    """db.execute() is called exactly once to fetch the script."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED.value)
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(mock_registry.id, mock_db)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_approve_script_only_status_changes():
    """Only the status field is mutated — no other fields touched."""
    script_id = uuid4()
    mock_registry = make_mock_registry(
        id=script_id,
        title="Original Title",
        status=ScriptStatus.SUBMITTED.value,
        revision=2,
    )
    mock_db = make_mock_db(existing_script=mock_registry)
    await approve_registry_service(script_id, mock_db)
    assert mock_registry.title == "Original Title"
    assert mock_registry.revision == 2
    assert mock_registry.status == ScriptStatus.APPROVED


@pytest.mark.asyncio
async def test_approve_script_execute_once_on_not_found():
    """db.execute() is called only once (fetch) when script is not found."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await approve_registry_service(uuid4(), mock_db)
    assert mock_db.execute.call_count == 1