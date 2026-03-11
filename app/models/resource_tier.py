from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from sqlalchemy.sql import func

class ResourceTier(Base):
    __tablename__ = "resource_tiers"

    id = Column(UUID(as_uuid=True),primary_key=True,server_default=text("gen_random_uuid()"))
    tier_name = Column(String(80), nullable=False)
    description = Column(Text)
    # Compute specifications
    cpu_cores = Column(Integer, nullable=False)
    memory_mb = Column(Integer, nullable=False)
    storage_gb = Column(Integer, nullable=False)
    gpu_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    # Provider mapping (optional abstraction layer)
    provider_type = Column(String(100), nullable=False)   # openstack/aws/etc
    provider_reference = Column(String(255), nullable=False)
    region = Column(String(100))
    # Visibility & ownership
    access_scope = Column(String(20), nullable=False, server_default="global")  # global/private
    owner_tenant_id = Column(UUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    extra_metadata = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    tenant_allocations = relationship(
    "TenantResourceTierLimit",
    back_populates="resource_tier"
)

    __table_args__ = (
    UniqueConstraint(
        "owner_tenant_id",
        "tier_name",
        name="uq_resource_tier_tenant_name"
    ),
    UniqueConstraint(
    "provider_reference",
    name="uq_resource_tier_provider_ref"
)
)

class TenantResourceTierLimit(Base):
    __tablename__ = "tenant_resource_tier_limits"

    tenant_id = Column(UUID(as_uuid=True),primary_key=True)
    resource_tier_id = Column(UUID(as_uuid=True),ForeignKey("resource_tiers.id", ondelete="CASCADE"),primary_key=True)
    max_instances_allowed = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())

    # Relationships
    resource_tier = relationship(
        "ResourceTier",
        back_populates="tenant_allocations"
    )