"""
Pytest configuration and shared fixtures.

Production-grade: isolated tests, deterministic data, no global state.
SonarQube: run with pytest-cov to generate coverage (e.g. --cov=app --cov-report=xml).
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Patch Redis so lifespan does not connect (same object as main imports)
# Also disable SKIP_USER_AUTH so that auth tests properly return 401
@pytest.fixture(autouse=True, scope="session")
def _no_redis_in_tests():
    async def noop(*args: Any, **kwargs: Any) -> None:
        pass
    with patch("app.core.redis_client.init_redis_pool", side_effect=noop), \
         patch("app.core.redis_client.close_redis_pool", side_effect=noop), \
         patch("app.core.security.settings") as mock_settings:
        mock_settings.SKIP_USER_AUTH = False
        mock_settings.SECRET_KEY = "test-secret-key-for-ci"
        mock_settings.ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        yield


from app.main import app  # noqa: E402


# ─────────────────────────────── Sample data ───────────────────────────────

def make_uuid(s: str = "11111111-1111-1111-1111-111111111111") -> uuid.UUID:
    return uuid.UUID(s)


@pytest.fixture
def sample_recipe_spec() -> dict[str, Any]:
    """Minimal published recipe snapshot as stored in recipe_spec (JSONB)."""
    uid1 = "6c0896ac-9ae3-4c74-809a-23d63fd5e7a9"
    uid2 = "546079dc-76ad-4e7b-b72d-577d24aac7e8"
    return {
        "metadata": {
            "name": "stealth-ops-ig05",
            "description": "Auto-generated CTF scenario",
            "category": "CTF",
        },
        "network_profile": {
            "id": "e8c224bd-b31f-4a5b-8556-ce6856a93913",
            "segmentation_strategy": "multi_net",
            "default_subnet_mask": 24,
            "gateway_offset": 1,
            "dns_resolvers": ["8.8.8.8", "1.1.1.1"],
        },
        "domains": [
            {"id": "4dd1d668-129f-4d62-8908-5c323c74acee", "domain_key": "internal-net", "description": "Internal", "public_ingress_enabled": False},
            {"id": "a9647c69-7eec-41db-9732-1d201098a447", "domain_key": "dmz", "description": "DMZ", "public_ingress_enabled": True},
        ],
        "workload_units": [
            {"id": uid1, "unit_key": "web-server-01", "functional_role": "target", "network_position_index": 1, "runtime_profile": "debian-bullseye-slim", "resource_tier": "medium", "assigned_domain": "dmz", "agent_enabled": True, "automation_profile": {"bootstrap_reference": "scripts/web/bootstrap.sh"}},
            {"id": uid2, "unit_key": "db-server-01", "functional_role": "target", "network_position_index": 2, "runtime_profile": "postgres-15-alpine", "resource_tier": "large", "assigned_domain": "internal-net", "agent_enabled": False, "automation_profile": None},
        ],
        "gateways": [
            {
                "id": "c8fb28a5-e3ac-4c9f-80dc-dc6535824f67",
                "gateway_key": "edge-gw-01",
                "gateway_type": "vyos",
                "runtime_profile": "oe:gateway",
                "resource_tier": "md",
                "exposure_rules": [
                    {"unit_id": uid1, "internal_port": 80, "transport_protocol": "tcp"},
                    {"unit_id": uid2, "internal_port": 5432, "transport_protocol": "tcp"},
                ],
            },
        ],
    }


@pytest.fixture
def deployment_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def recipe_version_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def recipe_draft_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_deployment_orm(
    deployment_id: uuid.UUID,
    recipe_version_id: uuid.UUID,
    recipe_draft_id: uuid.UUID,
    sample_recipe_spec: dict[str, Any],
) -> MagicMock:
    """ORM-like deployment object for _to_response (no DB)."""
    now = datetime.now(timezone.utc)
    d = MagicMock()
    d.id = deployment_id
    d.recipe_version_id = recipe_version_id
    d.recipe_draft_id = recipe_draft_id
    d.recipe_id = recipe_draft_id
    d.status = "ALLOCATING"
    d.expires_at = now
    d.team_size = 1
    d.name = None
    d.member_ids = []
    d.created_at = now
    d.updated_at = now
    d.access = {
        "entry_method": "gateway",
        "ssh_public_key_ref": "secret://org/default-ssh-key",
        "floating_ip_enabled": False,
        "remote_console_enabled": True,
    }
    d.recipe_spec = dict(sample_recipe_spec)
    d.experience_type = "selfpaced"
    d.duration_hours = 24
    d.access_mode = "solo"
    d.target_env = None
    d.exercises = None
    return d


@pytest.fixture
def mock_deployment_orm_no_recipe_spec(
    deployment_id: uuid.UUID,
    recipe_version_id: uuid.UUID,
) -> MagicMock:
    """Deployment ORM with no recipe_spec (e.g. legacy or minimal)."""
    now = datetime.now(timezone.utc)
    d = MagicMock()
    d.id = deployment_id
    d.recipe_version_id = recipe_version_id
    d.recipe_draft_id = None
    d.recipe_id = None
    d.status = "RUNNING"
    d.expires_at = now
    d.team_size = 1
    d.name = "My deployment"
    d.member_ids = [uuid.uuid4()]
    d.created_at = now
    d.updated_at = now
    d.access = None
    d.recipe_spec = None
    d.experience_type = None
    d.duration_hours = None
    d.access_mode = None
    d.target_env = None
    d.exercises = None
    return d


# ─────────────────────────────── API client ───────────────────────────────

@pytest.fixture
def any_app() -> FastAPI:
    """Application under test (same as production create_app())."""
    return app


@pytest.fixture
async def async_client(any_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for API tests. Overrides get_db and get_redis_optional so no real DB/Redis."""
    from app.core.database import get_db
    from app.core.redis_client import get_redis_optional, get_redis

    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        m = AsyncMock(spec=AsyncSession)
        
        # Configure execute() to return a mock that supports scalars().all() and scalar_one()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        result_mock.scalar_one.return_value = 0
        result_mock.scalar_one_or_none.return_value = None
        
        m.execute.return_value = result_mock
        yield m

    async def override_get_redis_optional() -> AsyncGenerator[None, None]:
        yield None

    async def override_get_redis() -> AsyncGenerator[AsyncMock, None]:
        m = AsyncMock()
        m.get.return_value = None
        
        # Configure pipeline() for rate limiting tests
        # The pipeline object returned by aioredis is synchronous until execute()
        pipe_mock = MagicMock()
        pipe_mock.zremrangebyscore.return_value = pipe_mock
        pipe_mock.zadd.return_value = pipe_mock
        pipe_mock.zcard.return_value = pipe_mock
        pipe_mock.expire.return_value = pipe_mock
        pipe_mock.execute = AsyncMock(return_value=(None, None, 0, None))
        
        m.pipeline = MagicMock(return_value=pipe_mock)
        
        yield m

    any_app.dependency_overrides[get_db] = override_get_db
    any_app.dependency_overrides[get_redis_optional] = override_get_redis_optional
    any_app.dependency_overrides[get_redis] = override_get_redis
    try:
        transport = ASGITransport(app=any_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        any_app.dependency_overrides.pop(get_db, None)
        any_app.dependency_overrides.pop(get_redis_optional, None)
        any_app.dependency_overrides.pop(get_redis, None)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Fake async DB session for dependency override (no real DB)."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def test_user_id() -> uuid.UUID:
    """Fixed user UUID for auth in API tests."""
    return uuid.UUID("a0000000-0000-0000-0000-000000000001")


@pytest.fixture
def auth_headers(test_user_id: uuid.UUID) -> dict[str, str]:
    """Authorization header with valid JWT for API tests."""
    from app.core.security import create_access_token
    token = create_access_token(test_user_id)
    return {"Authorization": f"Bearer {token}"}
