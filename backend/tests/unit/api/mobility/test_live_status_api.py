"""API coverage for the M16 live mobility status endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_live_status_reports_unavailable_for_provider_without_feed(
    client: AsyncClient,
) -> None:
    """No public live feed is configured, so the honest answer is 'unavailable'."""
    settings = get_settings()
    response = await client.get(
        f"{settings.api_v1_prefix}/mobility/live-status",
        params={"provider_id": "myciti"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_id"] == "myciti"
    assert body["availability"] == "unavailable"
    assert body["status"] == "unknown"
    assert body["confidence"] == 0.0
    # No invented delay, ETA or observation time.
    assert body["delay_minutes"] is None
    assert body["observed_at"] is None
    assert body["expected_departure"] is None
    assert body["is_blocking"] is False


@pytest.mark.asyncio
async def test_live_status_is_truthful_for_every_transit_provider(
    client: AsyncClient,
) -> None:
    """MyCiTi, PRASA and Golden Arrow must not claim realtime support."""
    settings = get_settings()
    for provider_id in ("myciti", "prasa_metrorail", "golden_arrow"):
        response = await client.get(
            f"{settings.api_v1_prefix}/mobility/live-status",
            params={"provider_id": provider_id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["availability"] == "unavailable", provider_id
        assert body["status"] == "unknown", provider_id


@pytest.mark.asyncio
async def test_live_status_is_truthful_for_ride_hail_providers(
    client: AsyncClient,
) -> None:
    """Ride-hailing platforms must not be presented as live-tracked."""
    settings = get_settings()
    for provider_id in ("uber", "bolt", "indrive"):
        response = await client.get(
            f"{settings.api_v1_prefix}/mobility/live-status",
            params={"provider_id": provider_id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["availability"] == "unavailable", provider_id
        assert body["status"] == "unknown", provider_id


@pytest.mark.asyncio
async def test_live_status_for_unregistered_provider_is_unavailable(
    client: AsyncClient,
) -> None:
    settings = get_settings()
    response = await client.get(
        f"{settings.api_v1_prefix}/mobility/live-status",
        params={"provider_id": "not_a_provider"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "unavailable"
    assert body["status"] == "unknown"
