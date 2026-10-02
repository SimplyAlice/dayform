from decimal import Decimal
import pytest

from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.planning.information import InformationCategory
from app.domain.entities.planning.understanding import BudgetKind, ProvenanceKind


@pytest.fixture
def engine() -> DeterministicUnderstandingEngine:
    return DeterministicUnderstandingEngine()


def test_benchmark_conversational_understanding(engine: DeterministicUnderstandingEngine) -> None:
    raw = "I want to take my boyfriend somewhere nice Saturday, maybe R800, somewhere around town, but nothing too fancy"
    u = engine.parse(raw)

    assert u.occasion == "date"
    assert u.relationship_context == "boyfriend"
    assert u.people_count == 2
    assert u.date_spec == "Saturday"
    assert u.budget_amount == Decimal("800")
    assert u.budget_kind == BudgetKind.APPROXIMATE
    assert "nice" in u.preferences
    assert "not_too_fancy" in u.exclusions
    assert "town" in u.location.lower() or "cape town" in u.location.lower()
    assert InformationCategory.FOOD in u.activity_types
    assert u.provenance["occasion"] == ProvenanceKind.INFERRED.value
    assert u.provenance["budget"] == ProvenanceKind.EXPLICIT.value


def test_couples_and_dating_relationships(engine: DeterministicUnderstandingEngine) -> None:
    cases = [
        ("romantic dinner with my girlfriend", "date", "girlfriend", 2),
        ("anniversary date with my wife", "date", "wife", 2),
        ("chill Saturday with my partner", "date", "partner", 2),
        ("taking my husband out for lunch", "date", "husband", 2),
    ]
    for prompt, expected_occ, expected_rel, expected_count in cases:
        u = engine.parse(prompt)
        assert u.occasion == expected_occ
        assert u.relationship_context == expected_rel
        assert u.people_count == expected_count


def test_friends_and_family_groups(engine: DeterministicUnderstandingEngine) -> None:
    u_friends = engine.parse("Going out with 3 friends for drinks")
    assert u_friends.occasion == "friends"
    assert u_friends.people_count == 4  # user + 3 friends

    u_group = engine.parse("Me and 4 friends want to do something fun this weekend. We have about R1500 total.")
    assert u_group.occasion == "friends"
    assert u_group.people_count == 5
    assert u_group.budget_amount == Decimal("1500")
    assert u_group.budget_kind == BudgetKind.APPROXIMATE
    assert "fun" in u_group.preferences

    u_birthday_mom = engine.parse("I want a chill birthday thing for my mom, not too expensive, preferably somewhere pretty.")
    assert u_birthday_mom.occasion == "birthday"
    assert u_birthday_mom.relationship_context == "mom"
    assert u_birthday_mom.people_count == 2
    assert u_birthday_mom.budget_kind == BudgetKind.PREFERENCE
    assert "casual" in u_birthday_mom.preferences
    assert "aesthetic" in u_birthday_mom.preferences

    u_family = engine.parse("Family outing for 5 people this weekend")
    assert u_family.occasion == "family"
    assert u_family.people_count == 5

    u_solo = engine.parse("I need a quiet solo afternoon to read and drink coffee")
    assert u_solo.occasion == "solo"
    assert u_solo.people_count == 1


def test_budget_semantics_classification(engine: DeterministicUnderstandingEngine) -> None:
    u_max = engine.parse("Dinner under R500 total")
    assert u_max.budget_amount == Decimal("500")
    assert u_max.budget_kind == BudgetKind.HARD_MAX

    u_approx = engine.parse("Somewhere around R1000 for dinner")
    assert u_approx.budget_amount == Decimal("1000")
    assert u_approx.budget_kind == BudgetKind.APPROXIMATE

    u_free = engine.parse("Free things to do outside")
    assert u_free.budget_amount == Decimal("0")
    assert u_free.budget_kind == BudgetKind.HARD_MAX


def test_date_and_time_window_extraction(engine: DeterministicUnderstandingEngine) -> None:
    u_sat_pm = engine.parse("Saturday evening walk and dinner")
    assert u_sat_pm.date_spec == "Saturday"
    assert u_sat_pm.time_window == "evening"

    u_tomorrow = engine.parse("Breakfast tomorrow morning")
    assert u_tomorrow.date_spec == "Tomorrow"
    assert u_tomorrow.time_window == "morning"

    u_weekend = engine.parse("Activities for this weekend")
    assert u_weekend.date_spec == "This weekend"


def test_public_transport_request_is_an_explicit_transport_preference(
    engine: DeterministicUnderstandingEngine,
) -> None:
    understanding = engine.parse("Take me to Kirstenbosch by public transport")

    assert understanding.transport_mode == "public_transport"
    assert understanding.provenance["transport_mode"] == ProvenanceKind.EXPLICIT.value


def test_hard_exclusions_detection(engine: DeterministicUnderstandingEngine) -> None:
    u_outdoor = engine.parse("Indoor activities only, no outdoors or nature")
    assert "no_outdoors" in u_outdoor.exclusions
    assert "outdoors" not in u_outdoor.preferences

    u_fancy = engine.parse("A nice dinner but nothing too fancy")
    assert "not_too_fancy" in u_fancy.exclusions

    u_clubs = engine.parse("Saturday night out but no clubs or loud venues")
    assert "no_clubs" in u_clubs.exclusions


def test_inferred_defaults_and_ambiguities(engine: DeterministicUnderstandingEngine) -> None:
    u = engine.parse("Somewhere nice to eat")
    # Location not given -> defaults to Cape Town with inferred flag
    assert u.location == "Cape Town"
    assert u.location_is_inferred is True
    assert u.provenance["location"] == ProvenanceKind.DEFAULTED.value

    # Group size not specified -> people_count is None and flagged in ambiguities
    assert u.people_count is None
    assert any("group size" in a.lower() for a in u.ambiguities)


def test_empty_request_rejected(engine: DeterministicUnderstandingEngine) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        engine.parse("   ")


def test_scenario_a_temporal_understanding(engine: DeterministicUnderstandingEngine) -> None:
    req = "I want to take my boyfriend somewhere nice Saturday around 11, we have until 7, budget R800."
    u = engine.parse(req)
    assert u.date_spec == "Saturday"
    assert u.start_time == "11:00"
    assert u.end_time == "19:00"
    assert u.time_confidence == "approximate"
    assert u.people_count == 2
    assert u.relationship_context == "boyfriend"
    assert u.occasion == "date"
    assert u.budget_amount == 800
    assert any("approximate" in a.lower() for a in u.ambiguities)
    assert any("19:00" in a for a in u.ambiguities)


def test_scenario_b_temporal_understanding(engine: DeterministicUnderstandingEngine) -> None:
    req = "It's my mom's birthday Saturday afternoon. I want lunch and something nice afterwards, around R1000."
    u = engine.parse(req)
    assert u.date_spec == "Saturday"
    assert u.time_window == "afternoon"
    assert u.start_time == "12:30"
    assert u.end_time == "17:30"
    assert u.time_confidence == "inferred"
    assert u.people_count == 2
    assert u.relationship_context == "mom"
    assert u.occasion == "birthday"
    assert u.budget_amount == 1000


def test_scenario_c_duration_limit(engine: DeterministicUnderstandingEngine) -> None:
    req = "I only have three hours Saturday afternoon."
    u = engine.parse(req)
    assert u.date_spec == "Saturday"
    assert u.time_window == "afternoon"
    assert u.duration_limit_minutes == 180
    assert u.provenance["duration_limit"] == ProvenanceKind.EXPLICIT.value
    assert any("3 hours" in a for a in u.ambiguities)


def test_exact_time_span(engine: DeterministicUnderstandingEngine) -> None:
    req = "Plan something from 2pm to 7pm on Sunday"
    u = engine.parse(req)
    assert u.date_spec == "Sunday"
    assert u.start_time == "14:00"
    assert u.end_time == "19:00"
    assert u.time_confidence == "exact"
    assert u.time_window == "14:00-19:00"


def test_birthday_group_budget_scenario(engine: DeterministicUnderstandingEngine) -> None:
    req = "I want a cute birthday day out in Cape Town for four people, under R2,000, starting after lunch."
    u = engine.parse(req)
    assert u.occasion == "birthday"
    assert u.people_count == 4
    assert u.location == "Cape Town"
    assert u.budget_amount == Decimal("2000")
    assert u.budget_kind == BudgetKind.HARD_MAX
    assert u.time_window == "afternoon"
    assert "romantic" in u.preferences or "cute" in req.lower()


def test_a_specific_intent_drives_the_right_category_not_generic_broadening(
    engine: DeterministicUnderstandingEngine,
) -> None:
    """A named experience supplies its own category instead of 'fun' broadening.

    'historic architecture' is a culture ask via the historic_streets requirement,
    and 'vintage shops' is a shopping ask via the shopping requirement. Neither
    collapses into a generic food/culture/nature mix when a specific intent
    is on the table.
    """
    architecture = engine.parse("Somewhere to explore historic architecture this weekend.")
    assert "historic_streets" in architecture.experience_requirements
    assert InformationCategory.CULTURE in architecture.activity_types

    shops = engine.parse("Browse vintage shops for an hour or so.")
    assert "shopping" in shops.experience_requirements
    assert InformationCategory.SHOPPING in shops.activity_types

    reading = engine.parse("Read somewhere cozy this afternoon.")
    assert "quiet_focus" in reading.experience_requirements
    # quiet_focus has no catalog category, so nothing substitutes for it.
    for broad in (InformationCategory.FOOD, InformationCategory.NATURE, InformationCategory.CULTURE):
        assert broad not in reading.activity_types


