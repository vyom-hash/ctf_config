"""
Alembic async migration environment.

Uses SQLAlchemy 2.0 async engine so migrations run against the same
postgresql+asyncpg driver that the application uses at runtime.

DATABASE_URL is taken from the app config (which loads .env and os.environ),
so use the same .env as the app and set DATABASE_URL with the correct password.
Falls back to alembic.ini only when config cannot be loaded (e.g. DATABASE_URL unset).
"""
import asyncio
import os
import sys
from pathlib import Path
from logging.config import fileConfig

# ── Load .env from project root before any app imports ────────────────────────
# So DATABASE_URL is set even when running alembic from a different cwd.
def _load_dotenv_from_project_root() -> None:
    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"
    if not env_file.is_file():
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip()


_load_dotenv_from_project_root()

# ── Now load logging and alembic ─────────────────────────────────────────────

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

# ── Import every model module so their mapped classes are registered with Base
# before Alembic inspects Base.metadata.  Add new model modules here.
from app.core.database import Base
from app.models import deployment         # noqa: F401
from app.models import recipe             # noqa: F401
from app.models import exercise_instance  # noqa: F401
from app.models import cloud_provider  # noqa: F401

config = context.config

# ── Wire up Python logging from alembic.ini ───────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """
    Use the app config so DATABASE_URL is read from .env (same as the app).
    Falls back to alembic.ini only when config is not available.
    """
    try:
        from app.core.config import get_settings
        return get_settings().DATABASE_URL
    except Exception:
        url = os.environ.get("DATABASE_URL")
        if url:
            return url
        fallback = config.get_main_option("sqlalchemy.url")
        if fallback and "secret" in (fallback or ""):
            print(
                "\n  DATABASE_URL not set. Using placeholder from alembic.ini (password will fail).\n"
                "  Create a .env file in the project root with:\n"
                "    DATABASE_URL=postgresql+asyncpg://ctf_user:YOUR_REAL_PASSWORD@localhost/ctf_config\n"
                "  Then run: alembic upgrade head\n",
                file=sys.stderr,
            )
        return fallback or ""


# ── Offline mode (generates SQL without connecting) ──────────────────────────

def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (connects and runs migrations) ────────────────────────────────

def _run_migrations_sync(connection) -> None:
    """Called inside connection.run_sync() — executes synchronously."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,          # detect column type changes
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_async() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    url = _get_url()
    cfg["sqlalchemy.url"] = url

    # NullPool: each migration run gets a fresh connection; no pooling needed.
    connectable = async_engine_from_config(
        cfg, prefix="sqlalchemy.", poolclass=NullPool
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_run_migrations_sync)
    except Exception as e:
        err_cls = type(e).__name__
        if "InvalidPasswordError" in err_cls or "password" in str(e).lower():
            print(
                "\n  Database connection failed: password for user 'ctf_user' was rejected.\n"
                "  Set DATABASE_URL in your project's .env file with the correct password.\n"
                "  Example: postgresql+asyncpg://ctf_user:YOUR_PASSWORD@localhost/ctf_config\n"
                "  Then run: alembic upgrade head\n",
                file=sys.stderr,
            )
        raise
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_migrations_async())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
