from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from app.models.openstack_resource_tier import OpenStackResourceTier
from openstack_client.exceptions import OpenStackConnectionError
from openstack_client.flavors import OpenStackFlavorService

logger = logging.getLogger(__name__)

class OpenStackSyncService:

    @staticmethod
    async def sync_flavors(db: AsyncSession, region: str):
        """
        Sync OpenStack flavors into local database.
        - If region has no data → populate all
        - Otherwise → upsert + deactivate removed flavors
        """
        try:
            flavors = await OpenStackFlavorService.list_flavors(region)

        except OpenStackConnectionError as e:
            logger.error(f"OpenStack sync failed {e}", exc_info=True)
            return

        result = await db.execute(
            select(OpenStackResourceTier).where(
                OpenStackResourceTier.region == region
            )
        )
        existing_flavors = result.scalars().all()

        #Table empty for region (Bootstrap)
        if not existing_flavors:
            logger.info(f"Bootstrapping flavors for region {region}")

            for flavor in flavors:
                db.add(
                    OpenStackResourceTier(
                        id=flavor["id"],
                        name=flavor["name"],
                        vcpus=flavor["vcpus"],
                        ram=flavor["ram"],
                        disk=flavor["disk"],
                        region=region,
                        is_active=True,
                        last_synced_at=datetime.now(timezone.utc),
                    )
                )

            await db.commit()
            logger.info(f"Initial flavor population completed for region {region}")
            return

        #CASE 2 — Normal Sync
        existing_map = {f.id: f for f in existing_flavors}
        incoming_ids = set()

        for flavor in flavors:
            flavor_id = flavor["id"]
            incoming_ids.add(flavor_id)

            if flavor_id in existing_map:
                db_flavor = existing_map[flavor_id]
                db_flavor.name = flavor["name"]
                db_flavor.vcpus = flavor["vcpus"]
                db_flavor.ram = flavor["ram"]
                db_flavor.disk = flavor["disk"]
                db_flavor.is_active = True
                db_flavor.last_synced_at = datetime.now(timezone.utc)
            else:
                db.add(
                    OpenStackResourceTier(
                        id=flavor_id,
                        name=flavor["name"],
                        vcpus=flavor["vcpus"],
                        ram=flavor["ram"],
                        disk=flavor["disk"],
                        region=region,
                        is_active=True,
                        last_synced_at=datetime.now(timezone.utc),
                    )
                )
        # Mark missing flavors inactive
        for flavor_id, db_flavor in existing_map.items():
            if flavor_id not in incoming_ids:
                db_flavor.is_active = False
                db_flavor.last_synced_at = datetime.now(timezone.utc)

        await db.commit()

        logger.info(f"OpenStack flavor sync completed successfully for region {region}")