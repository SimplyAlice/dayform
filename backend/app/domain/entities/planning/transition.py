from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveStatus,
    TransportMode,
)
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
    id: str = field(default_factory=lambda: f"trans-{uuid4().hex[:8]}")

    def __post_init__(self) -> None:
        if not self.from_location.strip():
            raise ValueError("Transition from_location cannot be empty.")
        if not self.to_location.strip():
            raise ValueError("Transition to_location cannot be empty.")
        if self.cost is not None and self.cost < 0:
            raise ValueError("Transition cost cannot be negative.")
        self.cost_known = self.cost is not None


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
