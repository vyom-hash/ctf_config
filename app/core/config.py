from functools import lru_cache
import os
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    OPENSTACK_REGIONS: List[str] = Field(default_factory=list)

    # OpenStack credentials
    OPENSTACK_AUTH_URL: str = os.getenv("OPENSTACK_AUTH_URL", "")
    OPENSTACK_USERNAME: str = os.getenv("OPENSTACK_USERNAME", "")
    OPENSTACK_PASSWORD: str = os.getenv("OPENSTACK_PASSWORD", "")
    OPENSTACK_USER_DOMAIN_NAME: str = os.getenv("OPENSTACK_USER_DOMAIN_NAME", "Default")
    OPENSTACK_PROJECT_DOMAIN_NAME: str = os.getenv("OPENSTACK_PROJECT_DOMAIN_NAME", "Default")
    OPENSTACK_REGION_NAME: str = os.getenv("OPENSTACK_REGION_NAME", "")

    MINIO_ENDPOINT: str = ""
    MINIO_PORT: int = 9000
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = False
    MINIO_SCRIPT_BUCKET: str = "scripts"

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_POOL_MAX_CONNECTIONS: int = 50

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me"
    ENCRYPTION_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # When True, API endpoints do not require a Bearer token (auth not implemented yet).
    SKIP_USER_AUTH: bool = True

    # ── App ───────────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    ENCRYPTION_KEY:str = "ALThy-VERXkvNMK6Lm9VyWBrjsMs5-ZgAR2ldNfCy1Q="

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    FLAG_SUBMIT_MAX_ATTEMPTS: int = 5
    FLAG_SUBMIT_WINDOW_SECONDS: int = 60

    # ── Cache TTL ─────────────────────────────────────────────────────────────
    LEADERBOARD_CACHE_TTL: int = 30
    CHALLENGE_CACHE_TTL: int = 300

    # ── Leaderboard ───────────────────────────────────────────────────────────
    LEADERBOARD_KEY: str = "ctf:leaderboard"
    LEADERBOARD_TOP_N: int = 100

    # ── Approval workflow ─────────────────────────────────────────────────────
    # When True, submitting a draft immediately moves it to APPROVED, bypassing
    # the manual reviewer step.  Set to False to require a human reviewer.
    AUTO_APPROVE_RECIPES: bool = True

    # ── Deployment constraints (platform-level) ───────────────────────────────
    MAXIMUM_CONCURRENT_DEPLOYMENTS: int = 1000
    AUTO_EXPIRE_MINUTES: int = 120
    TEAM_CONFIGURATION_ENABLED: bool = False
    TEAM_MINIMUM_MEMBERS: int = 1
    TEAM_MAXIMUM_MEMBERS: int = 4
    REDIS_KEY_ACTIVE_DEPLOYMENT_COUNT: str = "ctf:deployments:active_count"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = Settings()
