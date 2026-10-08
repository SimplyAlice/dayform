"""Tests for the /api/v1/health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    settings = get_settings()

    response = await client.get(f"{settings.api_v1_prefix}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == settings.project_name
    assert body["version"] == settings.version


@pytest.mark.asyncio
async def test_api_v1_root_returns_ok(client: AsyncClient) -> None:
    settings = get_settings()

    response = await client.get(settings.api_v1_prefix)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == settings.project_name
    assert body["version"] == settings.version
