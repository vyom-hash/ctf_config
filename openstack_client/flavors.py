# flavor fetch logic
import asyncio
from typing import List, Dict
from .connection import OpenStackConnectionManager
from .exceptions import OpenStackConnectionError
from openstack.exceptions import SDKException

class OpenStackFlavorService:
    """
    Service to fetch flavors from OpenStack.
    """

    @staticmethod
    async def list_flavors(project_name: str) -> List[Dict]:
        manager = await OpenStackConnectionManager.get_instance(project_name)
        conn = await manager.get_connection()

        def _fetch():
            return list(conn.compute.flavors())

        try:
            flavors = await asyncio.to_thread(_fetch)

        except SDKException as e:
            raise OpenStackConnectionError(str(e)) from e

        return [
            {
                "name": flavor.name,
                "vcpus": flavor.vcpus,
                "ram": flavor.ram,
                "disk": flavor.disk,
                "id": flavor.id,
            }
            for flavor in flavors
        ]