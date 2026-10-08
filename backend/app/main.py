"""FastAPI application entrypoint.

Wires together configuration, logging, routing, CORS, and the
startup/shutdown lifecycle. Kept intentionally thin: this module's only
job is to assemble the app — business logic never lives here (see the
Clean Architecture boundaries in `docs/architecture/high-level-architecture.md`).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.v1.router import api_router
from app.core.config import Environment, get_settings
from app.core.logging import configure_logging, get_logger
from app.infrastructure.cache.redis import dispose_redis_pool
from app.infrastructure.db.session import dispose_engine

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Application startup/shutdown lifecycle.

    Startup only logs readiness at this milestone — there's no state to
    warm up yet. Shutdown disposes the DB engine and Redis pool cleanly so
    connections aren't left dangling when the process exits (relevant for
    graceful container shutdowns in both Docker Compose and Azure App
    Service).
    """
    logger.info(
        "application_startup",
        environment=settings.environment.value,
        version=settings.version,
    )
    if settings.environment is Environment.PRODUCTION:
        import os

        if os.environ.get("RUN_MIGRATIONS_ON_STARTUP", "").lower() in {"1", "true", "yes"}:
            import subprocess
            import sys

            alembic_dir = "backend" if os.path.exists("backend/alembic.ini") else "."
            if os.path.exists(os.path.join(alembic_dir, "alembic.ini")):
                try:
                    res = subprocess.run(
                        [sys.executable, "-m", "alembic", "upgrade", "head"],
                        cwd=alembic_dir,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if res.returncode == 0:
                        logger.info("database_migrations_applied", output=res.stdout)
                    else:
                        logger.warning("database_migration_failed", error=res.stderr)
                except Exception as exc:
                    logger.warning("database_migration_exception", error=str(exc))
    yield
    logger.info("application_shutdown")
    await dispose_engine()
    await dispose_redis_pool()


def create_app() -> FastAPI:
    """Application factory.

    A factory function (rather than a bare module-level `app = FastAPI()`)
    keeps app construction testable — tests can call `create_app()` to get
    a fresh instance, and it keeps the option open for per-environment app
    configuration without import-time side effects sprawling further than
    they already need to.
    """
    application = FastAPI(
        title=settings.project_name,
        version=settings.version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    class RootResponse(BaseModel):
        """Shape of the root landing response."""

        service: str
        version: str
        docs_url: str | None

    @application.get("/", response_model=RootResponse, tags=["root"], summary="Service info")
    async def root() -> RootResponse:
        """Basic landing endpoint confirming the service is reachable."""
        return RootResponse(
            service=settings.project_name,
            version=settings.version,
            docs_url=application.docs_url,
        )

    return application


app = create_app()
