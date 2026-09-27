from __future__ import annotations

from app.domain.entities.mobility.live import (
    MobilityLiveStatusReport,
    unavailable_live_status,
)
from app.domain.ports.mobility.live_ports import LiveStatusQuery, LiveStatusSourcePort


class UnavailableLiveStatusSource(LiveStatusSourcePort):
    """Truthful stand-in for providers that publish no reachable public live feed.

    Uber, Bolt and inDrive, along with the Cape Town transit operators, do not
    expose an unauthenticated public realtime feed. Rather than guessing, this
    source states plainly that live status is unavailable for that provider.
    """

    def __init__(self, reason: str = "This operator publishes no public live service feed.") -> None:
        self._reason = reason

    @property
    def source_name(self) -> str:
        return "none"

    async def fetch_live_status(self, query: LiveStatusQuery) -> MobilityLiveStatusReport:
        return unavailable_live_status(
            provider_id=query.provider_id,
            provider_name=query.provider_name,
            reason=self._reason,
        )
