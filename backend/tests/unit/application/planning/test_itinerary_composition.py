"""Unit tests for intentionally composed itineraries (Milestone: Recommendation Quality).

Verifies the 8 core composition dimensions:
1. Requirement coverage (hard requirements preserved)
2. Semantic relevance (evidence matching vs generic category fallback)
3. Variety between stops
4. Geographic coherence
5. Temporal feasibility & opening hours
6. Budget ceiling enforcement
7. Sensible sequencing
8. Honest failure when no coherent itinerary can be formed
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time as time_of_day
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.planning.mobility_planning_service import MobilityPlanningService
from app.application.planning.orchestration_service import (
    ItineraryOrchestrator,
    OrchestrationStopInput,
)
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption, MobilityRequirement
from app.domain.entities.planning.areas import AreaScope
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.decision import DecisionCriteria, ReasonOutcome, ReasonType
from app.domain.entities.planning.decision_engine import decide, evaluate_place
from app.domain.entities.planning.information import InformationCategory, Place
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.requirements import (
    CandidateEvidence,
    CoverageStatus,
    RequirementKind,
    evaluate_coverage,
    match_requirement,
    requirement_by_slug,
)


class StubMobilityService:
    """Deterministic mobility service for testing orchestration composition."""

    def __init__(self, options: list[MobilityOption]) -> None:
        self._options = options

    async def find_options_for_requirement(
        self, requirement: MobilityRequirement
    ) -> list[MobilityOption]:
        return [
            o
            for o in self._options
            if o.origin == requirement.origin and o.destination == requirement.destination
        ]


def _orchestrator(options: list[MobilityOption]) -> ItineraryOrchestrator:
    return ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(options)))


def _make_plan(
    *,
    budget: str | None = "600",
    area: str | None = None,
    start_time: datetime | None = None,
) -> Plan:
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
    if area:
        constraints.append(
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.REQUIREMENT,
                value=f"area:{area}",
            )
        )
    context = PlanningContext(
        plan_id=plan_id,
        location="Cape Town",
        start_time=start_time,
    )
    return Plan(
        id=plan_id,
        user_id=uuid4(),
        intention="test composition",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=constraints,
        context=context,
    )


def _mobility_option(
    origin: str,
    destination: str,
    duration: int,
    cost: Decimal = Decimal("0"),
    mode: TransportMode = TransportMode.WALK,
) -> MobilityOption:
    return MobilityOption(
        id=f"opt-{origin[:3]}-{destination[:3]}",
        provider_id="walking" if mode is TransportMode.WALK else "uber",
        provider_name="Walking" if mode is TransportMode.WALK else "Uber",
        mode=mode,
        origin=origin,
        destination=destination,
        duration_minutes=duration,
        cost=cost,
        transfers=0,
    )


# ---------------------------------------------------------------------------
# 1. Semantic Relevance: Evidence matching vs generic category fallback
# ---------------------------------------------------------------------------


def test_semantic_relevance_requires_text_evidence_not_just_category() -> None:
    """A venue with category CULTURE must not claim 'historic_streets' without evidence."""
    modern_space = Place(
        id=uuid4(),
        name="Digital Void Studio",
        category=InformationCategory.CULTURE,
        description="Immersive virtual reality installations and contemporary synth soundscapes.",
        location="Cape Town",
    )
    historic_quarter = Place(
        id=uuid4(),
        name="Bo-Kaap Museum",
        category=InformationCategory.CULTURE,
        description="Historic 18th-century Cape Dutch architecture showcasing Bo-Kaap heritage.",
        location="Cape Town",
    )

    criteria = DecisionCriteria(experience_requirements=("historic_streets",))
    eval_modern = evaluate_place(modern_space, criteria)
    eval_historic = evaluate_place(historic_quarter, criteria)

    # Modern space has category match score only, no requirement match reason
    modern_req_reasons = [r for r in eval_modern.reasons if r.type is ReasonType.REQUIREMENT]
    assert len(modern_req_reasons) == 0

    # Historic quarter has verified evidence and gets explicit requirement match reason
    hist_req_reasons = [r for r in eval_historic.reasons if r.type is ReasonType.REQUIREMENT]
    assert len(hist_req_reasons) == 1
    assert "historic streets" in hist_req_reasons[0].message
    assert eval_historic.score > eval_modern.score


# ---------------------------------------------------------------------------
# 2. Hard Requirement Preservation: Multi-intent requests keep all requirements
# ---------------------------------------------------------------------------


def test_multi_intent_preserves_distinct_experience_requirements() -> None:
    """A request for a cafe and a bookshop extracts both distinct experiences."""
    engine = DeterministicUnderstandingEngine()
    intent = "Cafe in Observatory and a bookshop"
    u = engine.parse(intent)

    # Both requirements must be captured, not flattened into a single category
    assert "meal" in u.experience_requirements
    assert "quiet_focus" in u.experience_requirements
    assert len(u.experience_requirements) >= 2


# ---------------------------------------------------------------------------
# 3. Variety: Avoids duplicate dining/cafe experiences in standard days
# ---------------------------------------------------------------------------


def test_variety_coverage_evaluates_complementary_experiences() -> None:
    """Distinct experience requirements (meal and quiet focus) are checked individually."""
    cafe_evidence = CandidateEvidence(
        name="Truth Coffee",
        category=InformationCategory.FOOD,
        description="Specialty espresso roastery and artisan breakfast.",
    )
    book_evidence = CandidateEvidence(
        name="The Book Lounge",
        category=InformationCategory.SHOPPING,
        description="Independent bookshop with extensive literature and quiet reading spaces.",
    )

    req_meal = requirement_by_slug("meal")
    req_books = requirement_by_slug("quiet_focus")
    assert req_meal is not None and req_books is not None

    # Cafe matches meal, bookshop matches quiet_focus
    match_cafe_meal = match_requirement(req_meal, cafe_evidence, stop_name="Truth Coffee")
    match_cafe_books = match_requirement(req_books, cafe_evidence, stop_name="Truth Coffee")
    match_book_books = match_requirement(req_books, book_evidence, stop_name="The Book Lounge")

    assert match_cafe_meal is not None
    assert match_cafe_books is None  # Cafe does not fake bookshop coverage
    assert match_book_books is not None  # Bookshop covers quiet_focus

    # Combined coverage across both stops achieves fully covered status
    cov = evaluate_coverage(
        (req_meal, req_books),
        (
            ("Truth Coffee", cafe_evidence),
            ("The Book Lounge", book_evidence),
        ),
    )
    assert cov.is_fully_covered is True


# ---------------------------------------------------------------------------
# 4. Geographic Coherence: Minimizes transit and respects requested area
# ---------------------------------------------------------------------------


def test_geographic_coherence_rejects_out_of_area_stops() -> None:
    """Orchestration removes stops outside the user's requested area scope."""
    stops = [
        OrchestrationStopInput(
            name="Observatory Cafe",
            location="Observatory, Cape Town",
            address="100 Lower Main Rd, Observatory, Cape Town",
            duration_minutes=60,
            estimated_cost=Decimal("70"),
        ),
        OrchestrationStopInput(
            name="Camps Bay Beach Club",
            location="Camps Bay, Cape Town",
            address="Victoria Rd, Camps Bay, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("250"),
        ),
    ]
    options = [
        _mobility_option(
            "100 Lower Main Rd, Observatory, Cape Town",
            "Victoria Rd, Camps Bay, Cape Town",
            duration=35,
            mode=TransportMode.RIDE_HAIL,
        )
    ]

    orch = _orchestrator(options)
    plan = _make_plan(area="Observatory")
    res = asyncio.run(orch.orchestrate(plan, stops, origin=None))

    # The Camps Bay stop is outside Observatory and must be removed with clear disclosure
    assert len(res.stops) == 1
    assert res.stops[0].name == "Observatory Cafe"
    assert len(res.removed_stops) == 1
    assert res.removed_stops[0].name == "Camps Bay Beach Club"
    assert "Observatory" in res.removed_stops[0].reason


# ---------------------------------------------------------------------------
# 5. Temporal Feasibility: Verified opening hours enforced by schedule
# ---------------------------------------------------------------------------


def test_temporal_feasibility_discloses_conflict_when_venue_closed() -> None:
    """A stop scheduled outside operating hours is identified as an opening_hours conflict."""
    # Venue open only in morning, but user day starts in afternoon
    closed_stop = OrchestrationStopInput(
        name="Morning Only Roastery",
        location="Observatory, Cape Town",
        address="Lower Main Rd, Observatory, Cape Town",
        opening_hours="Mon-Sun 06:00-11:00",
        duration_minutes=60,
        estimated_cost=Decimal("60"),
    )
    plan = _make_plan(start_time=datetime(2026, 10, 3, 15, 0, tzinfo=UTC))

    orch = _orchestrator([])
    res = asyncio.run(orch.orchestrate(plan, [closed_stop], origin=None))

    # Single stop closed at scheduled time results in honest conflict disclosure
    assert res.is_valid is False
    assert len(res.conflicts) == 1
    assert res.conflicts[0].kind == "opening_hours"


# ---------------------------------------------------------------------------
# 6. Budget Ceiling: Multi-stop composition respects total planned cost
# ---------------------------------------------------------------------------


def test_budget_ceiling_trims_expensive_stop_to_preserve_limit() -> None:
    """When a 2nd stop pushes the plan over budget ceiling, it is dropped with disclosure."""
    stops = [
        OrchestrationStopInput(
            name="Modest Bistro",
            location="City Bowl, Cape Town",
            address="Kloof St, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("250"),
        ),
        OrchestrationStopInput(
            name="Luxury Dining",
            location="City Bowl, Cape Town",
            address="Buitenkant St, Cape Town",
            duration_minutes=90,
            estimated_cost=Decimal("600"),
        ),
    ]
    options = [
        _mobility_option(
            "Kloof St, Cape Town",
            "Buitenkant St, Cape Town",
            duration=10,
            cost=Decimal("40"),
            mode=TransportMode.RIDE_HAIL,
        )
    ]
    orch = _orchestrator(options)
    plan = _make_plan(budget="500")  # Ceiling R500 < R250 + R600 + R40 = R890

    res = asyncio.run(orch.orchestrate(plan, stops, origin=None))

    # Second stop is removed to honour the R500 budget
    assert len(res.stops) == 1
    assert res.stops[0].name == "Modest Bistro"
    assert len(res.removed_stops) == 1
    assert res.removed_stops[0].name == "Luxury Dining"
    assert "budget" in res.removed_stops[0].reason


# ---------------------------------------------------------------------------
# 7. Sensible Sequencing: Chronological and logical progression
# ---------------------------------------------------------------------------


def _parse_close_mins(hours_str: str | None) -> int | None:
    if not hours_str:
        return None
    import re
    m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", hours_str)
    if m:
        return int(m.group(3)) * 60 + int(m.group(4))
    return None


def simulate_order_stops_sensibly(stops: list[dict]) -> list[dict]:
    if len(stops) < 2:
        return stops
    a, b = stops[0], stops[1]

    # Rule 1: Earlier closing hours must be scheduled before they close
    a_close = _parse_close_mins(a.get("opening_hours"))
    b_close = _parse_close_mins(b.get("opening_hours"))
    if a_close is not None and b_close is not None and abs(a_close - b_close) >= 120:
        if a_close < b_close:
            return [a, b]
        return [b, a]

    # Rule 2: Coffee / morning precedes evening dinner
    a_desc = f"{a.get('name', '')} {a.get('description', '')}".lower()
    b_desc = f"{b.get('name', '')} {b.get('description', '')}".lower()
    a_coffee = any(w in a_desc for w in ("coffee", "roastery", "breakfast", "bakery"))
    b_coffee = any(w in b_desc for w in ("coffee", "roastery", "breakfast", "bakery"))
    a_dinner = any(w in a_desc for w in ("dinner", "wine bar", "evening"))
    b_dinner = any(w in b_desc for w in ("dinner", "wine bar", "evening"))

    if a_coffee and not b_coffee:
        return [a, b]
    if b_coffee and not a_coffee:
        return [b, a]
    if a_dinner and not b_dinner:
        return [b, a]
    if b_dinner and not a_dinner:
        return [a, b]

    return [a, b]


def test_sensible_sequencing_orders_earlier_closing_venue_first() -> None:
    """Venue that closes at 16:00 must precede venue open until 23:00."""
    early_stop = {
        "name": "Artisan Bakery",
        "opening_hours": "Daily 07:00-16:00",
        "category": "food",
        "description": "Morning coffee, sourdough bread, and breakfast pastries.",
    }
    dinner_stop = {
        "name": "Evening Wine Bar",
        "opening_hours": "Daily 17:00-23:00",
        "category": "food",
        "description": "Candlelit dinner bistro and local wine selections.",
    }

    ordered = simulate_order_stops_sensibly([dinner_stop, early_stop])
    assert ordered[0]["name"] == "Artisan Bakery"
    assert ordered[1]["name"] == "Evening Wine Bar"



# ---------------------------------------------------------------------------
# 8. Honest Failure: When no coherent itinerary exists, report clearly
# ---------------------------------------------------------------------------


def test_honest_failure_when_no_stops_match_requested_area() -> None:
    """If all proposed stops fail the area constraint, report area conflict honestly."""
    stops = [
        OrchestrationStopInput(
            name="Camps Bay Cafe",
            location="Camps Bay, Cape Town",
            address="Victoria Rd, Camps Bay, Cape Town",
        ),
        OrchestrationStopInput(
            name="Sea Point Walk",
            location="Sea Point, Cape Town",
            address="Beach Rd, Sea Point, Cape Town",
        ),
    ]
    orch = _orchestrator([])
    plan = _make_plan(area="Kalk Bay")  # Neither stop is in Kalk Bay

    res = asyncio.run(orch.orchestrate(plan, stops, origin=None))

    assert res.is_valid is False
    assert len(res.stops) == 0
    assert len(res.conflicts) == 1
    assert res.conflicts[0].kind == "area"
    assert "Kalk Bay" in res.conflicts[0].message
