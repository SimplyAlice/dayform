from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveAvailability,
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)
from app.domain.entities.mobility.live import MobilityLiveStatusReport
from app.domain.entities.mobility.models import MobilityEvidence, MobilityOption


@dataclass
class PlanTransition:
    """Represents physical travel connecting two consecutive itinerary stops."""

    from_location: str
    to_location: str
    from_item_id: UUID | None = None
    to_item_id: UUID | None = None
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    duration_minutes: int | None = None
    mode: TransportMode = TransportMode.WALK
    provider_id: str = "walking"
    provider_name: str = "Walking"
    cost: Decimal | None = None
    cost_known: bool = False
    currency: str = "ZAR"
    transfers: int = 0
    confidence: float = 0.5
    live_status: MobilityLiveStatus = MobilityLiveStatus.UNKNOWN
    booking_capability: BookingCapability = BookingCapability.NO_BOOKING
    booking_url: str | None = None
    summary: str = ""
    evidence: tuple[MobilityEvidence, ...] = field(default_factory=tuple)
    available_options: tuple[MobilityOption, ...] = field(default_factory=tuple)
    is_feasible: bool = True
    feasibility_issue: str | None = None
    # M16 live mobility. Defaults describe a plan with no live information at all,
    # which is the honest starting point for every provider without a public feed.
    live_availability: MobilityLiveAvailability = MobilityLiveAvailability.UNAVAILABLE
    live_explanation: str | None = None
    live_source: str | None = None
    live_source_type: MobilitySourceType = MobilitySourceType.UNKNOWN
    live_observed_at: datetime | None = None
    live_confidence: float = 0.0
    live_delay_minutes: int | None = None
    id: str = field(default_factory=lambda: f"trans-{uuid4().hex[:8]}")

    def __post_init__(self) -> None:
        if not self.from_location.strip():
            raise ValueError("Transition from_location cannot be empty.")
        if not self.to_location.strip():
            raise ValueError("Transition to_location cannot be empty.")
        if self.cost is not None and self.cost < 0:
            raise ValueError("Transition cost cannot be negative.")
        self.cost_known = self.cost is not None

    def apply_live_status(self, report: MobilityLiveStatusReport) -> None:
        """Fold live service state into this transition.

        Live evidence never changes `duration_minutes`: an unevidenced delay must
        not be invented into the schedule. It only raises the status the user sees
        and, when a service is genuinely unusable, marks the leg infeasible.
        """
        self.live_availability = report.availability
        self.live_explanation = report.explanation or None
        self.live_source = report.source or None
        self.live_source_type = report.source_type
        self.live_observed_at = report.observed_at
        self.live_confidence = report.confidence
        self.live_delay_minutes = report.delay_minutes
        self.live_status = report.effective_status()

        if report.is_blocking:
            self.is_feasible = False
            reason = (
                f"{self.provider_name} is currently reported as "
                f"{self.live_status.value.replace('_', ' ')}."
            )
            existing = self.feasibility_issue
            self.feasibility_issue = f"{existing} {reason}".strip() if existing else reason


@dataclass
class ItineraryFeasibility:
    """Aggregate feasibility assessment for an itinerary incorporating mobility transitions."""

    is_feasible: bool = True
    deadline_respected: bool = True
    budget_respected: bool = True
    transitions_feasible: bool = True
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_transition_duration_minutes: int = 0
    total_known_transition_cost: Decimal = Decimal("0")
    has_unknown_transition_costs: bool = False
