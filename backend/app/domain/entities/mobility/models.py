from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)


@dataclass(frozen=True)
class MobilityEvidence:
    """Provenance and observable proof for any transport fact or claim."""

    claim: str
    source: str
    source_type: MobilitySourceType
    observed_at: datetime
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    confidence: float = 0.8
    relevant_provider: str = ""
    relevant_route_or_stop: str | None = None

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("Mobility evidence claim cannot be empty.")
        if not self.source.strip():
            raise ValueError("Mobility evidence source cannot be empty.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}.")

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        return now > expiry


@dataclass
class MobilityRequirement:
    """Represents a request to travel between two points within a Dayform plan."""

    origin: str
    destination: str
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    date: date | None = None
    party_size: int = 1
    preferred_modes: list[TransportMode] = field(default_factory=list)
    excluded_modes: list[TransportMode] = field(default_factory=list)
    max_walking_minutes: int | None = None
    origin_coordinates: tuple[float, float] | None = None
    destination_coordinates: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if not self.origin.strip():
            raise ValueError("Mobility requirement origin cannot be empty.")
        if not self.destination.strip():
            raise ValueError("Mobility requirement destination cannot be empty.")
        if self.party_size < 1:
            raise ValueError("Party size must be at least 1.")
        if (
            self.departure_time is not None
            and self.arrival_time is not None
            and self.arrival_time < self.departure_time
        ):
            raise ValueError("Arrival time cannot be before departure time.")


@dataclass
class MobilityOption:
    """One concrete transport option or leg satisfying a mobility requirement."""

    id: str
    provider_id: str
    provider_name: str
    mode: TransportMode
    origin: str
    destination: str
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    duration_minutes: int | None = None
    cost: Decimal | None = None
    cost_is_unknown: bool = False
    cost_is_estimated: bool = False
    currency: str = "ZAR"
    walking_duration_minutes: int | None = None
    transfers: int = 0
    availability: str = "available"
    live_status: MobilityLiveStatus = MobilityLiveStatus.UNKNOWN
    booking_capability: BookingCapability = BookingCapability.NO_BOOKING
    booking_url: str | None = None
    source: str = ""
    source_type: MobilitySourceType = MobilitySourceType.UNKNOWN
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: float = 0.5
    evidence: list[MobilityEvidence] = field(default_factory=list)
    summary: str = ""
    legs: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id.strip():
            self.id = f"{self.provider_id}-{uuid4().hex[:8]}"
        if not self.provider_id.strip():
            raise ValueError("Provider ID cannot be empty.")
        if not self.provider_name.strip():
            raise ValueError("Provider name cannot be empty.")
        if not self.origin.strip():
            raise ValueError("Origin cannot be empty.")
        if not self.destination.strip():
            raise ValueError("Destination cannot be empty.")
        if self.cost is not None and self.cost < 0:
            raise ValueError("Cost cannot be negative.")
        if self.cost is None:
            self.cost_is_unknown = True
            # An unknown fare can never also be an estimate.
            self.cost_is_estimated = False
        if self.transfers < 0:
            raise ValueError("Transfers cannot be negative.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}.")


@dataclass(frozen=True)
class ProviderCapability:
    """Truthful declaration of what a mobility provider can actually supply."""

    provider_id: str
    name: str
    supported_modes: list[TransportMode]
    has_route_data: bool
    has_timetable: bool
    has_realtime: bool
    has_service_alerts: bool
    has_fare_estimates: bool
    booking_capability: BookingCapability
    api_available: bool
    auth_required: bool
    official_source_url: str | None = None
    is_enabled: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("Provider ID cannot be empty.")
        if not self.name.strip():
            raise ValueError("Provider name cannot be empty.")
