from decimal import Decimal

import pytest

from app.domain.entities.planning.decision import (
    CandidateType,
    DecisionCandidate,
    DecisionCriteria,
    DecisionReason,
    ReasonOutcome,
    ReasonType,
)
from app.domain.entities.planning.decision_engine import (
    BUDGET_FIT_SCORE,
    CATEGORY_MATCH_SCORE,
    GROUP_FIT_SCORE,
    LOCATION_MATCH_SCORE,
    PLACE_DURATION_NEUTRAL_SCORE,
    decide,
    evaluate_activity,
    evaluate_place,
)
from app.domain.entities.planning.information import Activity, InformationCategory, Place

FULL_CRITERIA = DecisionCriteria(
    location="Cape Town",
    category=InformationCategory.FOOD,
    maximum_cost=Decimal("500"),
    group_size=4,
    maximum_duration_minutes=120,
)


def _place(**overrides) -> Place:
    data: dict = {
        "name": "Venue",
        "location": "Cape Town",
        "category": InformationCategory.FOOD,
        "description": "A venue.",
        "price_from": Decimal("100"),
        "maximum_group_size": 10,
    }
    data.update(overrides)
    return Place(**data)


def _activity(**overrides) -> Activity:
    data: dict = {
        "name": "Tasting",
        "category": InformationCategory.FOOD,
        "description": "An activity.",
        "cost": Decimal("180"),
        "duration_minutes": 90,
        "location": "Cape Town",
        "minimum_group_size": 1,
        "maximum_group_size": 6,
    }
    data.update(overrides)
    return Activity(**data)


def test_place_matcher_scores_full_fit_and_explains() -> None:
    candidate = evaluate_place(_place(), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert candidate.option_type is CandidateType.PLACE
    assert candidate.score == (
        CATEGORY_MATCH_SCORE + BUDGET_FIT_SCORE + GROUP_FIT_SCORE + LOCATION_MATCH_SCORE
        + PLACE_DURATION_NEUTRAL_SCORE
    )
    outcomes = {reason.type: reason.outcome for reason in candidate.reasons}
    assert outcomes[ReasonType.BUDGET] is ReasonOutcome.SUPPORTED
    assert outcomes[ReasonType.GROUP_SIZE] is ReasonOutcome.SUPPORTED
    assert outcomes[ReasonType.LOCATION] is ReasonOutcome.SUPPORTED
    assert outcomes[ReasonType.CATEGORY] is ReasonOutcome.SUPPORTED


def test_activity_matcher_scores_full_fit_and_explains_duration() -> None:
    candidate = evaluate_activity(_activity(), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert candidate.option_type is CandidateType.ACTIVITY
    assert candidate.duration_minutes == 90
    assert candidate.score == 100
    outcomes = {reason.type: reason.outcome for reason in candidate.reasons}
    assert outcomes[ReasonType.DURATION] is ReasonOutcome.SUPPORTED


def test_activity_exceeding_budget_is_ineligible_with_violation_reason() -> None:
    candidate = evaluate_activity(_activity(cost=Decimal("600")), FULL_CRITERIA)

    assert candidate.is_eligible is False
    budget = next(reason for reason in candidate.reasons if reason.type is ReasonType.BUDGET)
    assert budget.outcome is ReasonOutcome.VIOLATED
    assert "exceeds" in budget.message


def test_exact_budget_boundary_is_eligible_and_scored() -> None:
    candidate = evaluate_activity(_activity(cost=Decimal("500")), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert next(r for r in candidate.reasons if r.type is ReasonType.BUDGET).outcome is ReasonOutcome.SUPPORTED


def test_group_too_large_is_ineligible() -> None:
    candidate = evaluate_place(_place(maximum_group_size=3), FULL_CRITERIA)

    assert candidate.is_eligible is False
    assert next(r for r in candidate.reasons if r.type is ReasonType.GROUP_SIZE).outcome is ReasonOutcome.VIOLATED


def test_group_exact_maximum_boundary_is_eligible() -> None:
    candidate = evaluate_place(_place(maximum_group_size=4), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert next(r for r in candidate.reasons if r.type is ReasonType.GROUP_SIZE).outcome is ReasonOutcome.SUPPORTED


def test_option_without_maximum_group_size_is_eligible_for_large_groups() -> None:
    candidate = evaluate_place(_place(maximum_group_size=None), FULL_CRITERIA)

    assert candidate.is_eligible is True
    group = next(r for r in candidate.reasons if r.type is ReasonType.GROUP_SIZE)
    assert group.outcome is ReasonOutcome.SUPPORTED
    assert "no listed maximum" in group.message


def test_duration_exactly_at_maximum_is_eligible() -> None:
    candidate = evaluate_activity(_activity(duration_minutes=120), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert next(r for r in candidate.reasons if r.type is ReasonType.DURATION).outcome is ReasonOutcome.SUPPORTED


def test_duration_over_maximum_is_ineligible() -> None:
    candidate = evaluate_activity(_activity(duration_minutes=121), FULL_CRITERIA)

    assert candidate.is_eligible is False
    assert next(r for r in candidate.reasons if r.type is ReasonType.DURATION).outcome is ReasonOutcome.VIOLATED


def test_unknown_place_price_is_neutral_and_not_disqualifying() -> None:
    candidate = evaluate_place(_place(price_from=None), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert next(r for r in candidate.reasons if r.type is ReasonType.BUDGET).outcome is ReasonOutcome.NEUTRAL


def test_category_mismatch_is_neutral_not_disqualifying() -> None:
    candidate = evaluate_activity(_activity(category=InformationCategory.NATURE, name="Gardens"), FULL_CRITERIA)

    assert candidate.is_eligible is True
    assert next(r for r in candidate.reasons if r.type is ReasonType.CATEGORY).outcome is ReasonOutcome.NEUTRAL


def test_decide_is_deterministic_and_orders_eligible_first_by_score() -> None:
    places = [_place(name="Cheap food", price_from=Decimal("50")), _place(name="Pricey food", price_from=Decimal("500"))]
    activities = [_activity(name="Nature walk", category=InformationCategory.NATURE, cost=Decimal("0"), duration_minutes=60)]

    first = decide(FULL_CRITERIA, places, activities)
    second = decide(FULL_CRITERIA, places, activities)

    assert [c.name for c in first.candidates] == [c.name for c in second.candidates]
    scores = [c.score for c in first.candidates]
    assert scores == sorted(scores, reverse=True)
    # Category-matching food options outrank the neutral nature activity.
    assert first.eligible[0].name in {"Cheap food", "Pricey food"}
    assert first.candidates[-1].name == "Nature walk"


def test_decide_applies_stable_tiebreak_for_equal_scores() -> None:
    # Two identical-score food activities; ties resolve by (type, name).
    activities = [_activity(name="Beta"), _activity(name="Alpha")]

    result = decide(FULL_CRITERIA, [], activities)

    assert [c.name for c in result.candidates] == ["Alpha", "Beta"]


def test_decide_returns_empty_result_when_no_options() -> None:
    result = decide(FULL_CRITERIA, [], [])

    assert result.candidates == ()
    assert result.source == "unknown"


def test_no_criteria_still_produces_a_neutral_explanation() -> None:
    candidate = evaluate_place(_place(), DecisionCriteria())

    assert candidate.is_eligible is True
    assert candidate.score == 0
    assert candidate.reasons[0].type is ReasonType.GENERAL
    assert candidate.reasons[0].outcome is ReasonOutcome.NEUTRAL


def test_candidate_rejects_empty_reasons() -> None:
    with pytest.raises(ValueError, match="at least one reason"):
        DecisionCandidate(option_id=_place().id, option_type=CandidateType.PLACE, name="X",
                          is_eligible=True, score=0, reasons=(), category=InformationCategory.FOOD)


def test_reason_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message"):
        DecisionReason(ReasonType.BUDGET, ReasonOutcome.SUPPORTED, "   ")


def test_decision_criteria_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Maximum cost"):
        DecisionCriteria(maximum_cost=Decimal("-1"))
    with pytest.raises(ValueError, match="Group size"):
        DecisionCriteria(group_size=0)
    with pytest.raises(ValueError, match="Maximum duration"):
        DecisionCriteria(maximum_duration_minutes=0)


def test_decision_criteria_filters_hard_exclusions_no_outdoors() -> None:
    criteria = DecisionCriteria(
        location="Cape Town",
        exclusions=("no_outdoors",),
    )
    nature_place = _place(category=InformationCategory.NATURE, name="Botanical Gardens")
    candidate = evaluate_place(nature_place, criteria)

    assert candidate.is_eligible is False
    violation = next(r for r in candidate.reasons if r.outcome is ReasonOutcome.VIOLATED)
    assert "outdoor activity violates constraint" in violation.message


def test_decision_criteria_filters_hard_exclusions_not_too_fancy() -> None:
    criteria = DecisionCriteria(
        location="Cape Town",
        exclusions=("not_too_fancy",),
    )
    upscale_place = _place(
        category=InformationCategory.FOOD,
        name="The Test Kitchen",
        description="Upscale fine dining tasting experience.",
        price_from=Decimal("550"),
    )
    candidate = evaluate_place(upscale_place, criteria)

    assert candidate.is_eligible is False
    violation = next(r for r in candidate.reasons if r.outcome is ReasonOutcome.VIOLATED)
    assert "upscale / formal venue violates constraint" in violation.message


def test_decision_criteria_applies_preference_fit_boost() -> None:
    criteria_normal = DecisionCriteria(location="Cape Town")
    criteria_chill = DecisionCriteria(location="Cape Town", preferences=("chill",))

    place = _place(description="A relaxed, casual venue with good coffee.")
    candidate_normal = evaluate_place(place, criteria_normal)
    candidate_chill = evaluate_place(place, criteria_chill)

    assert candidate_chill.score > candidate_normal.score
    pref_reasons = [r for r in candidate_chill.reasons if r.type is ReasonType.PREFERENCE]
    assert len(pref_reasons) > 0
    assert pref_reasons[0].outcome is ReasonOutcome.SUPPORTED


def test_decision_criteria_applies_occasion_fit_boost() -> None:
    criteria_normal = DecisionCriteria(location="Cape Town")
    criteria_date = DecisionCriteria(location="Cape Town", occasion="date")

    place = _place(description="A romantic waterfront spot with sunset views.")
    candidate_normal = evaluate_place(place, criteria_normal)
    candidate_date = evaluate_place(place, criteria_date)

    assert candidate_date.score > candidate_normal.score
    occasion_reasons = [r for r in candidate_date.reasons if r.type is ReasonType.OCCASION]
    assert len(occasion_reasons) > 0
    assert occasion_reasons[0].outcome is ReasonOutcome.SUPPORTED


def test_evaluate_place_neighborhood_matching() -> None:
    place = _place(
        name="Waterfront Bistro",
        location="Cape Town",
        address="10 Dock Rd, V&A Waterfront, Cape Town",
    )
    criteria = DecisionCriteria(location="Waterfront")
    candidate = evaluate_place(place, criteria)

    assert candidate.is_eligible is True
    loc_reason = next(r for r in candidate.reasons if r.type is ReasonType.LOCATION)
    assert loc_reason.outcome is ReasonOutcome.SUPPORTED
    assert "Waterfront" in loc_reason.message
    assert candidate.address == "10 Dock Rd, V&A Waterfront, Cape Town"


def test_evaluate_place_unlisted_price_is_eligible_with_neutral_reason() -> None:
    place = _place(name="Art Gallery", price_from=None)
    criteria = DecisionCriteria(maximum_cost=Decimal("200"))
    candidate = evaluate_place(place, criteria)

    assert candidate.is_eligible is True
    assert candidate.cost is None
    budget_reason = next(r for r in candidate.reasons if r.type is ReasonType.BUDGET)
    assert budget_reason.outcome is ReasonOutcome.NEUTRAL
    assert "Cost is unknown" in budget_reason.message


def test_decide_populates_real_source_and_attribution() -> None:
    place = _place(
        name="Kirstenbosch Garden",
        source="openstreetmap",
        address="Rhodes Dr, Newlands, Cape Town",
        opening_hours="Daily 08:00-18:00",
        freshness="recently_verified",
        verified_at="2026-09",
    )
    criteria = DecisionCriteria(location="Cape Town")
    result = decide(criteria, [place], [])

    assert result.source == "openstreetmap"
    assert result.attribution == "© OpenStreetMap contributors"
    assert result.freshness == "recently_verified"
    assert result.is_live is False
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.address == "Rhodes Dr, Newlands, Cape Town"
    assert c.opening_hours == "Daily 08:00-18:00"
    assert c.freshness == "recently_verified"


def test_evaluate_place_opening_hours_supported() -> None:
    place = _place(name="Kirstenbosch", opening_hours="Daily 08:00-18:00")
    criteria = DecisionCriteria(day_of_week="Saturday", start_time="11:00")
    candidate = evaluate_place(place, criteria)

    assert candidate.is_eligible is True
    oh_reason = next(r for r in candidate.reasons if r.type is ReasonType.OPENING_HOURS)
    assert oh_reason.outcome is ReasonOutcome.SUPPORTED
    assert "Open on Saturday around 11:00" in oh_reason.message
    assert candidate.score >= 20  # TEMPORAL_FIT_SCORE included


def test_evaluate_place_closed_during_time_violates() -> None:
    place = _place(name="Night Club", opening_hours="Mon-Sat 09:00-16:00")
    criteria = DecisionCriteria(day_of_week="Saturday", start_time="19:00")
    candidate = evaluate_place(place, criteria)

    assert candidate.is_eligible is False
    oh_reason = next(r for r in candidate.reasons if r.type is ReasonType.OPENING_HOURS)
    assert oh_reason.outcome is ReasonOutcome.VIOLATED
    assert "Closed on Saturday around 19:00" in oh_reason.message


def test_evaluate_place_unknown_opening_hours_neutral() -> None:
    place = _place(name="Secret Spot", opening_hours=None)
    criteria = DecisionCriteria(day_of_week="Saturday", start_time="14:00")
    candidate = evaluate_place(place, criteria)

    assert candidate.is_eligible is True
    oh_reason = next(r for r in candidate.reasons if r.type is ReasonType.OPENING_HOURS)
    assert oh_reason.outcome is ReasonOutcome.NEUTRAL
    assert "Opening hours could not be verified" in oh_reason.message


def test_evaluate_activity_duration_limit_exceeded_violates() -> None:
    act = _activity(name="Full Day Hike", duration_minutes=360)
    criteria = DecisionCriteria(duration_limit_minutes=180)
    candidate = evaluate_activity(act, criteria)

    assert candidate.is_eligible is False
    dur_reason = next(r for r in candidate.reasons if r.type is ReasonType.DURATION)
    assert dur_reason.outcome is ReasonOutcome.VIOLATED
    assert "exceeds the 180-minute time limit" in dur_reason.message


def test_evaluate_activity_duration_limit_fits() -> None:
    act = _activity(name="Quick Museum Tour", duration_minutes=90)
    criteria = DecisionCriteria(duration_limit_minutes=180)
    candidate = evaluate_activity(act, criteria)

    assert candidate.is_eligible is True
    dur_reason = next(r for r in candidate.reasons if r.type is ReasonType.DURATION)
    assert dur_reason.outcome is ReasonOutcome.SUPPORTED
    assert "fits the 180-minute time limit" in dur_reason.message


def test_evaluate_place_generic_category_does_not_satisfy_specific_experience_requirement() -> None:
    # A generic modern gallery has category CULTURE, but does NOT evidence historic streets
    generic_gallery = _place(
        name="Modern Avant-Garde Space",
        category=InformationCategory.CULTURE,
        description="Contemporary digital media and experimental abstract exhibits.",
    )
    criteria = DecisionCriteria(experience_requirements=("historic_streets",))
    candidate = evaluate_place(generic_gallery, criteria)

    req_reasons = [r for r in candidate.reasons if r.type is ReasonType.REQUIREMENT]
    assert len(req_reasons) == 0  # Generic category must not claim historic streets experience


def test_evaluate_place_evidence_matches_specific_experience_requirement() -> None:
    # A historic venue with evidence terms matches the experience requirement
    historic_fort = _place(
        name="Castle of Good Hope",
        category=InformationCategory.CULTURE,
        description="Historic 17th-century fortress featuring colonial architecture and heritage collections.",
    )
    criteria = DecisionCriteria(experience_requirements=("historic_streets",))
    candidate = evaluate_place(historic_fort, criteria)

    req_reasons = [r for r in candidate.reasons if r.type is ReasonType.REQUIREMENT]
    assert len(req_reasons) == 1
    assert "historic streets" in req_reasons[0].message

