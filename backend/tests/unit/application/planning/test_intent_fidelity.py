"""M17 — intent fidelity and hard constraint enforcement.

These cover the acceptance scenarios:

* A — a request naming several distinct experiences must keep them distinct, and
  the plan must show evidence for the ones it covers.
* B — a stated latest end time must be satisfied by the schedule itself, travel
  included, not merely reported as a warning.
* C — costs must stay honest across known, estimated and unavailable.
* D — a request that cannot fit must produce an explicit conflict rather than a
  plan that quietly breaks the user's limit.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time as time_of_day, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.planning.mobility_planning_service import MobilityPlanningService
from app.application.planning.orchestration_service import (
    ItineraryOrchestrator,
    OrchestrationStopInput,
    _plan_deadline,
)
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption, MobilityRequirement
from app.application.planning.selection_service import criteria_from_plan
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.decision import DecisionCriteria
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
    requirements_from_slugs,
)
from app.infrastructure.planning.openstreetmap_provider import ACTIVITIES_CATALOG, PLACES_CATALOG

A = "Smit Street, District Six, Cape Town"
B = "Victoria Road, Camps Bay, Cape Town"
C = "Kalk Bay, Cape Town"
OBS = "Observatory, Cape Town"


class StubMobilityService:
    """Returns fixed options per leg so scheduling is deterministic."""

    def __init__(self, options: list[MobilityOption]) -> None:
        self._options = options

    async def find_options_for_requirement(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        return [
            o
            for o in self._options
            if o.origin == requirement.origin and o.destination == requirement.destination
        ]


def _option(
    provider_id: str,
    origin: str,
    destination: str,
    duration: int | None,
    cost: Decimal | None,
    mode: TransportMode = TransportMode.RIDE_HAIL,
) -> MobilityOption:
    return MobilityOption(
        id=f"{provider_id}-{origin[:3]}-{destination[:3]}",
        provider_id=provider_id,
        provider_name=provider_id.title(),
        mode=mode,
        origin=origin,
        destination=destination,
        duration_minutes=duration,
        cost=cost,
        cost_is_unknown=cost is None,
        transfers=0,
    )


def _legs() -> list[MobilityOption]:
    return [
        _option("uber", OBS, A, 20, None),
        _option("uber", A, B, 15, None),
        _option("uber", B, C, 25, None),
    ]


def _stop(name: str, location: str, address: str, minutes: int, cost: str, description: str = "") -> OrchestrationStopInput:
    return OrchestrationStopInput(
        name=name,
        location=location,
        address=address,
        duration_minutes=minutes,
        estimated_cost=Decimal(cost),
        description=description,
    )


def _stops() -> list[OrchestrationStopInput]:
    return [
        _stop("Museum", "Cape Town", A, 90, "80", "A museum of the city's history."),
        _stop("Pavilion", "Cape Town", B, 90, "150"),
        _stop("Market", "Cape Town", C, 60, "40"),
    ]


def _plan(
    *,
    budget: str | None = None,
    end_time: datetime | None = None,
    start_time: datetime | None = None,
    requirements: tuple[str, ...] = (),
    stated_deadline: bool = True,
) -> Plan:
    """A plan shaped like production output.

    `stated_deadline` controls whether the end time is a limit the user actually
    stated (persisted as a `deadline:` constraint) or merely an inferred window on
    the context, which production does not treat as a limit.
    """
    plan_id = uuid4()
    constraints: list[Constraint] = []
    if budget:
        constraints.append(
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.BUDGET_MAX,
                value=f"R{budget}",
                numeric_value=Decimal(budget),
            )
        )
    if end_time is not None and stated_deadline:
        # Production persists an explicitly stated limit as a deadline constraint;
        # an inferred window never produces one, which is why only this enforces.
        constraints.append(
            Constraint(
                plan_id=plan_id,
                type=ConstraintType.REQUIREMENT,
                value=f"deadline:{end_time:%H:%M}",
            )
        )
    for slug in requirements:
        constraints.append(
            Constraint(plan_id=plan_id, type=ConstraintType.REQUIREMENT, value=f"requirement:{slug}")
        )
    context = None
    if end_time or start_time:
        context = PlanningContext(
            plan_id=plan_id,
            location="Cape Town",
            start_time=start_time or datetime.combine(datetime.now().date(), time_of_day(12, 0)),
            end_time=end_time,
            group_size=4,
        )
    return Plan(
        id=plan_id,
        user_id=uuid4(),
        intention="test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=constraints,
        context=context,
    )


def _orchestrate(plan: Plan, stops: list[OrchestrationStopInput], origin: str | None = None):
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(_legs())))
    return asyncio.run(orch.orchestrate(plan, stops, origin=origin))


# --- Test A: semantic intent ---------------------------------------------------


def test_a_distinct_concepts_are_not_collapsed_into_one() -> None:
    """"local culture, historic streets, and craft food markets" stays three things."""
    understanding = DeterministicUnderstandingEngine().parse(
        "An afternoon exploring local culture, historic streets, and craft food markets."
    )

    assert "local_culture" in understanding.experience_requirements
    assert "historic_streets" in understanding.experience_requirements
    assert "craft_food_market" in understanding.experience_requirements
    # The old broad category list still exists, but it is no longer the only
    # record of what the user asked for.
    assert len(understanding.experience_requirements) >= 3


def test_a_gallery_does_not_satisfy_an_explicit_museum_requirement() -> None:
    understanding = DeterministicUnderstandingEngine().parse("Lunch then museum in Woodstock")
    museum = requirement_by_slug("museum")
    assert museum is not None

    gallery = CandidateEvidence(
        name="Goodman Gallery Cape Town",
        category=InformationCategory.CULTURE,
        description="Contemporary art gallery in Woodstock.",
    )
    actual_museum = CandidateEvidence(
        name="District Six Museum",
        category=InformationCategory.CULTURE,
        description="Museum documenting District Six history.",
    )

    assert "museum" in understanding.experience_requirements
    assert "local_culture" not in understanding.experience_requirements
    assert match_requirement(museum, gallery, "Goodman Gallery Cape Town") is None
    assert match_requirement(museum, actual_museum, "District Six Museum") is not None


def test_a_coverage_uses_real_candidate_evidence() -> None:
    """A requirement is only covered when a candidate's own words support it."""
    requirements = requirements_from_slugs(("local_culture", "historic_streets", "craft_food_market"))
    stops = (
        (
            "District Six Museum",
            CandidateEvidence(
                name="District Six Museum",
                description="A museum in the historic District Six, telling the story of the area.",
            ),
        ),
        (
            "Old Biscuit Mill",
            CandidateEvidence(
                name="Old Biscuit Mill",
                description="A weekend craft market and food hall in the old mill.",
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)

    assert coverage.status.value == "covered"
    by_slug = {item.requirement.slug: item for item in coverage.items}
    assert by_slug["historic_streets"].is_covered
    assert by_slug["craft_food_market"].is_covered
    # The evidence names the actual field that matched.
    heritage = by_slug["historic_streets"].matches[0]
    assert heritage.field == "description"
    assert "historic" in heritage.term


def test_a_category_alone_does_not_count_as_coverage() -> None:
    """A broad category is not proof a specific request was met."""
    requirement = requirement_by_slug("historic_streets")
    assert requirement is not None
    evidence = CandidateEvidence(name="Some Restaurant", category=InformationCategory.CULTURE)

    assert match_requirement(requirement, evidence, "Some Restaurant") is None


def test_a_uncovered_requirement_is_reported_not_assumed() -> None:
    """A requirement nothing supports is stated as missing, never ticked off."""
    stops = [_stop("Pavilion", "Cape Town", B, 90, "150", "A seaside restaurant with ocean views.")]
    result = _orchestrate(_plan(requirements=("historic_streets",)), stops, origin=OBS)

    assert result.coverage is not None
    uncovered = [i.requirement.slug for i in result.coverage.uncovered]
    assert "historic_streets" in uncovered
    assert result.coverage.status.value == "not_covered"
    # An unmet preference is disclosed, not a violated hard constraint.
    assert result.is_valid is True


# --- Test A (reading): a quiet-focus intent is a checkable experience ----------


def test_a_reading_request_becomes_a_checkable_experience_requirement() -> None:
    """'read somewhere cozy' is not flattened into a food/culture/nature vibe.

    A request to read must surface as a distinct, checkable requirement so that
    coverage can report it honestly instead of claiming a lunch stop was lunch.
    """
    understanding = DeterministicUnderstandingEngine().parse("Read somewhere cozy this afternoon.")

    assert "quiet_focus" in understanding.experience_requirements
    # The broad categories that would normally stand in for a missing intent
    # must not be invented here: there is no food, culture, nature or "fun" ask.
    for broad in (InformationCategory.FOOD, InformationCategory.NATURE, InformationCategory.CULTURE, InformationCategory.ENTERTAINMENT):
        assert broad not in understanding.activity_types


def test_a_fun_word_does_not_substitute_when_a_primary_intent_is_stated() -> None:
    """'fun' must not widen a day that already named a specific experience."""
    understanding = DeterministicUnderstandingEngine().parse("Read somewhere cozy, maybe something fun later.")

    assert "quiet_focus" in understanding.experience_requirements
    assert "fun" in understanding.preferences
    for broad in (InformationCategory.FOOD, InformationCategory.NATURE, InformationCategory.CULTURE):
        assert broad not in understanding.activity_types


def test_a_pure_fun_request_still_gets_broadened_categories() -> None:
    """Broadening stays in place when fun *is* the only thing asked for."""
    understanding = DeterministicUnderstandingEngine().parse("Me and 4 friends want to do something fun this weekend.")

    assert "fun" in understanding.preferences
    assert InformationCategory.FOOD in understanding.activity_types
    assert InformationCategory.NATURE in understanding.activity_types
    assert InformationCategory.CULTURE in understanding.activity_types
    # No specific experience was named, so none is recorded as a requirement.
    assert "quiet_focus" not in understanding.experience_requirements


def test_a_uncovered_reading_requirement_is_reported_not_assumed() -> None:
    """A reading request with no reading venue is disclosed, not substituted.

    A garden (nature) is the kind of stop that would silently stand in for a
    reading request. Coverage must reject that: category alone is not proof.
    """
    requirements = requirements_from_slugs(("quiet_focus",))
    stops = (
        (
            "Kirstenbosch",
            CandidateEvidence(
                name="Kirstenbosch Botanical Garden",
                description="Gardens and mountain walks with indigenous flora and canopy trails.",
                category=InformationCategory.NATURE,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)
    by_slug = {item.requirement.slug: item for item in coverage.items}
    assert by_slug["quiet_focus"].is_covered is False
    assert coverage.status.value == "not_covered"


def test_a_real_reading_venue_covers_the_requirement() -> None:
    """When a candidate's own text speaks of reading, it is honestly covered."""
    requirements = requirements_from_slugs(("quiet_focus",))
    stops = (
        (
            "Huguenot Library",
            CandidateEvidence(
                name="Huguenot Library & Reading Room",
                description="A quiet library with study desks and a quiet reading room open daily.",
                category=InformationCategory.CULTURE,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)
    by_slug = {item.requirement.slug: item for item in coverage.items}
    assert by_slug["quiet_focus"].is_covered is True
    assert coverage.is_fully_covered is True


# --- Test B: latest end time ---------------------------------------------------


def test_b_stated_end_time_is_satisfied_by_the_schedule() -> None:
    """The plan must finish in time; a warning afterwards is not enough."""
    start = datetime.combine(datetime.now().date(), time_of_day(13, 0))
    limit = datetime.combine(datetime.now().date(), time_of_day(15, 30))
    plan = _plan(start_time=start, end_time=limit)

    result = _orchestrate(plan, _stops(), origin=OBS)

    assert result.feasibility is not None
    assert result.feasibility.deadline_respected is True
    # Travel is inside the schedule, so the last stop really does end in time.
    assert result.stops[-1].end_time <= limit
    # ...and no leg contributes zero time between consecutive stops.
    for previous, current in zip(result.stops, result.stops[1:], strict=False):
        assert current.start_time > previous.end_time


def test_b_overrunning_stops_are_removed_not_merely_warned_about() -> None:
    """Stops that cannot fit are dropped, and the drop is stated.

    After trimming, the plan does honour the limit, so it is valid — the removal
    is disclosed to the user rather than silently applied.
    """
    start = datetime.combine(datetime.now().date(), time_of_day(13, 0))
    limit = datetime.combine(datetime.now().date(), time_of_day(15, 30))
    plan = _plan(start_time=start, end_time=limit)

    result = _orchestrate(plan, _stops(), origin=OBS)

    assert result.stops[-1].end_time <= limit
    assert [s.name for s in result.removed_stops], "the overrun should have been reported"
    assert "limit" in result.removed_stops[0].reason
    assert result.is_valid is True
    assert result.conflicts == ()


def test_b_an_inferred_window_is_not_treated_as_a_hard_limit() -> None:
    """No stated limit means no limit: a default window must not drop stops.

    A context end time with no `deadline:` constraint came from an inferred
    window such as "afternoon", not from anything the user said. Enforcing it
    would silently remove stops from a day nobody bounded.
    """
    start = datetime.combine(datetime.now().date(), time_of_day(13, 0))
    inferred_end = datetime.combine(datetime.now().date(), time_of_day(15, 0))
    plan = _plan(start_time=start, end_time=inferred_end, stated_deadline=False)

    result = _orchestrate(plan, _stops(), origin=OBS)

    assert result.removed_stops == ()
    assert result.conflicts == ()
    assert result.is_valid is True
    assert len(result.stops) == 3


def test_b_travel_time_is_never_a_zero_minute_window() -> None:
    """Each gap between stops must be at least the selected leg's travel time."""
    start = datetime.combine(datetime.now().date(), time_of_day(9, 0))
    limit = datetime.combine(datetime.now().date(), time_of_day(20, 0))
    result = _orchestrate(_plan(start_time=start, end_time=limit), _stops(), origin=OBS)

    for previous, current in zip(result.stops, result.stops[1:], strict=False):
        gap = (current.start_time - previous.end_time).total_seconds() / 60
        assert gap > 0, "a zero-minute travel window must never be scheduled"


def test_b_a_wall_clock_deadline_is_enforced_against_utc_instants() -> None:
    """A stated "finished by 15:30" must not gain hours by being compared to UTC.

    Stored instants are timezone-aware, but the user states a wall-clock time. If
    the stated time is not converted into the plan's own frame, an afternoon that
    visibly runs past the limit is accepted as fine.
    """
    utc = timezone.utc
    # 12:00 UTC is 14:00 local (UTC+2), so a 15:30 local limit is 13:30 UTC.
    start = datetime.combine(datetime.now().date(), time_of_day(12, 0), tzinfo=utc)
    plan_id = uuid4()
    constraints = [
        Constraint(
            plan_id=plan_id, type=ConstraintType.REQUIREMENT, value="deadline:15:30"
        )
    ]
    plan = Plan(
        id=plan_id,
        user_id=uuid4(),
        intention="test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=constraints,
        context=PlanningContext(plan_id=plan_id, location="Cape Town", start_time=start, group_size=4),
    )
    stops = [
        _stop("Museum", "Cape Town", A, 30, "80", "A museum of the city's history."),
        _stop("Pavilion", "Cape Town", B, 20, "90"),
        _stop("Market", "Cape Town", C, 30, "40"),
    ]

    result = _orchestrate(plan, stops, origin=OBS)

    deadline = _plan_deadline(plan)
    assert deadline is not None
    assert deadline.hour == 13  # 15:30 local expressed in the stored frame
    # The stop that would have run past the limit is removed, and what remains
    # genuinely finishes inside it.
    assert [s.name for s in result.removed_stops] == ["Market"]
    assert result.stops[-1].end_time <= deadline
    assert result.feasibility is not None
    assert result.feasibility.deadline_respected is True


# --- Test C: budget ------------------------------------------------------------


def test_c_unknown_costs_stay_unknown_and_are_stated_as_a_floor() -> None:
    """Ride-hailing has no verified fare, so the total is a lower bound, not a claim."""
    result = _orchestrate(_plan(budget="800"), _stops(), origin=OBS)

    assert result.feasibility is not None
    assert result.feasibility.has_unknown_transition_costs is True
    assert any("lower bound" in warning for warning in result.feasibility.warnings)
    # Nothing was invented to make the budget look satisfied.
    assert result.feasibility.total_known_transition_cost == Decimal("0")


def test_c_a_known_cost_over_the_cap_is_reported_not_claimed_as_within_budget() -> None:
    """A verified total above the cap must be reported, never dressed up as fitting.

    The only transport for this leg costs R900 against an R500 cap. Dropping the
    final stop still cannot fix it, so the plan keeps what is needed, states the
    overrun, and refuses to present itself as valid.
    """
    legs = [_option("prasa", OBS, A, 20, Decimal("900"), TransportMode.TRAIN)]
    legs.append(_option("prasa", A, B, 15, Decimal("900"), TransportMode.TRAIN))
    legs.append(_option("prasa", B, C, 25, Decimal("900"), TransportMode.TRAIN))
    orch = ItineraryOrchestrator(MobilityPlanningService(StubMobilityService(legs)))
    result = asyncio.run(orch.orchestrate(_plan(budget="500"), _stops(), origin=OBS))

    assert result.feasibility is not None
    assert result.feasibility.budget_respected is False
    assert result.is_valid is False
    assert any(c.kind == "budget" for c in result.conflicts)
    assert result.feasibility.total_known_transition_cost == Decimal("900")
    assert [s.name for s in result.removed_stops]


# --- Test D: impossible / conflicting ------------------------------------------


def test_d_impossible_request_returns_a_conflict_not_a_violation() -> None:
    """One stop that cannot fit the window must be reported, not quietly overrun."""
    start = datetime.combine(datetime.now().date(), time_of_day(13, 0))
    limit = datetime.combine(datetime.now().date(), time_of_day(13, 20))
    stops = [_stop("Long Lunch", "Cape Town", A, 300, "80")]

    result = _orchestrate(_plan(start_time=start, end_time=limit), stops, origin=OBS)

    assert result.feasibility is not None
    assert result.feasibility.deadline_respected is False
    assert result.is_valid is False
    assert any(c.kind == "deadline" for c in result.conflicts)
    # A single stop is the floor, so it is kept but flagged rather than deleted.
    assert len(result.stops) == 1


def test_d_conflict_message_is_actionable() -> None:
    result = _orchestrate(
        _plan(
            start_time=datetime.combine(datetime.now().date(), time_of_day(13, 0)),
            end_time=datetime.combine(datetime.now().date(), time_of_day(13, 20)),
        ),
        [_stop("Long Lunch", "Cape Town", A, 300, "80")],
        origin=OBS,
    )

    assert result.conflicts
    assert "time you gave" in result.conflicts[0].message


# --- Test Cases A through I: End-to-end intent fidelity & regression coverage ---


def test_case_a_peaceful_reading_preserves_primary_requirement() -> None:
    """Case A: 'I want somewhere peaceful to read.'

    Primary requirement must remain reading (quiet_focus).
    Broad food/nature/culture categories must not be injected.
    Candidate evidence for reading/quiet matches; generic nature does not.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want somewhere peaceful to read.")

    assert "quiet_focus" in u.experience_requirements
    assert InformationCategory.FOOD not in u.activity_types
    assert InformationCategory.NATURE not in u.activity_types
    assert InformationCategory.CULTURE not in u.activity_types

    req = requirement_by_slug("quiet_focus")
    assert req is not None
    assert req.kind == RequirementKind.EXPERIENCE

    reading_candidate = CandidateEvidence(
        name="Huguenot Reading Room",
        description="A quiet reading room and library in the city center.",
        category=InformationCategory.CULTURE,
    )
    beach_candidate = CandidateEvidence(
        name="Camps Bay Beach",
        description="A scenic sandy beach with ocean views.",
        category=InformationCategory.NATURE,
    )
    assert match_requirement(req, reading_candidate, "Huguenot Reading Room") is not None
    assert match_requirement(req, beach_candidate, "Camps Bay Beach") is None


def test_case_b_cozy_place_to_work_for_two_hours() -> None:
    """Case B: 'I want a cozy place to work for two hours.'

    Primary requirement must remain working/quiet-use (quiet_focus).
    Cozy is supporting (intimate vibe and cozy preference).
    Duration limit is 120 minutes.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want a cozy place to work for two hours.")

    assert "quiet_focus" in u.experience_requirements
    req_focus = requirement_by_slug("quiet_focus")
    assert req_focus is not None
    assert req_focus.kind == RequirementKind.EXPERIENCE

    # Cozy is recognized as a supporting quality (atmosphere/vibe), not the primary activity
    assert "intimate" in u.experience_requirements
    req_intimate = requirement_by_slug("intimate")
    assert req_intimate is not None
    assert req_intimate.kind == RequirementKind.VIBE
    assert "cozy" in u.preferences

    # Duration limit is correctly extracted as 2 hours (120 minutes)
    assert u.duration_limit_minutes == 120


def test_case_c_romantic_dinner_intimate_preserves_primary_and_supporting() -> None:
    """Case C: 'I want a romantic dinner somewhere intimate.'

    Primary requirement must remain dinner (meal).
    Romantic and intimate are supporting qualities (vibes), not distinct activities.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want a romantic dinner somewhere intimate.")

    assert "meal" in u.experience_requirements
    req_meal = requirement_by_slug("meal")
    assert req_meal is not None
    assert req_meal.kind == RequirementKind.EXPERIENCE

    # Supporting qualities
    assert "romantic" in u.experience_requirements
    req_romantic = requirement_by_slug("romantic")
    assert req_romantic is not None
    assert req_romantic.kind == RequirementKind.VIBE

    assert "intimate" in u.experience_requirements
    req_intimate = requirement_by_slug("intimate")
    assert req_intimate is not None
    assert req_intimate.kind == RequirementKind.VIBE


def test_case_d_historic_architecture_materially_influences_candidate_selection() -> None:
    """Case D: 'I want to explore historic architecture.'

    Historic architecture must materially influence candidate selection.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want to explore historic architecture.")

    assert "historic_streets" in u.experience_requirements
    req_hist = requirement_by_slug("historic_streets")
    assert req_hist is not None
    assert req_hist.kind == RequirementKind.EXPERIENCE

    criteria = DecisionCriteria(
        experience_requirements=u.experience_requirements,
        location="Cape Town",
    )
    historic_place = Place(
        id="hist-1",
        name="Castle of Good Hope",
        category=InformationCategory.CULTURE,
        description="Historic fortress with colonial architecture and heritage tours.",
        location="Cape Town",
    )
    generic_place = Place(
        id="gen-1",
        name="Sea Point Promenade",
        category=InformationCategory.NATURE,
        description="A scenic seaside paved promenade for walking along the ocean.",
        location="Cape Town",
    )

    score_hist = evaluate_place(historic_place, criteria)
    score_gen = evaluate_place(generic_place, criteria)

    # Historic place gets matched requirement points and substantially outranks generic stop
    assert score_hist.score > score_gen.score
    req_reasons = [r for r in score_hist.reasons if r.type.value == "requirement"]
    assert len(req_reasons) > 0
    assert "historic streets" in req_reasons[0].message


def test_case_e_painting_outdoors_survives_into_planning() -> None:
    """Case E: 'I want somewhere outdoors where I can paint.'

    Painting + outdoor must both survive into planning.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want somewhere outdoors where I can paint.")

    assert "painting" in u.experience_requirements
    req_painting = requirement_by_slug("painting")
    assert req_painting is not None
    assert req_painting.kind == RequirementKind.EXPERIENCE

    assert "outdoor" in u.experience_requirements
    req_outdoor = requirement_by_slug("outdoor")
    assert req_outdoor is not None
    assert req_outdoor.kind == RequirementKind.PREFERENCE

    assert u.setting_preference == "outdoor"
    assert "outdoors" in u.preferences


def test_case_f_vintage_shopping_materially_influences_candidate_selection() -> None:
    """Case F: 'I want to browse vintage shops.'

    Vintage shopping must materially influence candidate selection.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I want to browse vintage shops.")

    assert "shopping" in u.experience_requirements
    req_shop = requirement_by_slug("shopping")
    assert req_shop is not None
    assert req_shop.kind == RequirementKind.EXPERIENCE

    criteria = DecisionCriteria(
        experience_requirements=u.experience_requirements,
        location="Cape Town",
    )
    vintage_shop = Place(
        id="shop-1",
        name="Kloof Vintage Thrift",
        category=InformationCategory.CULTURE,
        description="Curated vintage clothing, thrift fashion, and antique curio items.",
        location="Cape Town",
    )
    generic_park = Place(
        id="park-1",
        name="Company's Garden",
        category=InformationCategory.NATURE,
        description="Historic public park with walking paths and botanical flora.",
        location="Cape Town",
    )

    score_shop = evaluate_place(vintage_shop, criteria)
    score_park = evaluate_place(generic_park, criteria)

    assert score_shop.score > score_park.score
    req_reasons = [r for r in score_shop.reasons if r.type.value == "requirement"]
    assert len(req_reasons) > 0
    assert "shopping" in req_reasons[0].message


def test_case_g_bored_afternoon_reading_regression() -> None:
    """Case G: 'I’m bored. I have R300 and the afternoon free tomorrow to read somewhere cozy.'

    Regression test for the defect:
    1. 'quiet_focus' is extracted as primary experience requirement.
    2. 'bored' does not inject 'fun' into preferences or descriptors.
    3. Generic broad categories (FOOD, NATURE, CULTURE) are not injected.
    4. Selection forwards experience requirements into DecisionCriteria.
    5. Trade-off summary honestly discloses unverified primary experience rather than
       falsely claiming complete coverage or dismissing it as 'decor/ambiance'.
    """
    engine = DeterministicUnderstandingEngine()
    u = engine.parse("I’m bored. I have R300 and the afternoon free tomorrow to read somewhere cozy.")

    assert "quiet_focus" in u.experience_requirements
    assert "fun" not in u.preferences
    assert InformationCategory.FOOD not in u.activity_types
    assert InformationCategory.NATURE not in u.activity_types
    assert InformationCategory.CULTURE not in u.activity_types

    plan_id = uuid4()
    constraints = [
        Constraint(plan_id=plan_id, type=ConstraintType.BUDGET_MAX, value="R300", numeric_value=Decimal("300")),
    ]
    for slug in u.experience_requirements:
        constraints.append(
            Constraint(plan_id=plan_id, type=ConstraintType.REQUIREMENT, value=f"requirement:{slug}")
        )
    for pref in u.preferences:
        constraints.append(Constraint(plan_id=plan_id, type=ConstraintType.PREFERENCE, value=pref))

    plan = Plan(
        id=plan_id,
        user_id=uuid4(),
        intention="I’m bored. I have R300 and the afternoon free tomorrow to read somewhere cozy.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        constraints=constraints,
        context=PlanningContext(plan_id=plan_id, location="Cape Town", group_size=1),
    )

    criteria = criteria_from_plan(plan)
    assert "quiet_focus" in criteria.experience_requirements

    # When evaluated against baseline catalog without certified quiet study spaces
    result = decide(criteria, PLACES_CATALOG[:19], ACTIVITIES_CATALOG)

    # Because public registry listings do not independently verify reading/quiet study,
    # the trade-off summary is completely honest and specific:
    assert result.trade_off_summary is not None
    assert "quiet place to read or focus" in result.trade_off_summary
    assert "decor/ambiance" not in result.trade_off_summary


def test_case_h_unverified_primary_experience_honest_disclosure() -> None:
    """Case H: When primary experience cannot be verified.

    The planner must remain honest and report uncovered status rather than
    falsely claiming complete coverage.
    """
    requirements = requirements_from_slugs(("quiet_focus",))
    # Stops have no reading or quiet evidence
    stops = (
        (
            "Seaside Diner",
            CandidateEvidence(
                name="Seaside Diner",
                description="Bustling diner serving milkshakes and burgers with loud music.",
                category=InformationCategory.FOOD,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)
    assert coverage.is_fully_covered is False
    assert coverage.status == CoverageStatus.NOT_COVERED
    assert len(coverage.uncovered) == 1
    assert coverage.uncovered[0].requirement.slug == "quiet_focus"
    assert coverage.items[0].is_covered is False


def test_case_i_partial_coverage_preserves_partial_status() -> None:
    """Case I: When one provider/candidate partially satisfies requirements.

    The existing M17 partial-coverage behavior remains intact: satisfied items
    are marked covered with evidence, unsatisfied items remain uncovered.
    """
    requirements = requirements_from_slugs(("historic_streets", "craft_food_market"))
    stops = (
        (
            "District Six Museum",
            CandidateEvidence(
                name="District Six Museum",
                description="Historic museum recounting the forced removals in District Six.",
                category=InformationCategory.CULTURE,
            ),
        ),
        (
            "Generic Cafe",
            CandidateEvidence(
                name="Generic Cafe",
                description="Coffee and pastries in the city center.",
                category=InformationCategory.FOOD,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)
    assert coverage.is_fully_covered is False
    assert coverage.status == CoverageStatus.PARTIAL

    by_slug = {item.requirement.slug: item for item in coverage.items}
    assert by_slug["historic_streets"].is_covered is True
    assert by_slug["historic_streets"].matches[0].field == "description"
    assert "historic" in by_slug["historic_streets"].matches[0].term

    assert by_slug["craft_food_market"].is_covered is False
    assert any(u.requirement.slug == "craft_food_market" for u in coverage.uncovered)