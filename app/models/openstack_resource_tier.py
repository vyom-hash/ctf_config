from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.core.database import Base



class OpenStackResourceTier(Base):
    __tablename__ = "openstack_resource_tier"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    vcpus = Column(Integer, nullable=False)
    ram = Column(Integer, nullable=False)
    disk = Column(Integer, nullable=False)
    region = Column(String)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime(timezone=True))