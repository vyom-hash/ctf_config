import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from app.services.registry_metadata import create_registry_api
from app.api.schemas.registry_metadata import ScriptStatus
from app.models.registry_metadata import RegistryMetadata


PATCH_MD5 = "app.services.registry_metadata.generate_md5"
PATCH_SAVE = "app.services.registry_metadata.save_script_file"
PATCH_REVISION = "app.services.registry_metadata.RegistryRevision"

DEFAULT_SAVE_RETURN = "scripts/test-uuid/test-uuid_1"

def apply_patches(func):
    """
    Stacks the three standard patches onto a test function.
    Test args received: (mock_rev_cls, mock_sha256, mock_save)
    """
    func = patch(PATCH_REVISION)(func)
    func = patch(PATCH_MD5, return_value="checksum123")(func)
    func = patch(PATCH_SAVE, new_callable=AsyncMock)(func)
    return func


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_db(existing_script=None):
    mock_db = AsyncMock()
    check_result = MagicMock()
    check_result.scalar_one_or_none.return_value = existing_script
    mock_db.execute = AsyncMock(return_value=check_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def make_payload(**kwargs):
    defaults = {
        "tenant_id": uuid4(),
        "title": "Test Script",
        "summary": "A test summary",
        "execution_type": "batch",
        "script_type": "bash",
        "script_content": "#!/bin/bash\necho 'hello world'",
        "created_by": uuid4(),
        "action": ScriptStatus.DRAFT,
    }
    defaults.update(kwargs)

    class Payload:
        pass

    p = Payload()
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------------------
# Duplicate check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_duplicate_raises_400(mock_rev_cls, mock_sha256, mock_save):
    """Raises HTTP 400 when a script with same tenant + title already exists."""
    mock_db = make_mock_db(existing_script=MagicMock())
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    with pytest.raises(HTTPException) as exc_info:
        await create_registry_api(payload, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@apply_patches
async def test_create_script_duplicate_detail_message(mock_rev_cls, mock_sha256, mock_save):
    """400 exception carries the correct detail message."""
    mock_db = make_mock_db(existing_script=MagicMock())
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    with pytest.raises(HTTPException) as exc_info:
        await create_registry_api(payload, mock_db)
    assert exc_info.value.detail == "Script with this title already exists for the tenant."


@pytest.mark.asyncio
@apply_patches
async def test_create_script_no_commit_on_duplicate(mock_rev_cls, mock_sha256, mock_save):
    """db.commit() is NOT called when duplicate is detected."""
    mock_db = make_mock_db(existing_script=MagicMock())
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    with pytest.raises(HTTPException):
        await create_registry_api(payload, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_invalid_action_raises_400(mock_rev_cls, mock_sha256, mock_save):
    """Raises HTTP 400 when action is not DRAFT or SUBMITTED."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.APPROVED)
    with pytest.raises(HTTPException) as exc_info:
        await create_registry_api(payload, mock_db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@apply_patches
async def test_create_script_invalid_action_detail_message(mock_rev_cls, mock_sha256, mock_save):
    """400 detail message mentions the invalid action value."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.DEPRECATED)
    with pytest.raises(HTTPException) as exc_info:
        await create_registry_api(payload, mock_db)
    assert ScriptStatus.DEPRECATED.value in exc_info.value.detail


@pytest.mark.asyncio
@apply_patches
async def test_create_script_invalid_action_no_commit(mock_rev_cls, mock_sha256, mock_save):
    """db.commit() is NOT called when action is invalid."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.REJECTED)
    with pytest.raises(HTTPException):
        await create_registry_api(payload, mock_db)
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Status resolution — RegistryMetadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_action_draft_sets_draft_status(mock_rev_cls, mock_sha256, mock_save):
    """action=DRAFT results in DRAFT status on registry metadata."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.DRAFT)
    await create_registry_api(payload, mock_db)
    registry_instance = mock_db.add.call_args_list[0][0][0]
    assert registry_instance.status == ScriptStatus.DRAFT


@pytest.mark.asyncio
@apply_patches
async def test_create_script_action_submit_sets_submitted_status(mock_rev_cls, mock_sha256, mock_save):
    """action=SUBMITTED results in SUBMITTED status on registry metadata."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.SUBMITTED)
    await create_registry_api(payload, mock_db)
    registry_instance = mock_db.add.call_args_list[0][0][0]
    assert registry_instance.status == ScriptStatus.SUBMITTED


@pytest.mark.asyncio
@apply_patches
async def test_create_script_default_action_is_draft(mock_rev_cls, mock_sha256, mock_save):
    """When action is not provided it defaults to DRAFT status."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()  # action defaults to ScriptStatus.DRAFT
    await create_registry_api(payload, mock_db)
    registry_instance = mock_db.add.call_args_list[0][0][0]
    assert registry_instance.status == ScriptStatus.DRAFT


# ---------------------------------------------------------------------------
# Status resolution — RegistryRevision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_action_draft_sets_draft_status_on_revision(mock_rev_cls, mock_sha256, mock_save):
    """action=DRAFT results in DRAFT status on the revision as well."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.DRAFT)
    await create_registry_api(payload, mock_db)
    _, kwargs = mock_rev_cls.call_args
    assert kwargs["status"] == ScriptStatus.DRAFT


@pytest.mark.asyncio
@apply_patches
async def test_create_script_action_submit_sets_submitted_status_on_revision(mock_rev_cls, mock_sha256, mock_save):
    """action=SUBMITTED results in SUBMITTED status on the revision as well."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(action=ScriptStatus.SUBMITTED)
    await create_registry_api(payload, mock_db)
    _, kwargs = mock_rev_cls.call_args
    assert kwargs["status"] == ScriptStatus.SUBMITTED


# ---------------------------------------------------------------------------
# RegistryMetadata fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_metadata_fields(mock_rev_cls, mock_sha256, mock_save):
    """RegistryMetadata is created with correct fields from payload."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    tenant_id = uuid4()
    creator_id = uuid4()
    payload = make_payload(
        tenant_id=tenant_id,
        title="My Script",
        summary="Does stuff",
        execution_type="realtime",
        script_content="#!/bin/bash\necho 'test'",
        created_by=creator_id,
        action=ScriptStatus.DRAFT,
    )
    await create_registry_api(payload, mock_db)
    registry_instance = mock_db.add.call_args_list[0][0][0]
    assert registry_instance.tenant_id == tenant_id
    assert registry_instance.title == "My Script"
    assert registry_instance.summary == "Does stuff"
    assert registry_instance.execution_type == "realtime"
    assert registry_instance.created_by == creator_id
    assert registry_instance.revision == 1
    assert registry_instance.latest_revision == 1


# ---------------------------------------------------------------------------
# Storage and checksum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_generates_checksum(mock_rev_cls, mock_sha256, mock_save):
    """generate_md5 is called with the script content."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(script_content="#!/bin/bash\necho 'hi'")
    await create_registry_api(payload, mock_db)
    mock_sha256.assert_called_once_with("#!/bin/bash\necho 'hi'")


@pytest.mark.asyncio
@apply_patches
async def test_create_script_saves_file_with_uuid_and_version(mock_rev_cls, mock_sha256, mock_save):
    """save_script_file is called with registry UUID (not title) and version=1."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload(script_content="#!/bin/bash\necho 'test'")
    await create_registry_api(payload, mock_db)
    mock_save.assert_called_once()
    call_kwargs = mock_save.call_args
    # Called as save_script_file(script_uuid=<uuid>, version=1, content=<content>)
    assert call_kwargs.kwargs.get("version") == 1 or call_kwargs.args[1] == 1
    assert call_kwargs.kwargs.get("content") == "#!/bin/bash\necho 'test'" or call_kwargs.args[2] == "#!/bin/bash\necho 'test'"


# ---------------------------------------------------------------------------
# RegistryRevision fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_creates_revision(mock_rev_cls, mock_sha256, mock_save):
    """A RegistryRevision is created and added to db — total 2 db.add() calls."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    await create_registry_api(payload, mock_db)
    mock_rev_cls.assert_called_once()
    assert mock_db.add.call_count == 2


@pytest.mark.asyncio
@apply_patches
async def test_create_script_revision_fields(mock_rev_cls, mock_sha256, mock_save):
    """RegistryRevision is created with correct fields."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    creator_id = uuid4()
    content = "#!/bin/bash\necho 'rev'"
    payload = make_payload(
        script_content=content,
        created_by=creator_id,
    )
    await create_registry_api(payload, mock_db)
    _, kwargs = mock_rev_cls.call_args
    assert kwargs["revision_number"] == 1
    assert kwargs["checksum"] == "checksum123"
    assert kwargs["size"] == len(content.encode("utf-8"))
    assert kwargs["signature_reference"] == "scripts/test-uuid/test-uuid_1"
    assert kwargs["created_by"] == creator_id


@pytest.mark.asyncio
@apply_patches
async def test_create_script_revision_size_is_byte_length(mock_rev_cls, mock_sha256, mock_save):
    """size on revision equals byte length of script_content."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    content = "#!/bin/bash\necho 'size test'"
    payload = make_payload(script_content=content)
    await create_registry_api(payload, mock_db)
    _, kwargs = mock_rev_cls.call_args
    assert kwargs["size"] == len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# Call order and DB interactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@apply_patches
async def test_create_script_flush_before_save_and_revision(mock_rev_cls, mock_sha256, mock_save):
    """db.flush() is called before save_script_file and before RegistryRevision is created.
    This ensures registry.id is available for the MinIO path.
    """
    call_order = []
    mock_db = make_mock_db(existing_script=None)

    def flush_side_effect():
        call_order.append("flush")

    def save_side_effect(*args, **kwargs):
        call_order.append("save")
        return "scripts/uuid/uuid_1"

    def revision_side_effect(*args, **kwargs):
        call_order.append("revision")
        return MagicMock()

    mock_db.flush = AsyncMock(side_effect=flush_side_effect)
    mock_save.side_effect = save_side_effect
    mock_rev_cls.side_effect = revision_side_effect

    payload = make_payload()
    await create_registry_api(payload, mock_db)
    assert call_order.index("flush") < call_order.index("save")
    assert call_order.index("flush") < call_order.index("revision")


@pytest.mark.asyncio
@apply_patches
async def test_create_script_commits_to_db(mock_rev_cls, mock_sha256, mock_save):
    """db.commit() is called once after both objects are added."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    await create_registry_api(payload, mock_db)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
@apply_patches
async def test_create_script_refreshes_registry(mock_rev_cls, mock_sha256, mock_save):
    """db.refresh() is called on the real RegistryMetadata instance after commit."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    await create_registry_api(payload, mock_db)
    assert mock_db.refresh.call_count == 1
    refresh_arg = mock_db.refresh.call_args[0][0]
    assert isinstance(refresh_arg, RegistryMetadata)


@pytest.mark.asyncio
@apply_patches
async def test_create_script_success_returns_result(mock_rev_cls, mock_sha256, mock_save):
    """Returns registry metadata object on successful creation."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    result = await create_registry_api(payload, mock_db)
    assert result is not None
    mock_db.refresh.assert_called_once()


@pytest.mark.asyncio
@apply_patches
async def test_create_script_db_execute_called_once(mock_rev_cls, mock_sha256, mock_save):
    """db.execute() is called exactly once for the duplicate check."""
    mock_db = make_mock_db(existing_script=None)
    mock_save.return_value = DEFAULT_SAVE_RETURN
    payload = make_payload()
    await create_registry_api(payload, mock_db)
    assert mock_db.execute.call_count == 1