from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

class ScriptFileType(str, Enum):
    BASH = "bash"

class ScriptStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class CreateScriptMetadataSchema(BaseModel):
    """
    Schema to create a new script along with its metadata.
    """
    title: str = Field(..., max_length=255)
    summary: Optional[str] = None
    execution_type: str = Field(..., max_length=50)
    script_type: ScriptFileType  # bash
    script_content: str = Field(..., min_length=1)
    # TODO: Remove tenant_id and created_by once user management is implemented.
    tenant_id: UUID
    created_by: UUID
    action: ScriptStatus = ScriptStatus.DRAFT  # defaults to draft if not provided


class ScriptMetadataResponseSchema(BaseModel):
    """
    Response schema for script creation.
    """
    id: UUID
    title: str
    execution_type: str
    revision: int
    latest_revision: int
    status: str

    class Config:
        from_attributes = True


class UpdateScriptSchema(BaseModel):
    """
    Schema to update script metadata and content.
    Only metadata fields can be updated — content versioning
    is handled via new revision creation.
    """
    title: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = None
    execution_type: Optional[str] = Field(None, max_length=50)
    script_content: Optional[str] = None


class ScriptListFilterSchema(BaseModel):
    # TODO: tenant_id will be inferred from auth token once user management is implemented.
    tenant_id: Optional[UUID] = None
    execution_type: Optional[str] = None
    status: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class ScriptDetailResponseSchema(BaseModel):
    id: UUID
    title: str
    summary: Optional[str] = None
    execution_type: str
    revision: int
    latest_revision: int
    status: str
    checksum: str
    signature_reference: Optional[str] = None
    deprecated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ScriptListResponseSchema(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ScriptDetailResponseSchema]


class ScriptContentResponseSchema(BaseModel):
    id: UUID
    title: str
    summary: str
    execution_type: str
    revision: int
    latest_revision: int
    status: str
    checksum: str
    signature_reference: str
    deprecated_at: datetime
    script_content: str         
    
    class Config:
        from_attributes = True

