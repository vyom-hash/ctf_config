from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class RegistryMetadata(Base):
    """
    Stores metadata information about executable scripts.
    Acts as the primary registry entry for a script artifact.
    """
    __tablename__ = "registry_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    # TODO: Add ForeignKey("tenants.id", ondelete="CASCADE") once tenant model is implemented
    tenant_id = Column(UUID(as_uuid=True), nullable=False)

    title = Column(String(255), nullable=False)
    summary = Column(String, nullable=True)
    execution_type = Column(String(50), nullable=False)
    revision = Column(Integer, server_default="1", nullable=False)
    latest_revision = Column(Integer, nullable=False)
    status = Column(String(50), server_default="draft", nullable=False)

    # TODO: Add ForeignKey("users.id", ondelete="CASCADE") once user model is implemented
    created_by = Column(UUID(as_uuid=True), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deprecated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    revisions = relationship(
        "RegistryRevision",
        back_populates="registry",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "title", name="uq_registry_tenant_title"),
        Index("idx_registry_tenant_id", "tenant_id"),
        Index("idx_registry_status", "status"),
        Index("idx_registry_execution_type", "execution_type"),
    )

    def __repr__(self):
        return f"<RegistryMetadata id={self.id} title={self.title} status={self.status}>"


class RegistryRevision(Base):
    """
    Stores versioned metadata and execution configuration for a script.
    Each revision represents a specific immutable artifact version.
    """
    __tablename__ = "registry_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    registry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("registry_metadata.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number = Column(Integer, nullable=False)
    size = Column(Integer, nullable=False)
    signature_reference = Column(String(500), nullable=True)
    checksum = Column(String(32), nullable=False)
    status = Column(String(50), server_default="draft", nullable=False)

    # TODO: Add ForeignKey("users.id", ondelete="CASCADE") once user model is implemented
    created_by = Column(UUID(as_uuid=True), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    registry = relationship("RegistryMetadata", back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("registry_id", "revision_number", name="uq_registry_revision_number"),
        Index("idx_revision_registry_id", "registry_id"),
        Index("idx_revision_status", "status"),
    )

    def __repr__(self):
        return f"<RegistryRevision id={self.id} registry_id={self.registry_id} revision_number={self.revision_number}>"