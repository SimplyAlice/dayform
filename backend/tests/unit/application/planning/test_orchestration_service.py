"""Tests for transport-aware itinerary orchestration and origin handling.

The behaviour under test is the inversion the product required: transport is
evaluated *before* time windows are assigned, so a proposed day's windows
already contain their travel time.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.planning.mobility_planning_service import (
    MobilityPlanningService,
    StopSequencePoint,
)
from app.application.planning.orchestration_service import (
    ItineraryOrchestrator,
    OrchestrationStopInput,
)
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption, MobilityRequirement
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.plan import Plan


class StubMobilityService:
    """Returns fixed options per leg so selection is deterministic."""

    def __init__(self, options_by_provider: list[MobilityOption]) -> None:
        self._options = options_by_provider

    async def find_options_for_requirement(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        return [
            option
            for option in self._options
            if option.origin == requirement.origin and option.destination == requirement.destination
        ]


def _option(
    provider_id: str,
    provider_name: str,
    mode: TransportMode,
    origin: str,
    destination: str,
    duration: int | None,
    cost: Decimal | None,
) -> MobilityOption:
    return MobilityOption(
        id=f"{provider_id}-{origin[:3]}-{destination[:3]}",
        provider_id=provider_id,
        provider_name=provider_name,
        mode=mode,
        origin=origin,
        destination=destination,
        duration_minutes=duration,
        cost=cost,
        cost_is_unknown=cost is None,
        transfers=0,
    )


def _plan(*, budget: str | None = "800", transport_mode: str | None = None) -> Plan:
    plan_id = uuid4()
    constraints = []
    if budget:
        constraints.append(
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.BUDGET_MAX,
                value=f"R{budget}",
                numeric_value=Decimal(budget),
            )
        )
    return Plan(
        id=plan_id,
        user_id=uuid4(),
        intention="test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=constraints,
        context=PlanningContext(plan_id=plan_id, location="Cape Town", transport_mode=transport_mode)
        if transport_mode
        else None,
    )


def _stops() -> list[OrchestrationStopInput]:
    return [
        OrchestrationStopInput(
            name="Brunch",
            location="36 Buitenkant St, City Bowl, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("185"),
        ),
        OrchestrationStopInput(
            name="Bo-Kaap",
            location="71 Wale St, Bo-Kaap, Cape Town",
            duration_minutes=75,
            estimated_cost=Decimal("120"),
        ),
    ]


A = "36 Buitenkant St, City Bowl, Cape Town"
B = "71 Wale St, Bo-Kaap, Cape Town"
OBS = "Observatory, Cape Town"


def _orchestrator(options: list[MobilityOption]) -> ItineraryOrchestrator:
    return ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))


def _orchestrate(orch: ItineraryOrchestrator, *, origin: str | None, plan: Plan | None = None):
    return asyncio.run(orch.orchestrate(plan or _plan(), _stops(), origin=origin))


# --- Origin -----------------------------------------------------------------


def test_origin_is_never_assumed_when_absent() -> None:
    """No stated origin must leave origin unresolved, not invented."""
    options = [_option("walk", "Walking", TransportMode.WALK, A, B, 15, Decimal("0"))]
    result = _orchestrate(_orchestrator(options), origin=None)

    assert result.origin is None
    assert result.origin_resolved is False
    # Only the stop-to-stop leg exists; no fabricated start leg.
    assert len(result.legs) == 1
    assert result.legs[0].from_label == "Brunch"


def test_explicit_origin_adds_a_real_first_leg() -> None:
    """A stated origin becomes a genuine leg that shifts the schedule."""
    options = [
        _option("walk", "Walking", TransportMode.WALK, OBS, A, 20, Decimal("0")),
        _option("walk", "Walking", TransportMode.WALK, A, B, 15, Decimal("0")),
    ]
    result = _orchestrate(_orchestrator(options), origin=OBS)

    assert result.origin_resolved is True
    assert result.origin == OBS
    assert len(result.legs) == 2
    assert result.legs[0].from_label == OBS
    assert result.legs[0].to_label == "Brunch"


def test_origin_materially_changes_the_schedule() -> None:
    """The same stops with and without an origin must not produce the same day."""
    options = [
        _option("walk", "Walking", TransportMode.WALK, OBS, A, 25, Decimal("0")),
        _option("walk", "Walking", TransportMode.WALK, A, B, 15, Decimal("0")),
    ]
    with_origin = _orchestrate(_orchestrator(options), origin=OBS)
    without_origin = _orchestrate(_orchestrator(options), origin=None)

    assert with_origin.stops[0].start_time != without_origin.stops[0].start_time
    assert with_origin.stops[0].start_time > without_origin.stops[0].start_time


# --- Transport before scheduling -------------------------------------------


def test_windows_contain_the_selected_travel_time() -> None:
    """The gap between stops must equal the travel time actually chosen."""
    options = [_option("train", "Rail", TransportMode.TRAIN, A, B, 12, Decimal("10.50"))]
    result = _orchestrate(_orchestrator(options), origin=None)

    first, second = result.stops
    gap = (second.start_time - first.end_time).total_seconds() / 60
    assert gap == 12
    # A stop's own duration is respected, not overwritten by travel.
    assert (first.end_time - first.start_time).total_seconds() / 60 == 90


def test_leg_never_reports_a_zero_minute_window() -> None:
    """The original failure mode: a leg judged against an empty window."""
    options = [_option("train", "Rail", TransportMode.TRAIN, A, B, 12, Decimal("10.50"))]
    result = _orchestrate(_orchestrator(options), origin=None)

    for leg in result.legs:
        assert leg.transition.is_feasible
        assert "available window (0 min)" not in (leg.transition.feasibility_issue or "")

    assert result.feasibility is not None
    assert result.feasibility.is_feasible
    assert result.feasibility.transitions_feasible


def test_selected_option_is_feasible_and_alternatives_are_preserved() -> None:
    options = [
        _option("train", "Rail", TransportMode.TRAIN, A, B, 12, Decimal("10.50")),
        _option("uber", "Uber", TransportMode.RIDE_HAIL, A, B, 9, None),
        _option("walk", "Walking", TransportMode.WALK, A, B, 40, Decimal("0")),
    ]
    result = _orchestrate(_orchestrator(options), origin=None)

    leg = result.legs[0]
    assert leg.selected_option_id is not None
    provider_ids = {alt.provider_id for alt in leg.alternatives}
    # The chosen provider is not offered again as its own alternative.
    assert leg.transition.provider_id not in provider_ids
    assert provider_ids  # alternatives exist for the user
    assert len(leg.alternatives) <= 3


def test_unknown_duration_does_not_invent_a_buffer() -> None:
    """A leg with no verifiable travel time must not pad the schedule."""
    options = [_option("mystery", "Mystery", TransportMode.OTHER, A, B, None, None)]
    result = _orchestrate(_orchestrator(options), origin=None)

    first, second = result.stops
    gap = (second.start_time - first.end_time).total_seconds() / 60
    assert gap == 0
    assert result.feasibility is not None
    assert result.feasibility.has_unknown_transition_costs is True


def test_budget_filters_out_options_that_cannot_be_afforded() -> None:
    """An unaffordable option must never be presented as though it were affordable.

    The only option for this leg costs R5,000 against an R800 budget. Presenting the
    two-stop day anyway would be a knowingly violated hard constraint, so the day is
    trimmed to what fits and the trim is reported rather than hidden.
    """
    expensive = _option("shuttle", "Shuttle", TransportMode.SHUTTLE, A, B, 5, Decimal("5000"))
    result = _orchestrate(_orchestrator([expensive]), origin=None, plan=_plan(budget="800"))

    assert result.feasibility is not None
    assert result.feasibility.budget_respected is True
    # The dropped stop is stated, not silently discarded.
    assert [stop.name for stop in result.removed_stops] == ["Bo-Kaap"]
    assert "budget" in result.removed_stops[0].reason
    # The re-planned day now honours the budget, so it is presented as valid.
    assert result.conflicts == ()
    assert result.is_valid is True


# --- Business actions -------------------------------------------------------


def test_venue_actions_are_derived_from_verified_data_only() -> None:
    from app.application.planning.venue_actions import (
        derive_venue_action_specs,
    )
    from app.domain.entities.planning.execution import ExecutionActionType

    full = derive_venue_action_specs(
        name="Kloof Street House",
        location="30 Kloof St, Gardens",
        source_url="https://kloofstreet.co.za",
        phone="+27 21 424 3333",
        reservation_url="https://kloofstreet.co.za/book",
    )
    types = {spec.action_type for spec in full}
    assert ExecutionActionType.RESERVE in types
    assert ExecutionActionType.CALL in types
    assert ExecutionActionType.OPEN_WEBSITE in types
    assert ExecutionActionType.DIRECTIONS in types

    bare = derive_venue_action_specs(
        name="Some Walk",
        location="Beach Rd, Sea Point",
        source_url=None,
        phone=None,
        reservation_url=None,
    )
    assert [spec.action_type for spec in bare] == [ExecutionActionType.DIRECTIONS]
    # No fabricated booking path when the venue publishes none.
    assert ExecutionActionType.RESERVE not in {spec.action_type for spec in bare}


def test_orchestrated_stop_carries_execution_actions() -> None:
    from app.domain.entities.planning.execution import ExecutionActionType

    options = [_option("walk", "Walking", TransportMode.WALK, A, B, 15, Decimal("0"))]
    stops = [
        OrchestrationStopInput(
            name="Kloof Street House",
            location="30 Kloof St, Gardens",
            address="30 Kloof St, Gardens",
            source_url="https://kloofstreet.co.za",
            phone="+27 21 424 3333",
            reservation_url="https://kloofstreet.co.za/book",
        )
    ]
    result = asyncio.run(_orchestrator(options).orchestrate(_plan(), stops, origin=None))
    types = {spec.action_type for spec in result.stops[0].actions}
    assert ExecutionActionType.RESERVE in types
    assert ExecutionActionType.CALL in types
    # A venue with a booking page does not also need a "contact venue" hint.
    assert result.stops[0].contact_hint is None


# --- Understanding ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A relaxed date under R800.", None),
        (
            "A relaxed date with good food and somewhere pretty afterwards under R800. "
            "I'm starting from Observatory.",
            "Observatory",
        ),
        ("Plan this from my hotel in Sea Point.", "Sea Point"),
        ("Something relaxed in Gardens, starting from Woodstock.", "Woodstock"),
    ],
)
def test_explicit_origin_extraction(text: str, expected: str | None) -> None:
    assert DeterministicUnderstandingEngine._extract_origin(text) == expected


def test_origin_is_not_mistaken_for_the_destination_area() -> None:
    """'starting from Observatory' must not make Observatory the destination."""
    text = (
        "A relaxed date with good food and somewhere pretty afterwards under R800. "
        "I'm starting from Observatory."
    )
    location, _is_inferred, _prov, _descriptors = DeterministicUnderstandingEngine._extract_location(text)
    assert location == "Cape Town"


def test_aligned_legs_preserve_index_for_unaffected_pairs() -> None:
    """A pair needing no travel keeps its slot so scheduling stays aligned."""
    options = [_option("walk", "Walking", TransportMode.WALK, A, B, 15, Decimal("0"))]
    service = MobilityPlanningService(StubMobilityService(options))
    points = [StopSequencePoint(location=A), StopSequencePoint(location=A), StopSequencePoint(location=B)]
    legs = asyncio.run(service.evaluate_aligned_legs(points))

    assert len(legs) == 2
    assert legs[0] is None  # same location needs no travel
    assert legs[1] is not None


def test_venue_address_drives_routing_not_just_the_area() -> None:
    """Candidates report their area as the location, so the address must be the route key.

    Routing on "Cape Town" alone made three distinct venues look like one place,
    which silently removed the travel between them from the schedule.
    """
    stops = [
        OrchestrationStopInput(
            name="District Six Museum",
            location="Cape Town",
            address="Smit Street, District Six, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("60"),
        ),
        OrchestrationStopInput(
            name="Grand Pavilion",
            location="Cape Town",
            address="160 Victoria Road, Camps Bay, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("120"),
        ),
    ]
    options = [
        _option("uber", "Uber", TransportMode.RIDE_HAIL, "Observatory, Cape Town",
                "Smit Street, District Six, Cape Town", 14, None),
        _option("uber", "Uber", TransportMode.RIDE_HAIL, "Smit Street, District Six, Cape Town",
                "160 Victoria Road, Camps Bay, Cape Town", 12, None),
    ]
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))
    result = asyncio.run(orch.orchestrate(_plan(), stops, origin=OBS))

    # Both legs are evaluated and both carry real travel into the schedule.
    assert len(result.legs) == 2
    assert all(leg.transition.duration_minutes for leg in result.legs)
    first, second = result.stops
    assert (second.start_time - first.end_time).total_seconds() == 12 * 60


# --- Transport preference ------------------------------------------------------


def _two_leg_options(specs: list[tuple[str, str, TransportMode, int, Decimal | None]]) -> list[MobilityOption]:
    """The same set of options offered on both legs of the day."""
    options: list[MobilityOption] = []
    for origin, destination in ((OBS, A), (A, B)):
        for provider_id, provider_name, mode, duration, cost in specs:
            options.append(_option(provider_id, provider_name, mode, origin, destination, duration, cost))
    return options


def test_stated_transport_preference_is_used_for_the_leg() -> None:
    """A user who asks to walk gets walking, even when rail is quicker."""
    options = _two_leg_options(
        [
            ("prasa", "PRASA Metrorail", TransportMode.TRAIN, 8, Decimal("10.50")),
            ("walk", "Walking", TransportMode.WALK, 40, Decimal("0")),
        ]
    )
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))
    result = asyncio.run(
        orch.orchestrate(_plan(), _stops(), origin=OBS, preferred_modes=[TransportMode.WALK])
    )

    assert result.transport_preference == "walk"
    assert result.transport_preference_honoured is True
    assert result.transport_preference_note is None
    # The rail option is preserved as a genuine alternative, not discarded.
    assert any(o.provider_id == "prasa" for o in result.legs[0].alternatives)
    assert result.legs[0].transition.provider_id == "walk"
    assert result.legs[1].transition.provider_id == "walk"


def test_context_public_transport_preference_selects_transit_by_default() -> None:
    options = _two_leg_options(
        [
            ("prasa", "PRASA Metrorail", TransportMode.TRAIN, 20, Decimal("10.50")),
            ("walk", "Walking", TransportMode.WALK, 5, Decimal("0")),
        ]
    )
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))
    result = asyncio.run(
        orch.orchestrate(_plan(transport_mode="public_transport"), _stops(), origin=OBS)
    )

    assert result.transport_preference_honoured is True
    assert all(leg.transition.mode is TransportMode.TRAIN for leg in result.legs)
    assert all(leg.transition.live_source is None for leg in result.legs)


def test_unavailable_preference_is_explained_rather_than_silently_swapped() -> None:
    """Asking for rail where no rail exists must be reported, not quietly replaced."""
    options = _two_leg_options(
        [
            ("walk", "Walking", TransportMode.WALK, 30, Decimal("0")),
            ("uber", "Uber", TransportMode.RIDE_HAIL, 12, None),
        ]
    )
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))
    result = asyncio.run(
        orch.orchestrate(_plan(), _stops(), origin=OBS, preferred_modes=[TransportMode.TRAIN])
    )

    assert result.transport_preference == "train"
    assert result.transport_preference_honoured is False
    # The plan-level note is one summary, not a run-on of every leg's explanation.
    assert "could not be used" in result.transport_preference_note
    assert "ride hail" in result.transport_preference_note
    # Each leg still explains itself against the preference the user stated.
    assert result.legs[0].transition.provider_id is not None
    assert result.legs[0].preference_honoured is False
    assert "You asked for train" in result.legs[0].preference_note
    assert "walk" in result.legs[0].preference_note


def test_no_preference_leaves_preference_status_unstated() -> None:
    """Default-ranked legs must not be reported as contradicting the user."""
    options = _two_leg_options(
        [
            ("prasa", "PRASA Metrorail", TransportMode.TRAIN, 8, Decimal("10.50")),
            ("walk", "Walking", TransportMode.WALK, 40, Decimal("0")),
        ]
    )
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))
    result = asyncio.run(orch.orchestrate(_plan(), _stops(), origin=OBS))

    assert result.transport_preference is None
    assert result.transport_preference_honoured is None
    assert all(leg.preference_honoured is None for leg in result.legs)
