from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping
from uuid import UUID

from app.domain.entities.planning.information import InformationCategory


class CandidateType(str, Enum):
    PLACE = "place"
    ACTIVITY = "activity"


class ReasonType(str, Enum):
    LOCATION = "location"
    BUDGET = "budget"
    GROUP_SIZE = "group_size"
    CATEGORY = "category"
    DURATION = "duration"
    GENERAL = "general"
    PREFERENCE = "preference"
    OCCASION = "occasion"
    TIME_WINDOW = "time_window"
    OPENING_HOURS = "opening_hours"
    SCHEDULE_CONFLICT = "schedule_conflict"
    SEMANTIC_MATCH = "semantic_match"
    EXCLUSION = "exclusion"
    SETTING = "setting"
    WEATHER = "weather"
    TRADE_OFF = "trade_off"
    MOBILITY = "mobility"
    REQUIREMENT = "requirement"


class ReasonOutcome(str, Enum):
    SUPPORTED = "supported"
    NEUTRAL = "neutral"
    VIOLATED = "violated"


@dataclass(frozen=True)
class DecisionReason:
    """A single structured explanation for a candidate's evaluation."""

    type: ReasonType
    outcome: ReasonOutcome
    message: str
    evidence_status: str = "verified"

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("Decision reason message cannot be empty.")


@dataclass(frozen=True)
class DecisionCandidate:
    """A scored, explainable candidate produced by the decision engine."""

    option_id: UUID
    option_type: CandidateType
    name: str
    is_eligible: bool
    score: int
    reasons: tuple[DecisionReason, ...]
    category: InformationCategory
    cost: Decimal | None = None
    duration_minutes: int | None = None
    location: str | None = None
    source: str = "development_fixture"
    address: str | None = None
    opening_hours: str | None = None
    freshness: str = "fixture"
    verified_at: str | None = None
    attribution: str | None = None
    source_url: str | None = None
    phone: str | None = None
    reservation_url: str | None = None
    # Provider-supplied evidence. Retained so intent coverage can be checked
    # against what the venue actually says about itself, not just its category.
    description: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    # Carried so a requested area can be checked against where the venue
    # physically is, rather than against the city every catalog venue shares.
    latitude: float | None = None
    longitude: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Decision candidate name cannot be empty.")
        if self.score < 0:
            raise ValueError("Decision candidate score cannot be negative.")
        if not self.reasons:
            raise ValueError("Decision candidate must carry at least one reason.")


@dataclass(frozen=True)
class DecisionResult:
    """The ordered outcome of evaluating available options for a request."""

    candidates: tuple[DecisionCandidate, ...]
    source: str
    is_live: bool = False
    attribution: str | None = None
    freshness: str = "fixture"
    trade_off_summary: str | None = None

    @property
    def eligible(self) -> tuple[DecisionCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.is_eligible)


@dataclass(frozen=True)
class DecisionCriteria:
    """The provider-neutral request the decision engine evaluates against.

    Mirrors the fields callers already supply to option search so the same
    concepts are reused rather than duplicated. Passive value object: the
    engine interprets each field, not the criteria itself.
    """

    location: str | None = None
    category: InformationCategory | None = None
    maximum_cost: Decimal | None = None
    group_size: int | None = None
    maximum_duration_minutes: int | None = None
    occasion: str | None = None
    preferences: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    activity_types: tuple[InformationCategory, ...] = ()
    experience_requirements: tuple[str, ...] = ()
    semantic_descriptors: tuple[str, ...] = ()
    setting_preference: str | None = None
    weather_context: str | None = None

    day_of_week: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    deadline: str | None = None
    time_window: str | None = None
    duration_limit_minutes: int | None = None
    stretch_amount: Decimal | None = None
    priority_note: str | None = None

    def __post_init__(self) -> None:
        if self.maximum_cost is not None and self.maximum_cost < 0:
            raise ValueError("Maximum cost cannot be negative.")
        if self.group_size is not None and self.group_size < 1:
            raise ValueError("Group size must be at least 1.")
        if self.maximum_duration_minutes is not None and self.maximum_duration_minutes <= 0:
            raise ValueError("Maximum duration must be positive.")
        if self.duration_limit_minutes is not None and self.duration_limit_minutes <= 0:
            raise ValueError("Duration limit must be positive.")
