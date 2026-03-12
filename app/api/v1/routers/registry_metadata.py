# Router file for Scripts
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas.registry_metadata import (
    CreateScriptMetadataSchema,
    ScriptContentResponseSchema,
    ScriptDetailResponseSchema,
    ScriptListFilterSchema,
    ScriptListResponseSchema,
    ScriptMetadataResponseSchema,
    UpdateScriptSchema,
)
from app.core.database import get_db
from app.services.registry_metadata import (
    approve_registry_service,
    create_registry_api,
    delete_registry_service,
    deprecate_registry_service,
    get_registry_by_title_service,
    get_registry_detail_service,
    list_registry_service,
    update_registry_service,
)

router = APIRouter(prefix="/scripts", tags=["Scripts"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=ScriptMetadataResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_registry(payload: CreateScriptMetadataSchema, db: DB):
    """
    Create a new script along with its metadata and initial revision.
    - Validates uniqueness within tenant
    - Generates checksum
    - Stores metadata
    - Creates revision version 1
    """
    return await create_registry_api(payload, db)


@router.get("", response_model=ScriptListResponseSchema, status_code=status.HTTP_200_OK)
async def list_registry(filters: ScriptListFilterSchema, db:DB):
    """
    List scripts with optional filters and pagination.
    """
    return await list_registry_service(filters, db)


@router.get("/{registry_id}", response_model=ScriptContentResponseSchema, status_code=status.HTTP_200_OK)
async def get_registry_detail(registry_id: UUID, db: DB):
    """
    Get script details and current live revision content by ID.
    """
    return await get_registry_detail_service(registry_id, db)

@router.get("/{registry_id}", response_model=ScriptDetailResponseSchema, status_code=status.HTTP_200_OK)
async def get_registry_detail(registry_id: UUID, db: DB):
    """
    Get script details by ID.
    """
    return await get_registry_detail_service(registry_id, db)


@router.put("/{registry_id}", response_model=ScriptDetailResponseSchema, status_code=status.HTTP_200_OK)
async def update_registry(registry_id: UUID, payload: UpdateScriptSchema, db: DB):
    """
    Update script metadata and content.
    If content changes → new DRAFT revision created.
    Content goes live only after approval.
    """
    return await update_registry_service(registry_id, payload, db)


@router.post("/{registry_id}/deprecate", status_code=status.HTTP_200_OK)
async def deprecate_registry(registry_id: UUID, db: DB):
    """
    Deprecate a submitted or approved script.
    Only SUBMITTED or APPROVED scripts can be deprecated.
    """
    return await deprecate_registry_service(registry_id, db)


@router.post("/{registry_id}/approve", status_code=status.HTTP_200_OK)
async def approve_registry(registry_id: UUID, db: DB):
    """
    Approve or reject a script based on its current status.
    SUBMITTED → APPROVED
    DRAFT     → REJECTED
    """
    return await approve_registry_service(registry_id, db)


@router.delete("/{registry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registry(registry_id: UUID, db: DB):
    """
    Hard delete a script and all its revisions.
    Only DRAFT, REJECTED, or DEPRECATED scripts can be deleted.
    """
    await delete_registry_service(registry_id, db)


@router.get("/name/{title}", response_model=ScriptContentResponseSchema, status_code=status.HTTP_200_OK)
async def get_registry_by_title(title: str, tenant_id: UUID, db: DB):
    """
    Fetch a script by title within a tenant.
    Also retrieves the current live revision's content directly from MinIO.

    Query params:
      - tenant_id: UUID  (required — titles are unique per tenant, not globally)
    """
    return await get_registry_by_title_service(title, tenant_id, db)
