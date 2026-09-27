"""API coverage for mobility-aware planning of a proposed (not yet saved) itinerary.

A proposed itinerary is assembled from ranked candidates and only persisted once the
user confirms it, so the saved plan has no items to derive transitions from at
proposal time. These tests pin the behaviour the proposal UI depends on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_planning_service
from app.api.v1.auth import get_current_user
from app.application.planning.planning_service import PlanningService
from app.core.config import get_settings
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.plan_item import PlanItem
from app.infrastructure.db.models import User


class InMemoryPlanRepository:
    """Minimal `PlanRepository` so planning endpoints can be exercised without a database."""

    def __init__(self) -> None:
        self._plans: dict[UUID, Plan] = {}
        self._items: dict[UUID, list[PlanItem]] = {}

    async def create(self, plan: Plan) -> Plan:
        self._plans[plan.id] = plan
        self._items[plan.id] = list(plan.items)
        return plan

    async def get(self, plan_id: UUID, user_id: UUID) -> Plan | None:
        plan = self._plans.get(plan_id)
        if plan is None or plan.user_id != user_id:
            return None
        plan.items = list(self._items.get(plan_id, []))
        return plan

    async def list_for_user(self, user_id: UUID) -> list[Plan]:
        return [p for p in self._plans.values() if p.user_id == user_id]

    async def update(self, plan: Plan) -> Plan:
        self._plans[plan.id] = plan
        self._items[plan.id] = list(plan.items)
        return plan

    async def delete(self, plan_id: UUID, user_id: UUID) -> bool:
        plan = self._plans.get(plan_id)
        if plan is None or plan.user_id != user_id:
            return False
        del self._plans[plan_id]
        self._items.pop(plan_id, None)
        return True

    async def create_item(self, user_id: UUID, plan_id: UUID, item: PlanItem) -> PlanItem | None:
        if await self.get(plan_id, user_id) is None:
            return None
        self._items.setdefault(plan_id, []).append(item)
        return item

    async def get_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> PlanItem | None:
        return next((i for i in self._items.get(plan_id, []) if i.id == item_id), None)

    async def list_items(self, user_id: UUID, plan_id: UUID) -> list[PlanItem] | None:
        if await self.get(plan_id, user_id) is None:
            return None
        return list(self._items.get(plan_id, []))

    async def update_item(self, user_id: UUID, plan_id: UUID, item: PlanItem) -> PlanItem | None:
        items = self._items.get(plan_id, [])
        for idx, existing in enumerate(items):
            if existing.id == item.id:
                items[idx] = item
                return item
        return None

    async def delete_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> bool:
        items = self._items.get(plan_id, [])
        remaining = [i for i in items if i.id != item_id]
        if len(remaining) == len(items):
            return False
        self._items[plan_id] = remaining
        return True


@pytest.fixture
async def client_with_plans(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """A client with auth and plan persistence stubbed out, leaving M14 providers real."""
    user = User(id=uuid.uuid4(), email="mobility-proposal@example.com")
    # One repository instance for the whole test: the proposal flow spans several
    # requests and must see the plan created by the first one.
    repository = InMemoryPlanRepository()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_planning_service] = lambda: PlanningService(repository)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _create_plan(client: AsyncClient, request: str) -> dict:
    settings = get_settings()
    response = await client.post(
        f"{settings.api_v1_prefix}/planning/requests",
        json={"request": request},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_public_transport_request_produces_transitions_for_proposed_stops(
    client_with_plans: AsyncClient,
) -> None:
    plan = await _create_plan(
        client_with_plans,
        "A date for 4 with good food and somewhere pretty afterwards "
        "under R800 using public transport",
    )
    plan_id = plan["id"]

    # The stated mobility preference must survive into both understanding and context.
    assert plan["understanding"]["transport_mode"] == "public_transport"
    assert plan["context"]["transport_mode"] == "public_transport"
    assert plan["context"]["group_size"] == 4

    base = datetime(2026, 9, 27, 11, 0)
    stops = [
        {
            "name": "Artisan Coffee & Steampunk Brunch",
            "location": "Buitenkant St, Cape Town CBD",
            "start_time": base.isoformat(),
            "end_time": (base + timedelta(hours=1)).isoformat(),
            "estimated_cost": 180,
        },
        {
            "name": "Bo-Kaap Cultural & Spice Walk",
            "location": "Wale Street, Bo-Kaap, Cape Town",
            "start_time": (base + timedelta(hours=1)).isoformat(),
            "end_time": (base + timedelta(hours=2, minutes=15)).isoformat(),
            "estimated_cost": 0,
        },
        {
            "name": "Kirstenbosch Boomslang Canopy Walk",
            "location": "Kirstenbosch National Botanical Garden, Cape Town",
            "start_time": (base + timedelta(hours=2, minutes=15)).isoformat(),
            "end_time": (base + timedelta(hours=3, minutes=45)).isoformat(),
            "estimated_cost": 90,
        },
    ]

    settings = get_settings()
    response = await client_with_plans.post(
        f"{settings.api_v1_prefix}/planning/plans/{plan_id}/transitions/proposed",
        json={"stops": stops, "party_size": 4},
    )

    assert response.status_code == 200
    data = response.json()
    transitions = data["transitions"]

    # One transition per leg between the three proposed stops.
    assert len(transitions) == 2
    assert transitions[0]["from_location"] == stops[0]["location"]
    assert transitions[0]["to_location"] == stops[1]["location"]
    assert transitions[1]["from_location"] == stops[1]["location"]
    assert transitions[1]["to_location"] == stops[2]["location"]

    for transition in transitions:
        # Mobility must be represented, not silently dropped.
        assert transition["mode"] is not None
        assert transition["provider_id"] not in (None, "")
        assert transition["provider_name"] not in (None, "")
        assert transition["duration_minutes"] is not None
        # Unknown values stay unknown rather than being invented.
        if transition["cost_known"]:
            assert transition["cost"] is not None
        else:
            assert transition["cost"] is None
        assert "live_status" in transition

    assert "feasibility" in data


@pytest.mark.asyncio
async def test_proposed_transitions_require_at_least_two_stops(
    client_with_plans: AsyncClient,
) -> None:
    plan = await _create_plan(client_with_plans, "Coffee in Cape Town")
    settings = get_settings()

    response = await client_with_plans.post(
        f"{settings.api_v1_prefix}/planning/plans/{plan['id']}/transitions/proposed",
        json={"stops": [{"name": "Only stop", "location": "Civic Centre, Cape Town"}]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_proposed_transitions_reject_unknown_plan(client_with_plans: AsyncClient) -> None:
    settings = get_settings()
    response = await client_with_plans.post(
        f"{settings.api_v1_prefix}/planning/plans/{uuid.uuid4()}/transitions/proposed",
        json={
            "stops": [
                {"name": "A", "location": "Gardens, Cape Town"},
                {"name": "B", "location": "Camps Bay, Cape Town"},
            ]
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unstated_transport_preference_remains_unknown(
    client_with_plans: AsyncClient,
) -> None:
    body = await _create_plan(client_with_plans, "A quiet lunch in Cape Town")

    # No stated preference must not become an invented transport constraint.
    assert body["understanding"]["transport_mode"] is None
    assert body["context"]["transport_mode"] is None


@pytest.mark.asyncio
async def test_explicit_no_car_preference_is_extracted(client_with_plans: AsyncClient) -> None:
    body = await _create_plan(
        client_with_plans,
        "Dinner and an activity in Cape Town, I don't have a car, make sure timing works",
    )

    assert body["understanding"]["transport_mode"] == "walk"
    assert body["understanding"]["people_count"] is None
