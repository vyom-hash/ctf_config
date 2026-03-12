import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from app.services.registry_metadata import update_registry_service


PATCH_MD5 = "app.services.registry_metadata.generate_md5"
PATCH_SAVE = "app.services.registry_metadata.save_script_file"
PATCH_REVISION = "app.services.registry_metadata.RegistryRevision"


def make_mock_db(script_return):
    """Helper to build a mock db for update operations."""
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = script_return

    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def make_mock_registry(**kwargs):
    """Build a MagicMock mimicking a RegistryMetadata ORM object."""
    defaults = {
        "id": uuid4(),
        "title": "Original Title",
        "summary": "Original summary",
        "execution_type": "batch",
        "revision": 1,          # current approved/live version
        "latest_revision": 1,   # latest revision (may be a draft)
        "status": "draft",
        "created_by": uuid4(),
    }
    defaults.update(kwargs)

    registry = MagicMock()
    for k, v in defaults.items():
        setattr(registry, k, v)
    return registry


def make_payload(**kwargs):
    """Build a simple namespace mimicking UpdateScriptSchema."""
    defaults = {
        "title": None,
        "summary": None,
        "execution_type": None,
        "script_content": None,
    }
    defaults.update(kwargs)

    class Payload:
        pass

    p = Payload()
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------------------
# Not found cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_script_not_found():
    """Raises HTTP 404 when script does not exist."""
    mock_db = make_mock_db(script_return=None)
    payload = make_payload(title="New Title")

    with pytest.raises(HTTPException) as exc_info:
        await update_registry_service(uuid4(), payload, mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_script_not_found_detail_message():
    """404 exception carries the correct detail message."""
    mock_db = make_mock_db(script_return=None)
    payload = make_payload()

    with pytest.raises(HTTPException) as exc_info:
        await update_registry_service(uuid4(), payload, mock_db)

    assert exc_info.value.detail == "Script not found."


# ---------------------------------------------------------------------------
# Metadata-only updates (no script_content)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_script_title_only():
    """Updates title field when provided."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title="Updated Title")

    result = await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.title == "Updated Title"
    assert result is mock_registry


@pytest.mark.asyncio
async def test_update_script_summary_only():
    """Updates summary field when provided."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(summary="New summary text")

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.summary == "New summary text"


@pytest.mark.asyncio
async def test_update_script_execution_type_only():
    """Updates execution_type field when provided."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(execution_type="realtime")

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.execution_type == "realtime"


@pytest.mark.asyncio
async def test_update_script_multiple_metadata_fields():
    """Updates multiple metadata fields in a single call."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(
        title="Multi Update",
        summary="Updated summary",
        execution_type="realtime",
    )

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.title == "Multi Update"
    assert mock_registry.summary == "Updated summary"
    assert mock_registry.execution_type == "realtime"


@pytest.mark.asyncio
async def test_update_script_none_fields_not_applied():
    """Fields that are None in payload do not overwrite existing values."""
    mock_registry = make_mock_registry(title="Keep This Title")
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title=None, summary="Only this changes")

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.title == "Keep This Title"
    assert mock_registry.summary == "Only this changes"


# ---------------------------------------------------------------------------
# Script content update → new DRAFT revision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/scripts/v2.zip")
@patch(PATCH_MD5, return_value="newchecksum456")
async def test_update_script_content_bumps_latest_revision_only(
    mock_md5, mock_save, mock_revision_cls
):
    """
    Providing script_content increments latest_revision by 1.
    `revision` (the live/approved version) must NOT be changed — TL fix.
    """
    mock_registry = make_mock_registry(revision=1, latest_revision=1)
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="print('hello world')")

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.latest_revision == 2
    # revision (live version) must stay unchanged
    assert mock_registry.revision == 1


@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/scripts/v2.zip")
@patch(PATCH_MD5, return_value="newchecksum456")
async def test_update_script_content_revision_is_draft(
    mock_md5, mock_save, mock_revision_cls
):
    """New revision is always created with DRAFT status regardless of registry status."""
    mock_registry = make_mock_registry(revision=1, latest_revision=1, status="approved")
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="new content")

    await update_registry_service(mock_registry.id, payload, mock_db)

    _, kwargs = mock_revision_cls.call_args
    assert kwargs["status"] == "draft"


@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/scripts/v2.zip")
@patch(PATCH_MD5, return_value="newchecksum456")
async def test_update_script_content_generates_checksum(
    mock_md5, mock_save, mock_revision_cls
):
    """Checksum is computed from new script_content."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="new script content")

    await update_registry_service(mock_registry.id, payload, mock_db)

    mock_md5.assert_called_once_with("new script content")

@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, new_callable=AsyncMock)
@patch(PATCH_MD5, return_value="newchecksum456")
async def test_update_script_content_saves_file(
    mock_md5, mock_save, mock_revision_cls
):
    """save_script_file is called with registry UUID, new revision number, and content."""
    mock_save.return_value = "s3://bucket/scripts/v2.zip"
    mock_registry = make_mock_registry(latest_revision=1)
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="updated content")

    await update_registry_service(mock_registry.id, payload, mock_db)

    mock_save.assert_called_once_with(
        script_uuid=str(mock_registry.id),
        version=2,
        content="updated content",
    )


@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/scripts/v2.zip")
@patch(PATCH_MD5, return_value="newchecksum456")
async def test_update_script_content_creates_revision(
    mock_md5, mock_save, mock_revision_cls
):
    """A new RegistryRevision is created and added to db when content changes."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="new content")

    await update_registry_service(mock_registry.id, payload, mock_db)

    mock_revision_cls.assert_called_once()
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/v3.zip")
@patch(PATCH_MD5, return_value="checksum789")
async def test_update_script_content_revision_fields(
    mock_md5, mock_save, mock_revision_cls
):
    """RegistryRevision is created with correct fields."""
    script_id = uuid4()
    creator_id = uuid4()
    mock_registry = make_mock_registry(
        id=script_id, revision=2, latest_revision=2, created_by=creator_id
    )
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(script_content="content")

    await update_registry_service(script_id, payload, mock_db)

    _, kwargs = mock_revision_cls.call_args
    assert kwargs["registry_id"] == script_id
    assert kwargs["revision_number"] == 3
    assert kwargs["checksum"] == "checksum789"
    assert kwargs["signature_reference"] == "s3://bucket/v3.zip"
    assert kwargs["created_by"] == creator_id
    assert kwargs["status"] == "draft"


@pytest.mark.asyncio
@patch(PATCH_REVISION)
@patch(PATCH_SAVE, return_value="s3://bucket/v2.zip")
@patch(PATCH_MD5, return_value="checksum")
async def test_update_script_content_size_is_byte_length(
    mock_md5, mock_save, mock_revision_cls
):
    """size field on revision is the byte length of the script content."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    content = "hello world"
    payload = make_payload(script_content=content)

    await update_registry_service(mock_registry.id, payload, mock_db)

    _, kwargs = mock_revision_cls.call_args
    assert kwargs["size"] == len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# No content change → no revision, version unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_script_no_content_no_revision():
    """No RegistryRevision is created when script_content is not provided."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title="Just a title update")

    with patch(PATCH_REVISION) as mock_revision_cls:
        await update_registry_service(mock_registry.id, payload, mock_db)
        mock_revision_cls.assert_not_called()

    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_script_no_content_revision_unchanged():
    """Neither revision nor latest_revision changes when script_content is absent."""
    mock_registry = make_mock_registry(revision=3, latest_revision=5)
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(summary="Minor change")

    await update_registry_service(mock_registry.id, payload, mock_db)

    assert mock_registry.revision == 3
    assert mock_registry.latest_revision == 5


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_script_commits_to_db():
    """db.commit() is always called after a successful update."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title="Trigger commit")

    await update_registry_service(mock_registry.id, payload, mock_db)

    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_script_refreshes_registry():
    """db.refresh() is called on the registry after commit."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title="Trigger refresh")

    await update_registry_service(mock_registry.id, payload, mock_db)

    mock_db.refresh.assert_called_once_with(mock_registry)


@pytest.mark.asyncio
async def test_update_script_returns_refreshed_registry():
    """The updated registry object is returned after refresh."""
    mock_registry = make_mock_registry()
    mock_db = make_mock_db(script_return=mock_registry)
    payload = make_payload(title="Return me")

    result = await update_registry_service(mock_registry.id, payload, mock_db)

    assert result is mock_registry


@pytest.mark.asyncio
async def test_update_script_no_commit_on_not_found():
    """db.commit() is NOT called when script is not found."""
    mock_db = make_mock_db(script_return=None)
    payload = make_payload(title="Won't commit")

    with pytest.raises(HTTPException):
        await update_registry_service(uuid4(), payload, mock_db)

    mock_db.commit.assert_not_called()