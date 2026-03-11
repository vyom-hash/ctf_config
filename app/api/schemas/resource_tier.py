"""Flavour Profile schemas."""
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class CreateResourceTierSchema(BaseModel):
    """
    Schema for creating a new resource tier.
    """
    tier_name: str = Field(..., max_length=80)
    description: Optional[str] = None
    cpu_cores: int
    memory_mb: int
    storage_gb: int
    gpu_enabled: Optional[bool] = False
    provider_type: str
    provider_reference: str
    region: Optional[str] = None
    access_scope: Optional[str] = "global"
    owner_tenant_id: Optional[UUID] = None


class ReplaceResourceTierSchema(BaseModel):
    """
    Full replacement schema for resource tier.
    All required fields must be present.
    """
    tier_name: str
    description: Optional[str] = None
    cpu_cores: int
    memory_mb: int
    storage_gb: int
    gpu_enabled: bool
    provider_type: str
    provider_reference: str
    region: Optional[str] = None
    access_scope: str
    is_active: bool

class PatchResourceTierSchema(BaseModel):
    """
    Schema for partially updating a resource tier.
    All fields are optional.
    """
    tier_name: Optional[str] = None
    description: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_mb: Optional[int] = None
    storage_gb: Optional[int] = None
    gpu_enabled: Optional[bool] = None
    provider_type: Optional[str] = None
    provider_reference: Optional[str] = None
    region: Optional[str] = None
    access_scope: Optional[str] = None
    is_active: Optional[bool] = None

class ResourceTierResponseSchema(BaseModel):
    """
    Response schema for resource tier.
    """
    id: UUID
    tier_name: str
    description: Optional[str]=None
    cpu_cores: int
    memory_mb: int
    storage_gb: int
    gpu_enabled: bool
    provider_type: str
    provider_reference: str
    region: Optional[str]=None
    access_scope: str
    is_active: bool

    class Config:
        from_attributes = True