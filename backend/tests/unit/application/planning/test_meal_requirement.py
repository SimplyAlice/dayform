"""The meal requirement, and what it exists to prevent.

"Lunch for two in Southern Suburbs for R400" produced a plan of two gardens and
no lunch, presented as if the user had got what they asked for. The taxonomy had
no entry for wanting to eat, so "lunch" was invisible to coverage and the plan
looked complete.
"""
from __future__ import annotations

import pytest

from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.planning.information import InformationCategory
from app.domain.entities.planning.requirements import (
    CandidateEvidence,
    evaluate_coverage,
    requirements_from_slugs,
)


def _parse(text: str):
    return DeterministicUnderstandingEngine().parse(text)


def test_lunch_is_recorded_as_something_the_user_asked_for() -> None:
    understanding = _parse(
        "Lunch for two in Southern Suburbs for R400 includes outdoor activity, garden"
    )

    assert "meal" in understanding.experience_requirements
    assert "outdoor" in understanding.experience_requirements
    assert understanding.people_count == 2
    assert understanding.location == "Southern Suburbs"


@pytest.mark.parametrize(
    "text",
    [
        "Dinner somewhere romantic and then something fun",
        "a relaxed Saturday with my friends, somewhere good to eat",
        "I want breakfast tomorrow",
        "Coffee and something to eat",
    ],
)
def test_ordinary_meal_requests_are_recorded(text: str) -> None:
    assert "meal" in _parse(text).experience_requirements


def test_a_market_is_not_reported_as_a_lunch_request() -> None:
    """Browsing a food market is a market ask, not a meal.

    Without this, "craft food markets" would be counted as wanting to eat and a
    market-only day would be reported as missing lunch.
    """
    understanding = _parse(
        "An afternoon exploring local culture, historic streets, and craft food markets."
    )

    assert "meal" not in understanding.experience_requirements
    assert "craft_food_market" in understanding.experience_requirements


def test_a_plant_and_bread_day_still_reads_as_a_meal() -> None:
    """A market alongside an explicit meal is still a meal."""
    understanding = _parse("Breakfast at a food market on Saturday")

    assert "meal" in understanding.experience_requirements


def test_a_garden_only_plan_cannot_claim_the_lunch_was_covered() -> None:
    """The regression itself: two gardens, no meal, and the user did ask for lunch."""
    requirements = requirements_from_slugs(["meal", "outdoor"])
    stops = (
        (
            "kirstenbosch-garden",
            CandidateEvidence(
                name="Kirstenbosch National Botanical Garden",
                description="A garden of trees and seasonal flowers on the eastern slopes.",
                category=InformationCategory.NATURE,
            ),
        ),
        (
            "boomslang",
            CandidateEvidence(
                name="Kirstenbosch Boomslang Canopy Walk",
                description="An elevated walkway through tree crowns with mountain views.",
                category=InformationCategory.NATURE,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)

    by_slug = {item.requirement.slug: item for item in coverage.items}
    assert by_slug["outdoor"].is_covered is True
    assert by_slug["meal"].is_covered is False
    # And the plan as a whole is therefore not fully covered.
    assert coverage.is_fully_covered is False
    assert [i.requirement.slug for i in coverage.uncovered] == ["meal"]


def test_a_plan_with_a_real_restaurant_does_cover_the_meal() -> None:
    requirements = requirements_from_slugs(["meal"])
    stops = (
        (
            "kloof",
            CandidateEvidence(
                name="Kloof Street House",
                description=(
                    "Eclectic, atmospheric restaurant set in a Victorian house with a "
                    "candlelit courtyard garden and relaxed bistro fare."
                ),
                category=InformationCategory.FOOD,
            ),
        ),
    )

    coverage = evaluate_coverage(requirements, stops)

    assert coverage.items[0].is_covered is True
    assert coverage.is_fully_covered is True
