from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID

class ScriptFileType(str, Enum):
    bash = "bash"
    python = "python"

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

    category: Optional[str] = Field(None, max_length=50)
    execution_type: str = Field(..., max_length=50)

    script_type: ScriptFileType  # bash or python
    script_content: str = Field(..., min_length=1)

    tenant_id: UUID
    created_by: UUID

    # Optional execution metadata (for revision)
    input_schema: Optional[Dict[str, Any]] = None
    runtime_requirements: Optional[Dict[str, Any]] = None
    compatibility_matrix: Optional[Dict[str, Any]] = None
    execution_timeout_ms: Optional[int] = None
    retry_policy: Optional[Dict[str, Any]] = None


class ScriptMetadataResponseSchema(BaseModel):
    id: UUID
    title: str
    category: Optional[str]=None
    execution_type: str
    script_type: ScriptFileType
    current_version: int
    status: str

class UpdateScriptSchema(BaseModel):
    """
    Schema to update script metadata and content.
    """

    title: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    execution_type: Optional[str] = Field(None, max_length=50)

    script_content: Optional[str] = None

    input_schema: Optional[Dict[str, Any]] = None
    runtime_requirements: Optional[Dict[str, Any]] = None
    compatibility_matrix: Optional[Dict[str, Any]] = None
    execution_timeout_ms: Optional[int] = None
    retry_policy: Optional[Dict[str, Any]] = None


class ScriptListFilterSchema(BaseModel):
    tenant_id: Optional[UUID] = None
    category: Optional[str] = None
    execution_type: Optional[str] = None
    status: Optional[str] = None


class ScriptDetailResponseSchema(BaseModel):
    id: UUID
    title: str
    summary: Optional[str]=None
    category: Optional[str]=None
    execution_type: str
    current_version: int
    new_version: Optional[int]=None
    status: str
    checksum_sha256: str
    artifact_location: str

    class Config:
        from_attributes = True
