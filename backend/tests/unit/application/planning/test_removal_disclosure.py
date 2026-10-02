"""The removal disclosure has to name the stop it is actually about.

The re-plan loop resolves a violation, writes a reason for it, and drops a stop.
When those two disagree the user is told "Grand Pavilion Camps Bay was removed
because the Iziko Gallery is closed", and goes looking for the wrong venue — or
concludes the planner removed the right thing for a reason that has nothing to
do with it.

The mismatch is not hypothetical: with a gallery in the middle of the day that
closes before it is reached, every trimmed stop inherited the gallery's reason.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.application.planning.mobility_planning_service import MobilityPlanningService
from app.application.planning.orchestration_service import (
    ItineraryOrchestrator,
    OrchestrationStopInput,
)
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption, MobilityRequirement
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.plan import Plan

MUSEUM = "Iziko South African National Gallery"
A = "1 Adderley St, City Bowl, Cape Town"
B = "2 Orange St, Gardens, Cape Town"
C = "3 Loop St, V&A Waterfront, Cape Town"


class StubMobilityService:
    def __init__(self) -> None:
        pass

    async def find_options_for_requirement(
        self, requirement: MobilityRequirement
    ) -> list[MobilityOption]:
        # Walking everywhere keeps the schedule simple and the times predictable.
        return [
            MobilityOption(
                id=f"walk-{requirement.origin[:2]}-{requirement.destination[:2]}",
                provider_id="walk",
                provider_name="On foot",
                mode=TransportMode.WALKING,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=10,
                cost=Decimal("0"),
                cost_is_unknown=False,
                transfers=0,
            )
        ]


def _plan() -> Plan:
    return Plan(
        id=uuid4(),
        user_id=uuid4(),
        intention="a day out in the City Bowl",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=[],
    )


def _stops() -> list[OrchestrationStopInput]:
    """Three stops, the middle of which is shut by the time the day reaches it."""
    return [
        OrchestrationStopInput(
            name="Company's Garden", location=A, duration_minutes=45, estimated_cost=Decimal("0")
        ),
        OrchestrationStopInput(
            # Opens late and closes at 17:00, so an afternoon day cannot use it.
            name=MUSEUM,
            location=B,
            duration_minutes=60,
            estimated_cost=Decimal("60"),
            opening_hours="Daily 10:00-12:00",
        ),
        OrchestrationStopInput(
            name="Zeitz MOCAA", location=C, duration_minutes=60, estimated_cost=Decimal("0")
        ),
    ]


def test_a_removed_stop_is_named_in_its_own_reason() -> None:
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService()))
    result = asyncio.run(orch.orchestrate(_plan(), _stops(), origin=None))

    assert result.removed_stops, "the closed stop should have been dropped"

    for removed in result.removed_stops:
        # The reason reads "<name> was removed because <reason>", so it must
        # explain itself in the third person and not open by repeating the name.
        assert removed.name not in removed.reason, (
            f"the reason repeats the name the UI already printed: {removed.reason!r}"
        )
        assert removed.reason.startswith("it "), (
            f"a reason that does not refer to the stop cannot be read as its own: "
            f"{removed.reason!r}"
        )


def test_the_closed_stop_is_the_one_removed() -> None:
    """Not just self-consistent wording: the actual offender goes."""
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService()))
    result = asyncio.run(orch.orchestrate(_plan(), _stops(), origin=None))

    removed_names = [r.name for r in result.removed_stops]
    assert MUSEUM in removed_names, (
        f"the gallery is the closed one, but {removed_names} went instead"
    )
    assert "Company's Garden" not in removed_names, (
        "an open, free garden was dropped to fix a problem it had nothing to do with"
    )


def test_every_surviving_stop_is_still_in_the_plan() -> None:
    """Dropping the offender must not quietly empty the day."""
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService()))
    result = asyncio.run(orch.orchestrate(_plan(), _stops(), origin=None))

    assert result.stops, "removing one stop should not leave the user with nothing"
    kept = {s.name for s in result.stops}
    assert MUSEUM not in kept
