from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from app.domain.entities.mobility.enums import (
    MobilityLiveAvailability,
    MobilityLiveStatus,
    MobilitySourceType,
)
from app.domain.entities.mobility.live import MobilityLiveStatusReport
from app.domain.ports.mobility.live_ports import LiveStatusQuery, LiveStatusSourcePort

logger = logging.getLogger(__name__)


class HttpFetcher(Protocol):
    """Minimal fetch seam so the adapter is testable without a network."""

    async def get_json(self, url: str) -> Any:
        ...


class HttpxFetcher:
    """Default fetcher backed by the project's HTTP client."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout = timeout_seconds

    async def get_json(self, url: str) -> Any:
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()


class HttpJsonLiveStatusSource(LiveStatusSourcePort):
    """Reads a public JSON service-status feed for a single provider.

    The payload shape is intentionally small and explicit. A feed that does not
    conform, or that cannot be reached, yields an `UNAVAILABLE` report: this
    adapter has no fallback that guesses a status.
    """

    def __init__(
        self,
        url: str,
        provider_id: str,
        provider_name: str,
        source_name: str = "official",
        source_type: MobilitySourceType = MobilitySourceType.OFFICIAL_REALTIME,
        fetcher: HttpFetcher | None = None,
    ) -> None:
        self._url = url
        self._provider_id = provider_id
        self._provider_name = provider_name
        self._source_name = source_name
        self._source_type = source_type
        self._fetcher = fetcher or HttpxFetcher()

    @property
    def source_name(self) -> str:
        return self._source_name

    async def fetch_live_status(self, query: LiveStatusQuery) -> MobilityLiveStatusReport:
        try:
            payload = await self._fetcher.get_json(self._url)
        except Exception as exc:  # network/parse/HTTP failure must not fabricate
            logger.warning(
                "Live status feed for %s unavailable: %s", self._provider_id, exc
            )
            return self._unavailable(f"Live status feed unreachable ({type(exc).__name__}).")

        try:
            return self._to_report(payload)
        except Exception as exc:
            logger.warning(
                "Live status feed for %s returned an unusable payload: %s",
                self._provider_id,
                exc,
            )
            return self._unavailable("Live status feed returned an unrecognised payload.")

    def _unavailable(self, reason: str) -> MobilityLiveStatusReport:
        return MobilityLiveStatusReport(
            provider_id=self._provider_id,
            provider_name=self._provider_name,
            status=MobilityLiveStatus.UNKNOWN,
            availability=MobilityLiveAvailability.UNAVAILABLE,
            explanation=reason,
            source=self._source_name,
            source_type=MobilitySourceType.UNKNOWN,
            confidence=0.0,
        )

    def _to_report(self, payload: Any) -> MobilityLiveStatusReport:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        raw_status = str(payload.get("status", "")).strip().lower()
        if raw_status not in _STATUS_MAP:
            raise ValueError(f"unrecognised status {raw_status!r}")
        status = _STATUS_MAP[raw_status]

        observed = _parse_timestamp(payload.get("observed_at"))
        delay = payload.get("delay_minutes")
        delay_minutes = int(delay) if isinstance(delay, (int, float)) and delay >= 0 else None

        confidence = payload.get("confidence", 0.9)
        confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.9
        confidence = min(max(confidence, 0.0), 1.0)

        explanation = str(payload.get("explanation", "")).strip()
        if not explanation:
            explanation = f"{self._provider_name} service status: {status.value.replace('_', ' ')}."

        return MobilityLiveStatusReport(
            provider_id=self._provider_id,
            provider_name=self._provider_name,
            status=status,
            availability=MobilityLiveAvailability.LIVE,
            explanation=explanation,
            source=self._source_name,
            source_type=self._source_type,
            observed_at=observed,
            confidence=confidence,
            delay_minutes=delay_minutes,
            expected_departure=_parse_timestamp(payload.get("expected_departure")),
            expected_arrival=_parse_timestamp(payload.get("expected_arrival")),
        )


_STATUS_MAP: dict[str, MobilityLiveStatus] = {
    "operating_normal": MobilityLiveStatus.OPERATING_NORMAL,
    "on_time": MobilityLiveStatus.OPERATING_NORMAL,
    "live": MobilityLiveStatus.LIVE,
    "delayed": MobilityLiveStatus.DELAYED,
    "disrupted": MobilityLiveStatus.DISRUPTED,
    "cancelled": MobilityLiveStatus.CANCELLED,
    "canceled": MobilityLiveStatus.CANCELLED,
    "service_unavailable": MobilityLiveStatus.SERVICE_UNAVAILABLE,
    "out_of_service": MobilityLiveStatus.SERVICE_UNAVAILABLE,
}


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning None when absent or unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
