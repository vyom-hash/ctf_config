"""Flavour Profile service """
import logging
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas.resource_tier import CreateResourceTierSchema, PatchResourceTierSchema, ReplaceResourceTierSchema
from app.models.openstack_resource_tier import OpenStackResourceTier
from app.models.resource_tier import ResourceTier
from uuid import UUID

logger = logging.getLogger(__name__)


async def create_resource_tier_api(payload: CreateResourceTierSchema,db: AsyncSession,):
    """
    Create a resource tier.

    If a matching OpenStack flavor exists,
    reuse its ID as provider_reference.
    Otherwise create normally.
    """
    try:
        resource_data = payload.model_dump(exclude_none=True)

        # Try to find best matching OpenStack flavor (minimum greater-or-equal match)
        result = await db.execute(
            select(OpenStackResourceTier)
            .where(
                OpenStackResourceTier.vcpus >= payload.cpu_cores,
                OpenStackResourceTier.ram >= payload.memory_mb,
                OpenStackResourceTier.disk >= payload.storage_gb,
                OpenStackResourceTier.region == payload.region,
                OpenStackResourceTier.is_active.is_(True)
            )
            .order_by(
                OpenStackResourceTier.vcpus.asc(),
                OpenStackResourceTier.ram.asc(),
                OpenStackResourceTier.disk.asc(),
            )
            .limit(1)
        )
        flavor = result.scalar_one_or_none()

        if flavor:
            resource_data["provider_reference"] = flavor.id
            resource_data["provider_type"] = "openstack"

        # Create DB record
        resource_tier = ResourceTier(**resource_data)
        db.add(resource_tier)
        await db.flush()
        await db.commit()
        await db.refresh(resource_tier)

        return resource_tier

    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"Integrity error while creating resource tier: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=409,
            detail="Resource tier with same provider reference already exists",
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to create resource tier: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to create resource tier",
        )
    
async def update_resource_tier_api(resource_tier_id: UUID,payload: ReplaceResourceTierSchema,db: AsyncSession):
    """
    Full replacement of a resource tier.

    Omitted fields are not allowed.
    """
    tier = await db.get(ResourceTier, resource_tier_id)

    if not tier or not tier.is_active:
        raise HTTPException(
            status_code=404,
            detail=f"Resource tier with id '{resource_tier_id}' not found",
        )

    # Replace all fields explicitly
    tier.tier_name = payload.tier_name
    tier.description = payload.description
    tier.cpu_cores = payload.cpu_cores
    tier.memory_mb = payload.memory_mb
    tier.storage_gb = payload.storage_gb
    tier.gpu_enabled = payload.gpu_enabled
    tier.provider_type = payload.provider_type
    tier.provider_reference = payload.provider_reference
    tier.region = payload.region
    tier.access_scope = payload.access_scope
    tier.is_active = payload.is_active

    try:
        await db.flush()
        await db.commit()
        await db.refresh(tier)
        return tier

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Duplicate tier name or provider reference detected"
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to update resource tier: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to update resource tier",
        )
        
async def patch_resource_tier_api(resource_tier_id: UUID,payload: PatchResourceTierSchema,db: AsyncSession):
    """
    API for partial update of a resource tier.

    Merge semantics:
    - Only provided fields are updated
    - Other fields remain unchanged
    """
    tier = await db.get(ResourceTier, resource_tier_id)

    if not tier or not tier.is_active:
        raise HTTPException(
            status_code=404,
            detail=f"Resource tier with id '{resource_tier_id}' not found",
        )

    update_data = payload.model_dump(exclude_unset=True)

    # Reject empty PATCH body
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for partial update"
        )

    for field, value in update_data.items():
        setattr(tier, field, value)

    try:
        await db.commit()
        await db.refresh(tier)

        return tier

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Duplicate provider reference detected"
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to patch resource tier: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to update resource tier"
        )
    
async def list_resource_tiers_api(page: int, size: int, db: AsyncSession):
    offset = (page - 1) * size

    result = await db.execute(
        select(ResourceTier)
        .where(ResourceTier.is_active == True)
        .offset(offset)
        .limit(size)
    )

    tiers = result.scalars()
    return tiers.all()

async def get_resource_tier_api(tier_id: UUID, db: AsyncSession):
    result = await db.execute(
        select(ResourceTier).where(
            ResourceTier.id == tier_id,
            ResourceTier.is_active == True,
        )
    )
    tier = result.scalar_one_or_none()

    if not tier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource tier not found",
        )
    return tier

async def delete_resource_tier_api(resource_tier_id: UUID,db: AsyncSession):
    """
    API for soft deletion of a resource tier.

    Instead of permanently deleting the record,
    the resource tier is marked as inactive.
    """
    tier = await db.get(ResourceTier, resource_tier_id)

    if not tier:
        raise HTTPException(
            status_code=404,
            detail=f"Resource tier with id '{resource_tier_id}' not found",
        )
    # Prevent duplicate soft delete
    if not tier.is_active:
        raise HTTPException(
            status_code=400,
            detail="Resource tier is already inactive"
        )

    tier.is_active = False

    try:
        await db.commit()
        return {"message": "Resource tier deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to soft delete resource tier: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to delete resource tier"
        )
    
 