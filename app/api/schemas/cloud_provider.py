from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from app.models.cloud_provider import ProviderType


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CloudProviderCreate(_Base):
    type: ProviderType
    endpoint: str = Field(..., max_length=512)
    credentials: Dict[str, Any]
    provider_key: str = Field(..., max_length=255)


class CloudProviderResponse(_Base):
    id: int
    type: ProviderType
    endpoint: str
    credentials: Dict[str, Any]
    provider_key: str
    created_at: datetime
