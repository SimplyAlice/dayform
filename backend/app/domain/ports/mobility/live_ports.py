from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.entities.mobility.live import MobilityLiveStatusReport


@dataclass(frozen=True)
class LiveStatusQuery:
    """What a provider is being asked about when live status is requested."""

    provider_id: str
    provider_name: str
    origin: str | None = None
    destination: str | None = None
    route: str | None = None


class LiveStatusSourcePort(Protocol):
    """Boundary for a provider-specific live service-status source.

    Implementations must never fabricate a status. When the underlying feed is
    absent, unreachable, or malformed they return a report whose availability is
    `UNAVAILABLE` (or `STALE`) rather than a plausible-looking status.
    """

    @property
    def source_name(self) -> str:
        """Human-readable identity of the upstream source, used in evidence."""
        ...

    async def fetch_live_status(self, query: LiveStatusQuery) -> MobilityLiveStatusReport:
        """Retrieve the current service status, or a truthful 'not available' report."""
        ...
