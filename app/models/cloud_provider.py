from __future__ import annotations

import enum
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import String, Enum, JSON, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class ProviderType(enum.Enum):
    OPENSTACK = "OPENSTACK"


class CloudProvider(Base):
    __tablename__ = "cloud_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    type: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, name="provider_type_enum"),
        nullable=False,
    )

    endpoint: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    credentials: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    provider_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
