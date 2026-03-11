import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone
from openstack.connection import Connection
from openstack.exceptions import SDKException
from app.core.config import settings
from .exceptions import OpenStackConnectionError

logger = logging.getLogger(__name__)


class OpenStackConnectionManager:
    """
    Singleton OpenStack connection manager per project.

    - Caches connection per project
    - Validates Keystone token expiry
    - Refreshes connection automatically when expired
    - Thread-safe & async-safe
    """
    _instances: Dict[str, "OpenStackConnectionManager"] = {}
    _global_lock = asyncio.Lock()

    def __init__(self, project_name: str):
        self.project_name = project_name.lower()
        self._conn: Optional[Connection] = None
        self._lock = asyncio.Lock()

    # Singleton factory per project
    @classmethod
    async def get_instance(cls, project_name: str):
        project_name = project_name.lower()

        async with cls._global_lock:
            if project_name not in cls._instances:
                cls._instances[project_name] = cls(project_name)

            return cls._instances[project_name]

    # Create connection (sync → executed in thread)
    def _create_connection_sync(self) -> Connection:
        conn = Connection(
            auth_url=settings.OPENSTACK_AUTH_URL,
            username=settings.OPENSTACK_USERNAME,
            password=settings.OPENSTACK_PASSWORD,
            project_name=self.project_name,
            user_domain_name=settings.OPENSTACK_USER_DOMAIN_NAME,
            project_domain_name=settings.OPENSTACK_PROJECT_DOMAIN_NAME,
            region_name=settings.OPENSTACK_REGION_NAME,
        )

        conn.authorize()
        return conn

    # Token expiry validation
    def _is_token_expired(self, conn: Connection) -> bool:
        """
        Returns True if Keystone token is expired or invalid.
        """
        try:
            access_info = conn.session.auth.get_access(conn.session)
            expires_at = access_info.expires_at

            if not expires_at:
                return True

            # Convert to timezone-aware datetime
            expiry_time = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )

            return datetime.now(timezone.utc) >= expiry_time

        except Exception:
            logger.warning(
                "Unable to validate OpenStack token. Forcing refresh (project=%s)",
                self.project_name,
                exc_info=True,
            )
            return True  

    # Public async accessor
    async def get_connection(self) -> Connection:
        """
        Returns valid OpenStack connection.
        Automatically refreshes if token expired.
        """
        if self._conn and not self._is_token_expired(self._conn):
            return self._conn

        # Slow path with lock
        async with self._lock:
            if self._conn and not self._is_token_expired(self._conn):
                return self._conn

            try:
                self._conn = await asyncio.to_thread(
                    self._create_connection_sync
                )

                logger.info(
                    "OpenStack connection (re)established (project=%s)",
                    self.project_name,
                )

                return self._conn

            except SDKException as e:
                logger.exception(
                    "OpenStack SDK error (project=%s)",
                    self.project_name,
                )
                raise OpenStackConnectionError(str(e)) from e