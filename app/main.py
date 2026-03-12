"""
FastAPI application factory.

Startup / shutdown lifecycle
─────────────────────────────
• init_redis_pool() — creates the shared Redis connection pool
• close_redis_pool() — drains and closes the pool on shutdown
• start_scheduler() — starts periodic OpenStack flavor sync
"""
from contextlib import asynccontextmanager
from datetime import timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.api.v1.routers import (
    deployments,
    recipes,
    challenges,
    registry_metadata,
    resource_tier,
    cloud_providers
)
from app.constants import MAX_INSTANCES, PERIODIC_JOB_TIME_FOR_FLAVOR
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import close_redis_pool, init_redis_pool
from openstack_client.openstack_sync_service import OpenStackSyncService
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

# Scheduler (global instance)
async def sync_openstack_flavors():
    """
    Scheduler-safe wrapper.
    Creates DB session manually and syncs per region.
    """
    regions = settings.OPENSTACK_REGIONS 
    if not regions:
        logger.warning("OPENSTACK_REGIONS not configured. Skipping flavor sync.")
        return 

    async with AsyncSessionLocal() as db:
        for region in regions:
            try:
                await OpenStackSyncService.sync_flavors(db, region)
            except Exception as e:
                logger.error(
                    f"OpenStack flavor sync failed for region {region}: {e}",
                    exc_info=True,
                )

scheduler = AsyncIOScheduler(timezone=timezone.utc)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────
    await init_redis_pool()

    # Add periodic job 
    scheduler.add_job(
        sync_openstack_flavors,
        trigger=IntervalTrigger(minutes=PERIODIC_JOB_TIME_FOR_FLAVOR),
        id="openstack_flavor_sync",
        replace_existing=True,
        max_instances=MAX_INSTANCES,
        coalesce=True,
    )
    scheduler.start()
    yield
    # ── Shutdown ─────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    await close_redis_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CTF Config Service",
        description="Production-ready CTF training platform — recipe authoring & runtime API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS (tighten allowed_origins in production) ──────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global error handlers ─────────────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        for err in errors:
            if "ctx" in err and "error" in err["ctx"]:
                 err["ctx"]["error"] = str(err["ctx"]["error"])
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": errors,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
        # Preserve original detail as nested payload for debugging/clients
        content = {
            "error": detail.get("error", "HTTP_ERROR"),
            "message": detail.get("message", str(exc.detail)),
        }
        # Include any extra fields from the original detail under "details"
        extra = {
            k: v for k, v in detail.items() if k not in {"error", "message"}
        }
        if extra:
            content["details"] = extra
        return JSONResponse(status_code=exc.status_code, content=content)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(recipes.router, prefix=settings.API_V1_PREFIX)
    app.include_router(deployments.router, prefix=settings.API_V1_PREFIX)
    app.include_router(challenges.router, prefix=settings.API_V1_PREFIX)
    app.include_router(cloud_providers.router, prefix=settings.API_V1_PREFIX)
    app.include_router(resource_tier.router, prefix=settings.API_V1_PREFIX)
    app.include_router(registry_metadata.router, prefix=settings.API_V1_PREFIX)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()