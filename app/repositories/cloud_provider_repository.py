from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cloud_provider import CloudProvider


class CloudProviderRepository:
    """All DB operations for cloud providers."""

    async def create_provider(
        self,
        session: AsyncSession,
        *,
        type: str,
        endpoint: str,
        credentials: dict,
        provider_key: str,
    ) -> CloudProvider:
        provider = CloudProvider(
            type=type,
            endpoint=endpoint,
            credentials=credentials,
            provider_key=provider_key,
        )
        session.add(provider)
        await session.flush()
        return provider

    async def get_provider_by_id(
        self, session: AsyncSession, provider_id: int
    ) -> Optional[CloudProvider]:
        result = await session.execute(
            select(CloudProvider).where(CloudProvider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_provider_by_key(
        self, session: AsyncSession,
        provider_key: str
    ) -> Optional[CloudProvider]:
        result = await session.execute(
            select(CloudProvider).where(CloudProvider.provider_key == provider_key)
        )
        return result.scalar_one_or_none()
