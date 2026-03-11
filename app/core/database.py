"""
Async SQLAlchemy engine + session factory.

Pool is sized for 5 000 concurrent users:
  pool_size=20   → baseline persistent connections
  max_overflow=10 → allow burst headroom (30 total)
  pool_pre_ping   → drop stale connections automatically
  pool_recycle    → recycle connections before the DB kills them (30 min)
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
try:
    from sqlalchemy.ext.asyncio import async_sessionmaker
except ImportError:
    # Fallback for SQLAlchemy 1.4.x (often used by global alembic)
    from sqlalchemy.orm import sessionmaker
    def async_sessionmaker(*args, **kwargs):
        kwargs.setdefault("class_", AsyncSession)
        return sessionmaker(*args, **kwargs)
try:
    from sqlalchemy.orm import DeclarativeBase
except ImportError:
    # SQLAlchemy 1.x: DeclarativeBase was added in 2.0
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()
else:
    class Base(DeclarativeBase):
        pass

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and auto-commits on success."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
