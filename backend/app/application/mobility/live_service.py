from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.application.mobility.registry import MobilityProviderRegistry
from app.domain.entities.mobility.enums import (
    MobilityLiveAvailability,
    MobilityLiveStatus,
    get_source_hierarchy_weight,
)
from app.domain.entities.mobility.live import MobilityLiveStatusReport, unavailable_live_status
from app.domain.ports.mobility.live_ports import LiveStatusQuery, LiveStatusSourcePort

logger = logging.getLogger(__name__)


@dataclass
class LiveStatusRegistry:
    """Maps provider ids to the live source configured for that provider.

    A provider with no entry has no live source at all, and is reported as
    unavailable rather than unknown-after-a-lookup.
    """

    sources: dict[str, LiveStatusSourcePort] = field(default_factory=dict)

    def get(self, provider_id: str) -> LiveStatusSourcePort | None:
        return self.sources.get(provider_id)

    def register(self, provider_id: str, source: LiveStatusSourcePort) -> None:
        self.sources[provider_id] = source


class LiveMobilityService:
    """Aggregates live service status across providers without inventing data."""

    def __init__(
        self,
        provider_registry: MobilityProviderRegistry,
        live_registry: LiveStatusRegistry | None = None,
    ) -> None:
        self._providers = provider_registry
        self._live = live_registry or LiveStatusRegistry()

    @property
    def live_registry(self) -> LiveStatusRegistry:
        return self._live

    async def get_live_status(
        self,
        provider_id: str,
        origin: str | None = None,
        destination: str | None = None,
        route: str | None = None,
    ) -> MobilityLiveStatusReport:
        """Return the current live status for one provider.

        Always returns a report. Providers without a configured feed, and feeds
        that fail, produce an `UNAVAILABLE`/`UNKNOWN` report with provenance rather
        than an invented status.
        """
        provider = self._find_provider(provider_id)
        if provider is None:
            return unavailable_live_status(
                provider_id=provider_id,
                provider_name=provider_id,
                reason=f"No mobility provider named '{provider_id}' is registered.",
            )

        cap = provider.capability
        if not cap.is_enabled:
            return unavailable_live_status(
                provider_id=cap.provider_id,
                provider_name=cap.name,
                reason="This provider is currently disabled.",
            )

        source = self._live.get(provider_id)
        if source is None:
            return unavailable_live_status(
                provider_id=cap.provider_id,
                provider_name=cap.name,
                reason=(
                    "No public live feed is configured for this provider. "
                    "Status shown is planned, not live."
                ),
            )

        report = await source.fetch_live_status(
            LiveStatusQuery(
                provider_id=cap.provider_id,
                provider_name=cap.name,
                origin=origin,
                destination=destination,
                route=route,
            )
        )
        return _apply_staleness(report)

    async def get_live_status_for_providers(
        self, provider_ids: list[str]
    ) -> dict[str, MobilityLiveStatusReport]:
        """Fetch live status for several providers concurrently, isolating failures."""
        results = await asyncio.gather(
            *(self.get_live_status(pid) for pid in provider_ids), return_exceptions=True
        )
        reports: dict[str, MobilityLiveStatusReport] = {}
        for provider_id, result in zip(provider_ids, results, strict=False):
            if isinstance(result, Exception):
                logger.error("Live status lookup for %s failed: %s", provider_id, result)
                reports[provider_id] = unavailable_live_status(
                    provider_id=provider_id,
                    provider_name=provider_id,
                    reason="Live status lookup failed.",
                )
            else:
                reports[provider_id] = result
        return reports

    def _find_provider(self, provider_id: str):
        for provider in self._providers.get_enabled_providers():
            if provider.capability.provider_id == provider_id:
                return provider
        return None


def _apply_staleness(report: MobilityLiveStatusReport) -> MobilityLiveStatusReport:
    """Downgrade aged live data to STALE so it is never presented as current.

    Weak sources also never displace stronger evidence: an UNKNOWN-typed report
    cannot claim a concrete status.
    """
    if report.availability is not MobilityLiveAvailability.LIVE:
        return report
    if get_source_hierarchy_weight(report.source_type) <= 0:
        return MobilityLiveStatusReport(
            provider_id=report.provider_id,
            provider_name=report.provider_name,
            status=MobilityLiveStatus.UNKNOWN,
            availability=MobilityLiveAvailability.UNAVAILABLE,
            explanation="Live status could not be attributed to a trustworthy source.",
            source=report.source,
            source_type=report.source_type,
            observed_at=report.observed_at,
            confidence=0.0,
            evidence=report.evidence,
        )
    if report.is_stale:
        return MobilityLiveStatusReport(
            provider_id=report.provider_id,
            provider_name=report.provider_name,
            status=report.status,
            availability=MobilityLiveAvailability.STALE,
            explanation=(
                f"{report.explanation} "
                f"(last updated {report.freshness_minutes} minutes ago)"
            ).strip(),
            source=report.source,
            source_type=report.source_type,
            observed_at=report.observed_at,
            confidence=report.confidence,
            delay_minutes=report.delay_minutes,
            evidence=report.evidence,
        )
    return report
