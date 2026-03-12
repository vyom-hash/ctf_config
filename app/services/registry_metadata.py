# Service file for Scripts
from datetime import datetime, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from fastapi import HTTPException, status
from app.api.schemas.registry_metadata import ScriptStatus
from app.core.minio import delete_script_files, get_script_file, save_script_file
from app.core.utils import generate_md5
from app.models.registry_metadata import RegistryMetadata, RegistryRevision

logger = logging.getLogger(__name__)

SCRIPT_NOT_FOUND="Script not found."

async def create_registry_api(payload, db: AsyncSession):
    """
    Creates a new registry entry along with its initial revision.
    Status is determined by payload.action:
      action=DRAFT     → status DRAFT
    # TODO: Add user authorization check once user management is implemented.
    """
    # Validate action
    if payload.action not in {ScriptStatus.DRAFT, ScriptStatus.SUBMITTED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{payload.action.value}'. Script can only be created as draft or submitted."
        )

    # Check if script already exists for same tenant + title
    existing_query = await db.execute(
        select(RegistryMetadata).where(
            RegistryMetadata.tenant_id == payload.tenant_id,
            RegistryMetadata.title == payload.title
        )
    )
    if existing_query.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Script with this title already exists for the tenant."
        )

    resolved_status = payload.action

    # Generate checksum and compute size before any DB/storage writes
    checksum = generate_md5(payload.script_content)
    size = len(payload.script_content.encode("utf-8"))

    # Create RegistryMetadata first — need UUID for MinIO path
    registry = RegistryMetadata(
        tenant_id=payload.tenant_id,
        title=payload.title,
        summary=payload.summary,
        execution_type=payload.execution_type,
        revision=1,
        latest_revision=1,
        status=resolved_status,
        created_by=payload.created_by,
    )
    db.add(registry)
    await db.flush()  

    # Upload to MinIO: <bucket>/<registry_uuid>/<registry_uuid>_<version>
    object_path = await save_script_file(
        script_uuid=str(registry.id),
        version=1,
        content=payload.script_content,
    )

    # Create initial revision
    revision = RegistryRevision(
        registry_id=registry.id,
        revision_number=1,
        size=size,
        signature_reference=object_path,
        checksum=checksum,
        status=resolved_status,
        created_by=payload.created_by,
    )
    db.add(revision)

    await db.commit()
    await db.refresh(registry)
    return registry


async def update_registry_service(registry_id, payload, db: AsyncSession):
    """
    Updates registry metadata and creates a new DRAFT revision if content changes.

    Version management:
      - `revision`        → the current APPROVED/live version. Never changed here.
      - `latest_revision` → the latest revision number (may be a draft pending approval).

    When script_content changes:
      - A new RegistryRevision is created in DRAFT status.
      - Only `latest_revision` is incremented on RegistryMetadata.
      - `revision` is left untouched — it is only promoted in approve_registry_service
        once the new revision is reviewed and approved.
    """
    query = await db.execute(
        select(RegistryMetadata).where(RegistryMetadata.id == registry_id)
    )
    registry = query.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCRIPT_NOT_FOUND
        )

    # Update metadata fields if provided
    if payload.title is not None:
        registry.title = payload.title

    if payload.summary is not None:
        registry.summary = payload.summary

    if payload.execution_type is not None:
        registry.execution_type = payload.execution_type

    # If script content updated → create a new DRAFT revision
    if payload.script_content:
        new_revision_number = registry.latest_revision + 1

        checksum = generate_md5(payload.script_content)
        size = len(payload.script_content.encode("utf-8"))

        # Upload new version to MinIO — await required, save_script_file is async
        object_path = await save_script_file(
            script_uuid=str(registry.id),
            version=new_revision_number,
            content=payload.script_content,
        )

        # Only latest_revision moves forward — revision (live version) stays unchanged
        registry.latest_revision = new_revision_number

        # New revision always starts as DRAFT — requires approval to go live
        revision = RegistryRevision(
            registry_id=registry.id,
            revision_number=new_revision_number,
            size=size,
            signature_reference=object_path,
            checksum=checksum,
            status=ScriptStatus.DRAFT,
            created_by=registry.created_by,
        )
        db.add(revision)

    await db.commit()
    await db.refresh(registry)
    return registry


async def list_registry_service(filters, db: AsyncSession):
    """
    Returns paginated list of registry entries with optional filtering.
    """
    base_query = select(RegistryMetadata)

    if filters.tenant_id:
        base_query = base_query.where(
            RegistryMetadata.tenant_id == filters.tenant_id
        )

    if filters.execution_type:
        base_query = base_query.where(
            RegistryMetadata.execution_type == filters.execution_type
        )

    if filters.status:
        base_query = base_query.where(
            RegistryMetadata.status == filters.status
        )

    # Total count
    total_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = total_result.scalar()

    # Pagination
    offset = (filters.page - 1) * filters.page_size
    result = await db.execute(
        base_query
        .offset(offset)
        .limit(filters.page_size)
        .order_by(RegistryMetadata.created_at.desc())
    )
    items = result.scalars().all()

    return {
        "total": total,
        "page": filters.page,
        "page_size": filters.page_size,
        "items": items,
    }

async def get_registry_detail_service(registry_id, db: AsyncSession):
    """
    Fetch registry metadata by ID, including the current live revision's
    script content fetched directly from MinIO.
    """
    result = await db.execute(
        select(RegistryMetadata).where(RegistryMetadata.id == registry_id)
    )
    registry = result.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCRIPT_NOT_FOUND,
        )

    revision_result = await db.execute(
        select(RegistryRevision).where(
            RegistryRevision.registry_id == registry.id,
            RegistryRevision.revision_number == registry.revision,
        )
    )
    revision = revision_result.scalar_one_or_none()

    if not revision or not revision.signature_reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Script revision or file reference not found.",
        )

    #fetch content from MinIO using signature_reference
    script_content = await get_script_file(revision.signature_reference)

    return {
        "id": registry.id,
        "title": registry.title,
        "summary": registry.summary,
        "execution_type": registry.execution_type,
        "revision": registry.revision,
        "latest_revision": registry.latest_revision,
        "status": registry.status,
        "checksum": revision.checksum,
        "signature_reference": revision.signature_reference,
        "deprecated_at": registry.deprecated_at,
        "script_content": script_content,
    }


async def deprecate_registry_service(registry_id, db: AsyncSession):
    """
    Transitions a script status to DEPRECATED.
    Only scripts in SUBMITTED or APPROVED status can be deprecated.
    # TODO: Add user authorization check once user management is implemented.
    """
    result = await db.execute(
        select(RegistryMetadata).where(RegistryMetadata.id == registry_id)
    )
    registry = result.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCRIPT_NOT_FOUND,
        )
    try:
        current_status = ScriptStatus(registry.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scripts with status '{registry.status}' cannot be deprecated.",
        )

    if current_status not in {ScriptStatus.SUBMITTED, ScriptStatus.APPROVED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scripts with status '{registry.status}' cannot be deprecated. Only submitted or approved scripts can be deprecated.",
        )

    registry.status = ScriptStatus.DEPRECATED
    registry.deprecated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Script deprecated successfully."}


async def delete_registry_service(registry_id, db: AsyncSession):
    """
    Permanently deletes a script and all associated revisions.
    Also cleans up all MinIO objects under the script's UUID prefix.
    # TODO: Add user authorization check once user management is implemented.
    """
    result = await db.execute(
        select(RegistryMetadata).where(RegistryMetadata.id == registry_id)
    )
    registry = result.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCRIPT_NOT_FOUND,
        )
    try:
        current_status = ScriptStatus(registry.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scripts with status '{registry.status}' cannot be deleted.",
        )

    if current_status not in {ScriptStatus.DRAFT, ScriptStatus.REJECTED, ScriptStatus.DEPRECATED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scripts with status '{registry.status}' cannot be deleted.",
        )

    # Status validated — safe to delete
    await db.delete(registry)
    await db.commit()

    # Clean up MinIO objects after successful DB delete
    await delete_script_files(script_uuid=str(registry_id))


async def approve_registry_service(registry_id, db: AsyncSession):
    """
    Transitions a script status:
      SUBMITTED → APPROVED
    APPROVED returns early. REJECTED and DEPRECATED raise 400.
    # TODO: Add approver user_id parameter and store approved_by / rejected_by
            once user management is implemented.
    """
    result = await db.execute(
        select(RegistryMetadata).where(RegistryMetadata.id == registry_id)
    )
    registry = result.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCRIPT_NOT_FOUND,
        )

    # Cast to enum — model stores status as plain String
    try:
        current_status = ScriptStatus(registry.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Script with status '{registry.status}' cannot be processed for approval.",
        )

    if current_status == ScriptStatus.APPROVED:
        return {"message": "Script is already in approved state."}

    if current_status in {ScriptStatus.REJECTED, ScriptStatus.DEPRECATED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Script with status '{registry.status}' cannot be processed for approval.",
        )

    original_status = registry.status

    if current_status == ScriptStatus.SUBMITTED:
        registry.status = ScriptStatus.APPROVED
        message = "Script approved successfully."
    else:
        # DRAFT falls here
        registry.status = ScriptStatus.REJECTED
        message = f"Script cannot be approved from '{original_status}' status and has been rejected."

    await db.commit()
    return {"message": message}


async def get_registry_by_title_service(title: str, tenant_id, db: AsyncSession):
    """
    Fetches registry metadata by title + tenant_id, and retrieves the
    current revision's script content directly from MinIO.

    Returns a dict containing the registry metadata and script_content.
    """
    #find registry by title within tenant
    result = await db.execute(
        select(RegistryMetadata).where(
            RegistryMetadata.tenant_id == tenant_id,
            RegistryMetadata.title == title,
        )
    )
    registry = result.scalar_one_or_none()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Script not found.",
        )

    revision_result = await db.execute(
        select(RegistryRevision).where(
            RegistryRevision.registry_id == registry.id,
            RegistryRevision.revision_number == registry.revision,
        )
    )
    revision = revision_result.scalar_one_or_none()

    if not revision or not revision.signature_reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Script revision or file reference not found.",
        )

    #fetch content from MinIO using signature_reference
    script_content = await get_script_file(revision.signature_reference)

    return {
        "id": registry.id,
        "title": registry.title,
        "summary": registry.summary,
        "execution_type": registry.execution_type,
        "revision": registry.revision,
        "latest_revision": registry.latest_revision,
        "status": registry.status,
        "checksum": revision.checksum,
        "signature_reference": revision.signature_reference,
        "deprecated_at": registry.deprecated_at,
        "script_content": script_content,
    }
