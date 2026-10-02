"""Geographic intent as a hard planning constraint.

A user who says "in Southern Suburbs" has said where the day must happen. These
tests pin the behaviour that used to be missing: the request was understood,
displayed, and then ignored, so a Southern Suburbs plan came back with venues in
Camps Bay, Bo-Kaap and the City Bowl.

The scenario is the reported one:

    "Lunch for two in Southern Suburbs for R400 includes outdoor activity, garden"
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from datetime import time as time_of_day
from decimal import Decimal
from uuid import uuid4

from app.application.planning.information import OptionSearchCriteria
from app.application.planning.mobility_planning_service import MobilityPlanningService
from app.application.planning.orchestration_service import (
    ItineraryOrchestrator,
    OrchestratedStop,
    OrchestrationStopInput,
    _Attempt,
    _closed_at_scheduled_time,
    _hard_blocker,
    _plan_area,
)
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption
from app.domain.entities.planning.areas import (
    AreaScope,
    AreaStatus,
    classify_in_area,
    resolve_area_scope,
)
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.decision import DecisionCriteria, ReasonOutcome, ReasonType
from app.domain.entities.planning.decision_engine import evaluate_place
from app.domain.entities.planning.information import InformationCategory, Place
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.transition import ItineraryFeasibility
from app.infrastructure.planning.openstreetmap_provider import (
    ACTIVITIES_CATALOG,
    PLACES_CATALOG,
    OpenStreetMapInformationProvider,
)

REQUEST = "Lunch for two in Southern Suburbs for R400 includes outdoor activity, garden"

# Real localities from the catalog, so these tests exercise the same matching the
# product runs on rather than hand-written strings.
NEWLANDS = "Rhodes Dr, Newlands, Cape Town"
CONSTANTIA = "Silvermist Wine Estate, Constantia Nek, Cape Town"
CAMPS_BAY = "270 Victoria Rd, Camps Bay, Cape Town"
BO_KAAP = "71 Wale St, Bo-Kaap, Cape Town"
CITY_BOWL = "15 Queen Victoria St, City Bowl, Cape Town"
ORIGIN = "Observatory, Cape Town"


def _southern() -> AreaScope:
    scope = resolve_area_scope("Southern Suburbs")
    assert scope is not None
    return scope


def _place(name: str, address: str, price: str = "100") -> Place:
    return Place(
        name=name,
        location="Cape Town",
        category=InformationCategory.FOOD,
        description=f"{name} in {address}.",
        price_from=Decimal(price),
        address=address,
    )


def _location_reason(candidate) -> ReasonOutcome:
    return next(r for r in candidate.reasons if r.type is ReasonType.LOCATION).outcome


# --- 1/2/3: the named suburbs must be rejected -----------------------------


def test_southern_suburbs_request_rejects_camps_bay_candidate() -> None:
    candidate = evaluate_place(
        _place("Grand Pavilion Camps Bay", CAMPS_BAY),
        DecisionCriteria(location="Southern Suburbs"),
    )

    assert candidate.is_eligible is False
    assert _location_reason(candidate) is ReasonOutcome.VIOLATED
    assert "Southern Suburbs" in next(
        r for r in candidate.reasons if r.type is ReasonType.LOCATION
    ).message


def test_southern_suburbs_request_rejects_bok_aap_candidate() -> None:
    candidate = evaluate_place(
        _place("Bo-Kaap Museum", BO_KAAP), DecisionCriteria(location="Southern Suburbs")
    )

    assert candidate.is_eligible is False
    assert _location_reason(candidate) is ReasonOutcome.VIOLATED


def test_southern_suburbs_request_rejects_city_bowl_candidate() -> None:
    candidate = evaluate_place(
        _place("Company's Garden", CITY_BOWL), DecisionCriteria(location="Southern Suburbs")
    )

    assert candidate.is_eligible is False
    assert _location_reason(candidate) is ReasonOutcome.VIOLATED


# --- 4: a genuine Southern Suburbs candidate is accepted --------------------


def test_genuine_southern_suburbs_candidate_satisfies_the_requirement() -> None:
    newlands = evaluate_place(
        _place("Kirstenbosch National Botanical Garden", NEWLANDS),
        DecisionCriteria(location="Southern Suburbs"),
    )
    constantia = evaluate_place(
        _place("La Colombe Fine Dining", CONSTANTIA),
        DecisionCriteria(location="Southern Suburbs"),
    )

    assert newlands.is_eligible is True
    assert constantia.is_eligible is True
    assert _location_reason(newlands) is ReasonOutcome.SUPPORTED
    # "Constantia Nek" is read as Constantia rather than missed for the extra word.
    assert _location_reason(constantia) is ReasonOutcome.SUPPORTED


def test_city_wide_request_imposes_no_area_constraint() -> None:
    """A Cape Town request must keep the whole city eligible, as before."""
    scope = resolve_area_scope("Cape Town")

    assert scope is None
    for address in (NEWLANDS, CAMPS_BAY, BO_KAAP, CITY_BOWL):
        verdict = classify_in_area(scope, address=address, location="Cape Town")
        assert verdict.status is AreaStatus.MATCH


def test_venue_outside_the_radius_is_outside_even_by_its_own_coordinates() -> None:
    """The coordinate check places a venue whose address names no in-area suburb."""
    scope = _southern()
    woodstock = next(p for p in PLACES_CATALOG if p.name == "The Pot Luck Club")

    verdict = classify_in_area(
        scope,
        address=woodstock.address,
        location=woodstock.location,
        latitude=woodstock.latitude,
        longitude=woodstock.longitude,
    )

    assert verdict.status is AreaStatus.OUTSIDE


def test_no_catalog_venue_outside_the_area_is_admitted() -> None:
    """Guard against the area check accidentally admitting the wider catalog."""
    scope = _southern()

    for activity in ACTIVITIES_CATALOG:
        verdict = classify_in_area(
            scope,
            address=activity.address,
            location=activity.location,
            latitude=activity.latitude,
            longitude=activity.longitude,
        )
        if activity.address == NEWLANDS:
            assert verdict.status is AreaStatus.MATCH, activity.name
        else:
            assert verdict.status is not AreaStatus.MATCH, activity.name


def test_a_venue_with_no_geographic_evidence_is_unknown_not_a_match() -> None:
    """No address and no coordinates cannot be shown to be in the area."""
    verdict = classify_in_area(_southern(), address=None, location=None)

    assert verdict.status is AreaStatus.UNKNOWN


# --- Understanding keeps the area as structured intent ----------------------


def test_understanding_retains_the_named_region_whole() -> None:
    understanding = DeterministicUnderstandingEngine().parse(REQUEST)

    assert understanding.location == "Southern Suburbs"
    assert understanding.location_is_inferred is False
    assert understanding.people_count == 2
    assert understanding.budget_amount == Decimal("400")


def test_understanding_keeps_a_named_suburb_as_the_area() -> None:
    understanding = DeterministicUnderstandingEngine().parse("Lunch in Claremont for two")

    assert understanding.location == "Claremont"
    assert understanding.location_is_inferred is False


# --- the search must not widen itself ---------------------------------------


def _provider() -> OpenStreetMapInformationProvider:
    provider = OpenStreetMapInformationProvider.__new__(OpenStreetMapInformationProvider)
    provider._enable_network = False
    return provider


def test_provider_does_not_widen_the_search_beyond_the_requested_area() -> None:
    """The provider returns the in-area venues only, not the whole catalog.

    Before this, an area filter that matched nothing fell back to "Cape Town" and
    handed back all 19 places, which is how a Southern Suburbs request came to be
    served from Camps Bay.
    """
    provider = _provider()
    criteria = OptionSearchCriteria(location="Southern Suburbs", geographic_anchor="Cape Town")

    assert {p.name for p in asyncio.run(provider.find_places(criteria))} == {
        "Kirstenbosch National Botanical Garden",
        "La Colombe Fine Dining",
        "Arderne Gardens",
        "Newlands Forest",
        "Montebello Design Centre",
        "Chart Farm",
    }
    assert [a.name for a in asyncio.run(provider.find_activities(criteria))] == [
        "Kirstenbosch Boomslang Canopy Walk"
    ]


def test_provider_still_widens_for_a_city_wide_request() -> None:
    provider = _provider()
    criteria = OptionSearchCriteria(location="Cape Town", geographic_anchor="Cape Town")

    assert len(asyncio.run(provider.find_places(criteria))) == len(PLACES_CATALOG)


# --- 5/6: final-plan validation ---------------------------------------------


class _StubMobility:
    def __init__(self) -> None:
        self._options = [
            MobilityOption(
                id=f"uber-{index}",
                provider_id="uber",
                provider_name="Uber",
                mode=TransportMode.RIDE_HAIL,
                origin=origin,
                destination=destination,
                duration_minutes=20,
                cost=None,
                cost_is_unknown=True,
                transfers=0,
            )
            for index, (origin, destination) in enumerate(
                (
                    (ORIGIN, NEWLANDS),
                    (NEWLANDS, NEWLANDS),
                    (NEWLANDS, CAMPS_BAY),
                )
            )
        ]

    async def find_options_for_requirement(self, requirement) -> list[MobilityOption]:
        return [
            o
            for o in self._options
            if o.origin == requirement.origin and o.destination == requirement.destination
        ]


def _stop(name: str, address: str, minutes: int = 60, cost: str = "100") -> OrchestrationStopInput:
    return OrchestrationStopInput(
        name=name,
        location=address,
        address=address,
        duration_minutes=minutes,
        estimated_cost=Decimal(cost),
    )


def _scheduled_stop(name: str, address: str, start: datetime, hours: str | None = None) -> OrchestratedStop:
    return OrchestratedStop(
        name=name,
        location=address,
        address=address,
        opening_hours=hours,
        phone=None,
        source_url=None,
        reservation_url=None,
        category=None,
        estimated_cost=None,
        duration_minutes=60,
        start_time=start,
        end_time=start + timedelta(minutes=60),
    )


def _area_plan() -> Plan:
    """A plan carrying the stated area as a persisted geographic requirement."""
    plan_id = uuid4()
    return Plan(
        id=plan_id,
        user_id=uuid4(),
        intention=REQUEST,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=[
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.REQUIREMENT,
                value="area:Southern Suburbs",
            ),
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.BUDGET_MAX,
                value="R400",
                numeric_value=Decimal("400"),
            ),
        ],
        context=PlanningContext(
            plan_id=plan_id,
            location="Southern Suburbs",
            start_time=datetime.combine(datetime.now().date(), time_of_day(12, 30)),
            group_size=2,
        ),
    )


def _orchestrate(plan: Plan, stops: list[OrchestrationStopInput]):
    orch = ItineraryOrchestrator(MobilityPlanningService(_StubMobility()))
    return asyncio.run(orch.orchestrate(plan, stops, origin=ORIGIN, party_size=2))


def test_final_plan_validation_removes_an_out_of_area_stop() -> None:
    result = _orchestrate(
        _area_plan(),
        [
            _stop("Kirstenbosch National Botanical Garden", NEWLANDS),
            _stop("Grand Pavilion Camps Bay", CAMPS_BAY),
        ],
    )

    # The Camps Bay stop never reaches the schedule; the day stays in the area.
    assert [s.name for s in result.stops] == ["Kirstenbosch National Botanical Garden"]
    assert [r.name for r in result.removed_stops] == ["Grand Pavilion Camps Bay"]
    assert "Southern Suburbs" in result.removed_stops[0].reason
    assert result.is_valid is True
    assert result.conflicts == ()


def test_final_plan_validation_catches_a_stop_left_outside_the_area() -> None:
    """The final check catches an out-of-area stop independently of the pre-filter.

    The pre-filter runs before transport is priced; this is the last gate before
    the plan is presented, and it fails the plan rather than warning about it.
    """
    start = datetime.now(UTC)
    attempt = _Attempt(
        day_start=start,
        stops=[
            _scheduled_stop("Kirstenbosch", NEWLANDS, start),
            _scheduled_stop("Bo-Kaap Museum", BO_KAAP, start + timedelta(minutes=90)),
        ],
        legs=[],
        feasibility=ItineraryFeasibility(),
    )

    blocker = _hard_blocker(attempt, _area_plan(), _southern())

    assert blocker is not None
    assert blocker[0] == "area"
    assert "Southern Suburbs" in blocker[1]


def test_unsatisfiable_area_produces_a_structured_conflict_not_a_widened_plan() -> None:
    """No in-area candidate: refuse, rather than fall back to the rest of the city."""
    result = _orchestrate(
        _area_plan(),
        [
            _stop("Grand Pavilion Camps Bay", CAMPS_BAY),
            _stop("Bo-Kaap Museum", BO_KAAP),
            _stop("Company's Garden", CITY_BOWL),
        ],
    )

    assert result.is_valid is False
    assert [c.kind for c in result.conflicts] == ["area"]
    assert "couldn't build the day within Southern Suburbs" in result.conflicts[0].message
    # The wider city is not offered as a substitute.
    assert result.stops == []
    assert {r.name for r in result.removed_stops} == {
        "Grand Pavilion Camps Bay",
        "Bo-Kaap Museum",
        "Company's Garden",
    }


def test_plan_area_is_read_from_the_persisted_requirement() -> None:
    scope = _plan_area(_area_plan())

    assert scope is not None
    assert scope.label == "Southern Suburbs"


def test_a_city_plan_carries_no_area_constraint() -> None:
    plan = _area_plan()
    plan.constraints = [c for c in plan.constraints if not c.value.startswith("area:")]
    plan.context = PlanningContext(plan_id=plan.id, location="Cape Town", group_size=2)

    assert _plan_area(plan) is None


# --- 8: opening hours are checked at the stop's own scheduled time ----------


def test_opening_hours_are_checked_at_the_stops_own_scheduled_time() -> None:
    """A late stop at a venue that has shut must not pass on the day's start time.

    The venue opens 11:00-16:00. Checking every stop against the time the day
    begins would clear a stop that is not reached until 17:00.
    """
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(
        second=0, microsecond=0
    )
    late = _scheduled_stop("Late Stop", NEWLANDS, tomorrow.replace(hour=17, minute=0), "Daily 11:00-16:00")
    on_time = _scheduled_stop("Early Stop", NEWLANDS, tomorrow.replace(hour=13, minute=0), "Daily 11:00-16:00")

    closed = _closed_at_scheduled_time(late)
    assert closed is not None
    assert "17:00" in closed
    assert _closed_at_scheduled_time(on_time) is None


def test_missing_opening_hours_is_not_treated_as_closed() -> None:
    stop = _scheduled_stop("Unverified", NEWLANDS, datetime.now().astimezone(), None)

    assert _closed_at_scheduled_time(stop) is None
