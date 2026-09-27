from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.entities.mobility.enums import (
    BLOCKING_LIVE_STATUSES,
    MobilityLiveAvailability,
    MobilityLiveStatus,
    MobilitySourceType,
)
from app.domain.entities.mobility.models import MobilityEvidence


@dataclass(frozen=True)
class MobilityLiveStatusReport:
    """A truthful snapshot of what is known about a service right now.

    A report is always returned, even when nothing is known: `availability=UNAVAILABLE`
    with `status=UNKNOWN` is a valid and expected answer. Fields that are not known
    stay `None` rather than being defaulted to a plausible-looking value.
    """

    provider_id: str
    provider_name: str
    status: MobilityLiveStatus = MobilityLiveStatus.UNKNOWN
    availability: MobilityLiveAvailability = MobilityLiveAvailability.UNAVAILABLE
    explanation: str = ""
    source: str = ""
    source_type: MobilitySourceType = MobilitySourceType.UNKNOWN
    observed_at: datetime | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: float = 0.0
    delay_minutes: int | None = None
    expected_departure: datetime | None = None
    expected_arrival: datetime | None = None
    evidence: tuple[MobilityEvidence, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("Live status report provider_id cannot be empty.")
        if not self.provider_name.strip():
            raise ValueError("Live status report provider_name cannot be empty.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}.")
        if self.delay_minutes is not None and self.delay_minutes < 0:
            raise ValueError("Delay minutes cannot be negative.")
        # An unknown service can never carry a delay claim or a reported duration.
        if self.availability is not MobilityLiveAvailability.LIVE:
            if self.status is not MobilityLiveStatus.UNKNOWN and (
                self.availability is MobilityLiveAvailability.UNAVAILABLE
            ):
                raise ValueError(
                    "An unavailable live source cannot assert a concrete service status."
                )

    @property
    def is_live(self) -> bool:
        return self.availability is MobilityLiveAvailability.LIVE

    @property
    def is_stale(self) -> bool:
        """True when live data is no longer fresh enough to describe "now".

        Covers both a report already downgraded to `STALE` and live data that has
        aged past the trust window but has not yet been downgraded.
        """
        if self.availability is MobilityLiveAvailability.STALE:
            return True
        if self.availability is not MobilityLiveAvailability.LIVE or self.observed_at is None:
            return False
        observed = self.observed_at if self.observed_at.tzinfo else self.observed_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - observed > timedelta(minutes=STALE_AFTER_MINUTES)

    @property
    def is_blocking(self) -> bool:
        """True when the service cannot be used as planned (cancelled/disrupted/down)."""
        return self.is_live and self.status in BLOCKING_LIVE_STATUSES

    @property
    def freshness_minutes(self) -> int | None:
        if self.observed_at is None:
            return None
        observed = self.observed_at if self.observed_at.tzinfo else self.observed_at.replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - observed).total_seconds() // 60))

    def effective_status(self) -> MobilityLiveStatus:
        """Stale live data is reported as unknown rather than presented as current."""
        if self.is_stale:
            return MobilityLiveStatus.UNKNOWN
        return self.status


#: Live data older than this is no longer trusted to describe "now".
STALE_AFTER_MINUTES = 30


def unavailable_live_status(
    provider_id: str,
    provider_name: str,
    reason: str,
) -> MobilityLiveStatusReport:
    """Build the canonical "no live source configured" report.

    This is the honest answer for providers that publish no reachable public feed.
    """
    return MobilityLiveStatusReport(
        provider_id=provider_id,
        provider_name=provider_name,
        status=MobilityLiveStatus.UNKNOWN,
        availability=MobilityLiveAvailability.UNAVAILABLE,
        explanation=reason,
        source="none",
        source_type=MobilitySourceType.UNKNOWN,
        confidence=0.0,
    )
