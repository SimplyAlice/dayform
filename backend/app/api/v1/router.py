"""Aggregates all API v1 routers into a single router mounted by `app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    cover_letters,
    health,
    jobs,
    matches,
    mobility,
    operations,
    planning,
    profile,
    resumes,
    services,
)

from app.core.config import get_settings

api_router = APIRouter()


@api_router.get("", response_model=health.HealthResponse, tags=["health"], summary="API v1 root status")
async def api_v1_root() -> health.HealthResponse:
    """Confirm API v1 router is mounted and healthy."""
    settings = get_settings()
    return health.HealthResponse(
        status="ok",
        service=settings.project_name,
        version=settings.version,
    )


api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(jobs.router)
api_router.include_router(profile.router)
api_router.include_router(matches.router)
api_router.include_router(resumes.router)
api_router.include_router(cover_letters.router)
api_router.include_router(services.router)
api_router.include_router(operations.router)
api_router.include_router(planning.router)
api_router.include_router(planning.information_router, prefix="/planning")
api_router.include_router(mobility.router)

