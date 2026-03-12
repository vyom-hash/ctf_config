import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from app.services.registry_metadata import delete_registry_service
from app.api.schemas.registry_metadata import ScriptStatus

PATCH_MINIO = "app.services.registry_metadata.delete_script_files"


def make_mock_db(existing_script=None):
    """
    Only one execute() needed now — fetch script by id.
    Cascade delete-orphan handles revision cleanup via db.delete(registry).
    """
    mock_db = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = existing_script
    mock_db.execute = AsyncMock(return_value=fetch_result)
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


def make_mock_registry(**kwargs):
    defaults = {
        "id": uuid4(),
        "title": "Script To Delete",
        "status": ScriptStatus.DEPRECATED,
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
async def test_delete_script_not_found():
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_registry_service(uuid4(), mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_script_not_found_detail_message():
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_registry_service(uuid4(), mock_db)
    assert exc_info.value.detail == "Script not found."


@pytest.mark.asyncio
async def test_delete_script_no_delete_on_not_found():
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await delete_registry_service(uuid4(), mock_db)
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_script_no_commit_on_not_found():
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await delete_registry_service(uuid4(), mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Status guard — invalid statuses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_script_submitted_raises_400():
    """SUBMITTED scripts cannot be deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await delete_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_script_approved_raises_400():
    """APPROVED scripts cannot be deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await delete_registry_service(mock_registry.id, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_script_invalid_status_detail_message():
    """400 detail message includes the current status that cannot be deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException) as exc_info:
        await delete_registry_service(mock_registry.id, mock_db)
    detail = exc_info.value.detail.lower()
    assert ScriptStatus.APPROVED.value in detail
    assert "cannot be deleted" in detail


@pytest.mark.asyncio
async def test_delete_script_invalid_status_no_delete():
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await delete_registry_service(mock_registry.id, mock_db)
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_script_invalid_status_no_commit():
    mock_registry = make_mock_registry(status=ScriptStatus.APPROVED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await delete_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Successful deletes — allowed statuses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_deprecated_success(mock_minio):
    """DEPRECATED script is successfully deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await delete_registry_service(mock_registry.id, mock_db)
    assert result is None


@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_draft_success(mock_minio):
    """DRAFT script is successfully deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.DRAFT)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await delete_registry_service(mock_registry.id, mock_db)
    assert result is None


@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_rejected_success(mock_minio):
    """REJECTED script is successfully deleted."""
    mock_registry = make_mock_registry(status=ScriptStatus.REJECTED)
    mock_db = make_mock_db(existing_script=mock_registry)
    result = await delete_registry_service(mock_registry.id, mock_db)
    assert result is None


# ---------------------------------------------------------------------------
# DB interactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_deletes_metadata(mock_minio):
    """db.delete() is called with the registry object — cascade handles revisions."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    await delete_registry_service(mock_registry.id, mock_db)
    mock_db.delete.assert_called_once_with(mock_registry)


@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_commits(mock_minio):
    """db.commit() is called after deletion."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    await delete_registry_service(mock_registry.id, mock_db)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_executes_once(mock_minio):
    """db.execute() called exactly once — only the fetch. Cascade handles revisions."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    await delete_registry_service(mock_registry.id, mock_db)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_delete_script_execute_once_on_not_found():
    """db.execute() called only once (fetch) when script is not found."""
    mock_db = make_mock_db(existing_script=None)
    with pytest.raises(HTTPException):
        await delete_registry_service(uuid4(), mock_db)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_delete_script_execute_once_on_invalid_status():
    """db.execute() called only once (fetch) when status check fails."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with pytest.raises(HTTPException):
        await delete_registry_service(mock_registry.id, mock_db)
    assert mock_db.execute.call_count == 1


# ---------------------------------------------------------------------------
# MinIO cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_calls_minio_cleanup(mock_minio):
    """delete_script_files is called with the script UUID after DB delete."""
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    await delete_registry_service(mock_registry.id, mock_db)
    mock_minio.assert_called_once_with(script_uuid=str(mock_registry.id))


@pytest.mark.asyncio
@patch(PATCH_MINIO, new_callable=AsyncMock)
async def test_delete_script_minio_called_after_commit(mock_minio):
    """MinIO cleanup happens after db.commit() — DB is consistent first."""
    call_order = []
    mock_registry = make_mock_registry(status=ScriptStatus.DEPRECATED)
    mock_db = make_mock_db(existing_script=mock_registry)
    mock_db.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))
    mock_minio.side_effect = AsyncMock(side_effect=lambda **kw: call_order.append("minio"))
    await delete_registry_service(mock_registry.id, mock_db)
    assert call_order.index("commit") < call_order.index("minio")


@pytest.mark.asyncio
async def test_delete_script_no_minio_on_not_found():
    """delete_script_files is NOT called when script is not found."""
    mock_db = make_mock_db(existing_script=None)
    with patch(PATCH_MINIO, new_callable=AsyncMock) as mock_minio:
        with pytest.raises(HTTPException):
            await delete_registry_service(uuid4(), mock_db)
        mock_minio.assert_not_called()


@pytest.mark.asyncio
async def test_delete_script_no_minio_on_invalid_status():
    """delete_script_files is NOT called when status check fails."""
    mock_registry = make_mock_registry(status=ScriptStatus.SUBMITTED)
    mock_db = make_mock_db(existing_script=mock_registry)
    with patch(PATCH_MINIO, new_callable=AsyncMock) as mock_minio:
        with pytest.raises(HTTPException):
            await delete_registry_service(mock_registry.id, mock_db)
        mock_minio.assert_not_called()