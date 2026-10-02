from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.domain.entities.planning.constraints import BudgetConstraint, BudgetStyle, TemporalConstraint
from app.domain.entities.planning.information import InformationCategory


class BudgetKind(str, Enum):
    HARD_MAX = "hard_max"
    APPROXIMATE = "approximate"
    PREFERENCE = "preference"
    NONE = "none"


class ProvenanceKind(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    DEFAULTED = "defaulted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlanningUnderstanding:
    """A provider-agnostic domain value object capturing the structured understanding of a natural language planning request."""

    raw_request: str
    goal: str
    occasion: str | None = None
    people_count: int | None = None
    relationship_context: str | None = None
    date_spec: str | None = None
    time_window: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    deadline: str | None = None
    time_confidence: str = "unknown"
    duration_limit_minutes: int | None = None
    location: str | None = None
    location_is_inferred: bool = False
    origin: str | None = None
    transport_mode: str | None = None
    budget_amount: Decimal | None = None
    budget_kind: BudgetKind = BudgetKind.NONE
    budget_model: BudgetConstraint | None = None
    temporal_model: TemporalConstraint | None = None
    preferences: tuple[str, ...] = field(default_factory=tuple)
    exclusions: tuple[str, ...] = field(default_factory=tuple)
    activity_types: tuple[InformationCategory, ...] = field(default_factory=tuple)
    semantic_descriptors: tuple[str, ...] = field(default_factory=tuple)
    # The distinct things the user asked for, kept separate from broad
    # categories so the final plan can show what it actually covered.
    experience_requirements: tuple[str, ...] = field(default_factory=tuple)
    setting_preference: str | None = None
    weather_context: str | None = None
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    provenance: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.raw_request.strip():
            raise ValueError("Raw planning request cannot be empty.")
        if not self.goal.strip():
            raise ValueError("Planning goal cannot be empty.")
        if self.people_count is not None and self.people_count < 1:
            raise ValueError("People count must be at least 1.")
        if self.budget_amount is not None and self.budget_amount < Decimal("0"):
            raise ValueError("Budget amount cannot be negative.")
        if self.duration_limit_minutes is not None and self.duration_limit_minutes <= 0:
            raise ValueError("Duration limit minutes must be positive.")
