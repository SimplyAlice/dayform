"""Tests for M16 live mobility intelligence.

Covers the live status model, evidence/provenance, provider live responses,
unavailable and stale handling, delayed/disrupted services, and consumption of
live state by M15 transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.application.mobility.live_service import (
    LiveMobilityService,
    LiveStatusRegistry,
)
from app.application.mobility.registry import MobilityProviderRegistry
from app.application.mobility.service import MobilityService
from app.application.planning.mobility_planning_service import (
    MobilityPlanningService,
    StopSequencePoint,
)
from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveAvailability,
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)
from app.domain.entities.mobility.live import MobilityLiveStatusReport
from app.domain.entities.mobility.models import (
    MobilityEvidence,
    MobilityOption,
    MobilityRequirement,
    ProviderCapability,
)
from app.domain.ports.mobility.live_ports import LiveStatusQuery, LiveStatusSourcePort
from app.domain.ports.mobility.ports import MobilityProviderPort
from app.infrastructure.mobility.live import (
    HttpJsonLiveStatusSource,
    UnavailableLiveStatusSource,
)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class StubProvider(MobilityProviderPort):
    def __init__(self, provider_id: str = "myciti", name: str = "MyCiTi") -> None:
        self._provider_id = provider_id
        self._name = name

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self._provider_id,
            name=self._name,
            supported_modes=[TransportMode.BUS],
            has_route_data=True,
            has_timetable=True,
            # Truthful: no public realtime feed is configured for this provider.
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=True,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        return [
            MobilityOption(
                id=f"{self._provider_id}-1",
                provider_id=self._provider_id,
                provider_name=self._name,
                mode=TransportMode.BUS,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=12,
                cost=Decimal("10.50"),
                confidence=0.8,
                summary=f"{self._name} 12 min",
            )
        ]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None


class StubLiveSource(LiveStatusSourcePort):
    def __init__(self, report: MobilityLiveStatusReport | Exception) -> None:
        self._report = report
        self.calls = 0

    @property
    def source_name(self) -> str:
        return "stub"

    async def fetch_live_status(self, query: LiveStatusQuery) -> MobilityLiveStatusReport:
        self.calls += 1
        if isinstance(self._report, Exception):
            raise self._report
        return self._report


class StubFetcher:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def get_json(self, url: str):
        if self.error:
            raise self.error
        return self.payload


def build_service(
    live_report=None,
    live_error: Exception | None = None,
    provider_id: str = "myciti",
) -> tuple[MobilityPlanningService, LiveMobilityService]:
    provider = StubProvider(provider_id=provider_id)
    registry = MobilityProviderRegistry()
    registry.register(provider)

    live_registry = LiveStatusRegistry()
    if live_report is not None or live_error is not None:
        source = StubLiveSource(live_error or live_report)
        live_registry.register(provider_id, source)

    live_service = LiveMobilityService(registry, live_registry)
    planning = MobilityPlanningService(MobilityService(registry), live_service)
    return planning, live_service


def report(
    status: MobilityLiveStatus,
    *,
    availability: MobilityLiveAvailability = MobilityLiveAvailability.LIVE,
    observed_at: datetime | None = None,
    source_type: MobilitySourceType = MobilitySourceType.OFFICIAL_REALTIME,
    delay_minutes: int | None = None,
    explanation: str = "test",
) -> MobilityLiveStatusReport:
    return MobilityLiveStatusReport(
        provider_id="myciti",
        provider_name="MyCiTi",
        status=status,
        availability=availability,
        explanation=explanation,
        source="myciti-status",
        source_type=source_type,
        observed_at=observed_at if observed_at is not None else datetime.now(UTC),
        confidence=0.9,
        delay_minutes=delay_minutes,
    )


async def evaluate_one(plan_service: MobilityPlanningService) -> list:
    now = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
    stops = [
        StopSequencePoint(
            location="Civic Centre, Cape Town",
            name="Brunch",
            start_time=now,
            end_time=now + timedelta(hours=1),
        ),
        StopSequencePoint(
            location="Gardens, Cape Town",
            name="Walk",
            start_time=now + timedelta(hours=1, minutes=30),
            end_time=now + timedelta(hours=2, minutes=30),
        ),
    ]
    return await plan_service.evaluate_stop_sequence(stops)


# --------------------------------------------------------------------------
# 1. Live status model
# --------------------------------------------------------------------------


def test_live_status_model_exposes_full_state_range() -> None:
    for value in (
        "operating_normal",
        "delayed",
        "disrupted",
        "cancelled",
        "service_unavailable",
        "unknown",
    ):
        assert MobilityLiveStatus(value).value == value


def test_live_status_report_requires_identity() -> None:
    with pytest.raises(ValueError):
        MobilityLiveStatusReport(provider_id="", provider_name="MyCiTi")
    with pytest.raises(ValueError):
        MobilityLiveStatusReport(provider_id="myciti", provider_name="  ")


def test_live_status_report_rejects_invalid_confidence_and_delay() -> None:
    with pytest.raises(ValueError):
        MobilityLiveStatusReport(provider_id="a", provider_name="A", confidence=1.5)
    with pytest.raises(ValueError):
        MobilityLiveStatusReport(provider_id="a", provider_name="A", delay_minutes=-3)


def test_unavailable_source_cannot_assert_a_concrete_status() -> None:
    with pytest.raises(ValueError):
        MobilityLiveStatusReport(
            provider_id="myciti",
            provider_name="MyCiTi",
            status=MobilityLiveStatus.DELAYED,
            availability=MobilityLiveAvailability.UNAVAILABLE,
        )


def test_blocking_and_live_helpers() -> None:
    assert report(MobilityLiveStatus.DISRUPTED).is_blocking is True
    assert report(MobilityLiveStatus.CANCELLED).is_blocking is True
    assert report(MobilityLiveStatus.SERVICE_UNAVAILABLE).is_blocking is True
    assert report(MobilityLiveStatus.DELAYED).is_blocking is False
    assert report(MobilityLiveStatus.OPERATING_NORMAL).is_blocking is False
    assert report(MobilityLiveStatus.OPERATING_NORMAL).is_live is True


# --------------------------------------------------------------------------
# 2. Live evidence / provenance
# --------------------------------------------------------------------------


def test_live_report_preserves_provenance_fields() -> None:
    observed = datetime.now(UTC) - timedelta(minutes=3)
    r = report(MobilityLiveStatus.OPERATING_NORMAL, observed_at=observed)
    assert r.source == "myciti-status"
    assert r.source_type is MobilitySourceType.OFFICIAL_REALTIME
    assert r.observed_at == observed
    assert r.retrieved_at is not None
    assert r.confidence == 0.9
    assert r.freshness_minutes is not None and r.freshness_minutes >= 3


@pytest.mark.asyncio
async def test_untrusted_source_type_cannot_claim_a_status() -> None:
    """Weak provenance must not present itself as a concrete service state."""
    _, live = build_service(
        live_report=report(
            MobilityLiveStatus.OPERATING_NORMAL, source_type=MobilitySourceType.UNKNOWN
        )
    )
    result = await live.get_live_status("myciti")
    assert result.availability is MobilityLiveAvailability.UNAVAILABLE
    assert result.status is MobilityLiveStatus.UNKNOWN


# --------------------------------------------------------------------------
# 3. Provider live response (real adapter, stubbed transport)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_source_parses_operating_normal_payload() -> None:
    src = HttpJsonLiveStatusSource(
        url="https://example.test/status.json",
        provider_id="myciti",
        provider_name="MyCiTi",
        fetcher=StubFetcher(
            {
                "status": "operating_normal",
                "explanation": "PRASA service operating normally.",
                "observed_at": datetime.now(UTC).isoformat(),
                "confidence": 0.95,
            }
        ),
    )
    r = await src.fetch_live_status(LiveStatusQuery("myciti", "MyCiTi"))
    assert r.status is MobilityLiveStatus.OPERATING_NORMAL
    assert r.availability is MobilityLiveAvailability.LIVE
    assert r.explanation == "PRASA service operating normally."
    assert r.confidence == 0.95
    assert r.is_live is True


@pytest.mark.asyncio
async def test_http_source_parses_delay_minutes() -> None:
    src = HttpJsonLiveStatusSource(
        url="https://example.test/status.json",
        provider_id="myciti",
        provider_name="MyCiTi",
        fetcher=StubFetcher(
            {
                "status": "delayed",
                "delay_minutes": 15,
                "observed_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    r = await src.fetch_live_status(LiveStatusQuery("myciti", "MyCiTi"))
    assert r.status is MobilityLiveStatus.DELAYED
    assert r.delay_minutes == 15
    assert "delayed" in r.explanation.lower()


# --------------------------------------------------------------------------
# 4. Unknown / unavailable response
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_without_feed_reports_unavailable_not_unknown_data() -> None:
    _, live = build_service()
    r = await live.get_live_status("myciti")
    assert r.availability is MobilityLiveAvailability.UNAVAILABLE
    assert r.status is MobilityLiveStatus.UNKNOWN
    assert r.confidence == 0.0
    assert r.source_type is MobilitySourceType.UNKNOWN
    assert "No public live feed" in r.explanation


@pytest.mark.asyncio
async def test_unknown_provider_reports_unavailable() -> None:
    _, live = build_service()
    r = await live.get_live_status("does_not_exist")
    assert r.availability is MobilityLiveAvailability.UNAVAILABLE
    assert r.status is MobilityLiveStatus.UNKNOWN


@pytest.mark.asyncio
async def test_unreachable_feed_does_not_fabricate_status() -> None:
    src = HttpJsonLiveStatusSource(
        url="https://example.test/status.json",
        provider_id="myciti",
        provider_name="MyCiTi",
        fetcher=StubFetcher(error=TimeoutError("connection refused")),
    )
    r = await src.fetch_live_status(LiveStatusQuery("myciti", "MyCiTi"))
    assert r.availability is MobilityLiveAvailability.UNAVAILABLE
    assert r.status is MobilityLiveStatus.UNKNOWN
    assert r.delay_minutes is None
    assert r.expected_departure is None


@pytest.mark.asyncio
async def test_malformed_feed_does_not_fabricate_status() -> None:
    src = HttpJsonLiveStatusSource(
        url="https://example.test/status.json",
        provider_id="myciti",
        provider_name="MyCiTi",
        fetcher=StubFetcher({"status": "totally_made_up"}),
    )
    r = await src.fetch_live_status(LiveStatusQuery("myciti", "MyCiTi"))
    assert r.status is MobilityLiveStatus.UNKNOWN
    assert r.availability is MobilityLiveAvailability.UNAVAILABLE


@pytest.mark.asyncio
async def test_ride_hail_provider_has_no_live_source() -> None:
    """Uber/Bolt/inDrive publish no public feed, so they must not appear live."""
    src = UnavailableLiveStatusSource()
    r = await src.fetch_live_status(LiveStatusQuery("uber", "Uber"))
    assert r.provider_id == "uber"
    assert r.availability is MobilityLiveAvailability.UNAVAILABLE
    assert r.status is MobilityLiveStatus.UNKNOWN
    assert r.is_live is False


# --------------------------------------------------------------------------
# 5. Stale data handling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_live_data_is_downgraded_and_never_claims_current_state() -> None:
    stale = report(
        MobilityLiveStatus.OPERATING_NORMAL,
        observed_at=datetime.now(UTC) - timedelta(hours=3),
    )
    _, live = build_service(live_report=stale)
    r = await live.get_live_status("myciti")
    assert r.availability is MobilityLiveAvailability.STALE
    assert r.effective_status() is MobilityLiveStatus.UNKNOWN
    assert r.is_stale is True
    assert "minutes ago" in r.explanation


@pytest.mark.asyncio
async def test_fresh_live_data_is_not_downgraded() -> None:
    fresh = report(
        MobilityLiveStatus.OPERATING_NORMAL, observed_at=datetime.now(UTC) - timedelta(minutes=2)
    )
    _, live = build_service(live_report=fresh)
    r = await live.get_live_status("myciti")
    assert r.availability is MobilityLiveAvailability.LIVE
    assert r.effective_status() is MobilityLiveStatus.OPERATING_NORMAL


# --------------------------------------------------------------------------
# 6 & 7. Delayed / disrupted services
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delayed_service_is_reported_with_evidence() -> None:
    delayed = report(MobilityLiveStatus.DELAYED, delay_minutes=12)
    _, live = build_service(live_report=delayed)
    r = await live.get_live_status("myciti")
    assert r.status is MobilityLiveStatus.DELAYED
    assert r.delay_minutes == 12
    assert r.availability is MobilityLiveAvailability.LIVE


@pytest.mark.asyncio
async def test_disrupted_service_is_blocking() -> None:
    _, live = build_service(live_report=report(MobilityLiveStatus.DISRUPTED))
    r = await live.get_live_status("myciti")
    assert r.status is MobilityLiveStatus.DISRUPTED
    assert r.is_blocking is True


@pytest.mark.asyncio
async def test_multi_provider_lookup_isolates_failures() -> None:
    provider = StubProvider()
    registry = MobilityProviderRegistry()
    registry.register(provider)
    live_registry = LiveStatusRegistry()
    live_registry.register("myciti", StubLiveSource(RuntimeError("feed down")))
    live = LiveMobilityService(registry, live_registry)
    reports = await live.get_live_status_for_providers(["myciti"])
    assert reports["myciti"].availability is MobilityLiveAvailability.UNAVAILABLE
    assert reports["myciti"].status is MobilityLiveStatus.UNKNOWN


# --------------------------------------------------------------------------
# 8. Planning consumption of live mobility state
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operating_normal_live_service_leaves_plan_untouched() -> None:
    planning, _ = build_service(
        live_report=report(
            MobilityLiveStatus.OPERATING_NORMAL, explanation="PRASA service operating normally."
        )
    )
    transitions = await evaluate_one(planning)
    assert len(transitions) == 1
    t = transitions[0]
    assert t.live_status is MobilityLiveStatus.OPERATING_NORMAL
    assert t.live_availability is MobilityLiveAvailability.LIVE
    assert t.live_explanation == "PRASA service operating normally."
    assert t.live_confidence == 0.9
    assert t.is_feasible is True


@pytest.mark.asyncio
async def test_delayed_service_does_not_invent_extra_travel_time() -> None:
    """The planner must stay conservative: a reported delay is shown, not scheduled."""
    planning, _ = build_service(
        live_report=report(MobilityLiveStatus.DELAYED, delay_minutes=20)
    )
    transitions = await evaluate_one(planning)
    t = transitions[0]
    assert t.live_status is MobilityLiveStatus.DELAYED
    assert t.live_delay_minutes == 20
    # Duration is unchanged: no evidence-based adjustment was made.
    assert t.duration_minutes == 12
    assert t.is_feasible is True


@pytest.mark.asyncio
async def test_disrupted_service_marks_transition_infeasible_with_reason() -> None:
    planning, _ = build_service(live_report=report(MobilityLiveStatus.DISRUPTED))
    transitions = await evaluate_one(planning)
    t = transitions[0]
    assert t.live_status is MobilityLiveStatus.DISRUPTED
    assert t.is_feasible is False
    assert "disrupted" in (t.feasibility_issue or "").lower()


@pytest.mark.asyncio
async def test_cancelled_service_marks_transition_infeasible() -> None:
    planning, _ = build_service(live_report=report(MobilityLiveStatus.CANCELLED))
    t = (await evaluate_one(planning))[0]
    assert t.is_feasible is False
    assert "cancelled" in (t.feasibility_issue or "").lower()


@pytest.mark.asyncio
async def test_absent_live_layer_leaves_transition_truthfully_unavailable() -> None:
    """M15 still works standalone; without M16 there is simply no live state."""
    registry = MobilityProviderRegistry()
    registry.register(StubProvider())
    planning = MobilityPlanningService(MobilityService(registry))
    t = (await evaluate_one(planning))[0]
    assert t.live_availability is MobilityLiveAvailability.UNAVAILABLE
    assert t.live_status is MobilityLiveStatus.UNKNOWN
    assert t.is_feasible is True


@pytest.mark.asyncio
async def test_live_lookup_failure_does_not_break_planning() -> None:
    planning, _ = build_service(live_error=RuntimeError("feed exploded"))
    t = (await evaluate_one(planning))[0]
    assert t.duration_minutes == 12
    assert t.is_feasible is True
    assert t.live_availability is MobilityLiveAvailability.UNAVAILABLE


# --------------------------------------------------------------------------
# 9. M15 regression
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m15_transition_evaluation_is_unchanged_by_m16() -> None:
    """The 12-minute leg and its 30-minute window behave exactly as in M15."""
    planning, _ = build_service()
    t = (await evaluate_one(planning))[0]
    assert t.duration_minutes == 12
    assert t.cost == Decimal("10.50")
    assert t.cost_known is True
    assert t.is_feasible is True
    assert t.feasibility_issue is None
