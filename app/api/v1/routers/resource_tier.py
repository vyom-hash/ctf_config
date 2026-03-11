from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, status
from app.core.database import get_db
from app.services.resource_tier import (
    create_resource_tier_api,
    delete_resource_tier_api,
    get_resource_tier_api,
    list_resource_tiers_api,
    patch_resource_tier_api,
    update_resource_tier_api,
)
from app.api.schemas.resource_tier import (
    CreateResourceTierSchema,
    PatchResourceTierSchema,
    ReplaceResourceTierSchema,
    ResourceTierResponseSchema,)

router = APIRouter(prefix="/resource-tier",tags=["Flavours"],)

DB = Annotated[AsyncSession, Depends(get_db)]

@router.post("/", response_model=ResourceTierResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_resource_tier_router(payload: CreateResourceTierSchema,db: DB):
    """
    Create a new Resource Tier.

    This endpoint creates a resource tier entry in the system.
    During creation:
    - The system attempts to match an existing OpenStack flavor.
    - If a matching flavor is found, its ID is reused as the provider reference.
    - If OpenStack validation fails, creation proceeds without blocking.

    Returns:
        ResourceTierResponseSchema: The created resource tier.

    Raises:
        409: If a resource tier with the same provider reference already exists.
        500: If creation fails due to an unexpected error.
    """
    return await create_resource_tier_api(payload, db)


@router.get("/", response_model=list[ResourceTierResponseSchema],status_code=status.HTTP_200_OK)
async def list_resource_tiers_router(db: DB, page: int = 1,size: int = 10):
    """
    List active Resource Tiers with pagination.

    This endpoint retrieves active resource tiers using page-based pagination.

    Query Parameters:
        page (int): Page number (default: 1)
        size (int): Number of records per page (default: 10)

    Returns:
        List[ResourceTierResponseSchema]: A list of active resource tiers.
    """
    return await list_resource_tiers_api(page, size, db)

@router.get("/{resource_tier_id}",response_model=ResourceTierResponseSchema,status_code=status.HTTP_200_OK)
async def get_resource_tier_router(resource_tier_id: UUID,db: DB):
    """
    Get a specific active Resource Tier by ID.

    Path Parameters:
        tier_id (int): ID of the resource tier.

    Returns:
        ResourceTierResponseSchema: The requested resource tier.
    """
    return await get_resource_tier_api(resource_tier_id, db)

@router.put("/{resource_tier_id}", response_model=ResourceTierResponseSchema,status_code=status.HTTP_200_OK)
async def update_resource_tier_router(resource_tier_id: UUID,payload: ReplaceResourceTierSchema,db:DB):
    """
    Fully replace an existing Resource Tier.

    This endpoint performs a complete replacement of the resource tier.
    All fields must be provided in the request body.

    Path Parameters:
        resource_tier_id (str): Unique identifier of the resource tier.

    Returns:
        ResourceTierResponseSchema: The updated resource tier.

    Raises:
        404: If the resource tier does not exist or is inactive.
        409: If a duplicate tier name or provider reference is detected.
    """
    return await update_resource_tier_api(resource_tier_id, payload, db)


@router.patch("/{resource_tier_id}", response_model=ResourceTierResponseSchema,status_code=status.HTTP_200_OK)
async def patch_resource_tier_router(resource_tier_id: UUID,payload: PatchResourceTierSchema,db: DB):
    """
    Partially update an existing Resource Tier.

    This endpoint updates only the fields provided in the request body.
    Fields not included remain unchanged.

    Path Parameters:
        resource_tier_id (str): Unique identifier of the resource tier.

    Behavior:
        - At least one field must be provided.
        - Duplicate provider references are not allowed.

    Returns:
        ResourceTierResponseSchema: The updated resource tier.

    Raises:
        400: If no fields are provided in the request body.
        404: If the resource tier does not exist or is inactive.
        409: If a duplicate provider reference is detected.
        500: If an unexpected error occurs.
    """
    return await patch_resource_tier_api(resource_tier_id, payload, db)


@router.delete("/{resource_tier_id}",status_code=status.HTTP_200_OK)
async def delete_resource_tier_router(resource_tier_id: UUID,db: DB):
    """
    Partially update an existing Resource Tier.

    This endpoint updates only the fields provided in the request body.
    Fields not included remain unchanged.

    Path Parameters:
        resource_tier_id (str): Unique identifier of the resource tier.

    Behavior:
        - At least one field must be provided.
        - Duplicate provider references are not allowed.

    Returns:
        ResourceTierResponseSchema: The updated resource tier.

    Raises:
        400: If no fields are provided in the request body.
        404: If the resource tier does not exist or is inactive.
        409: If a duplicate provider reference is detected.
        500: If an unexpected error occurs.
    """
    return await delete_resource_tier_api(resource_tier_id, db)