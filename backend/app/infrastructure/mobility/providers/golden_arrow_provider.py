from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)
from app.domain.entities.mobility.models import (
    MobilityEvidence,
    MobilityOption,
    MobilityRequirement,
    ProviderCapability,
)
from app.domain.ports.mobility.ports import MobilityProviderPort
from app.infrastructure.mobility.geo import address_serves_place, estimate_network_distance_km

GABS_HUBS = [
    "cape town cbd",
    "cape town station",
    "civic centre",
    "wynberg",
    "claremont",
    "bellville",
    "woodstock",
    "salt river",
    "mowbray",
    "athlone",
    "mitchells plain",
    "khayelitsha",
    "atlantis",
]


class GoldenArrowProvider(MobilityProviderPort):
    """Golden Arrow Bus Services (GABS) commuter transport adapter."""

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="golden_arrow",
            name="Golden Arrow Bus Services",
            supported_modes=[TransportMode.BUS],
            has_route_data=True,
            has_timetable=True,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=False,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            official_source_url="https://www.gabs.co.za",
            is_enabled=True,
            notes="Commuter bus network across the Cape Town metropolitan area. Exact cash/clip-card fares and real-time tracking are not available via public API; cost is explicitly unknown.",
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # GABS only claims a journey when both ends are served by a GABS hub. Matching on the
        # city name would claim a bus route for every Cape Town address.
        has_orig = any(address_serves_place(requirement.origin, hub) for hub in GABS_HUBS)
        has_dest = any(address_serves_place(requirement.destination, hub) for hub in GABS_HUBS)

        if not (has_orig and has_dest):
            return []

        distance_km = estimate_network_distance_km(
            requirement.origin,
            requirement.destination,
            requirement.origin_coordinates,
            requirement.destination_coordinates,
        )

        duration_minutes = max(15, int(round((distance_km / 20.0) * 60)) + 6)
        dep_time = requirement.departure_time or datetime.now(UTC)
        arr_time = requirement.arrival_time
        if arr_time is not None and requirement.departure_time is None:
            dep_time = arr_time - timedelta(minutes=duration_minutes)
        else:
            arr_time = dep_time + timedelta(minutes=duration_minutes)

        evidence = MobilityEvidence(
            claim="Scheduled Golden Arrow commuter bus service between metropolitan hubs.",
            source="Golden Arrow Timetable Information",
            source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
            observed_at=datetime.now(UTC),
            confidence=0.70,
            relevant_provider="golden_arrow",
        )

        option = MobilityOption(
            id=f"gabs-{uuid4().hex[:8]}",
            provider_id="golden_arrow",
            provider_name="Golden Arrow Bus Services",
            mode=TransportMode.BUS,
            origin=requirement.origin,
            destination=requirement.destination,
            departure_time=dep_time,
            arrival_time=arr_time,
            duration_minutes=duration_minutes,
            cost=None,  # Factual: fare is unverified without smartcard/cash scale
            cost_is_unknown=True,
            currency="ZAR",
            walking_duration_minutes=6,
            transfers=0,
            availability="available",
            live_status=MobilityLiveStatus.UNKNOWN,
            booking_capability=BookingCapability.NO_BOOKING,
            booking_url="https://www.gabs.co.za",
            source="Golden Arrow Bus Services",
            source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
            retrieved_at=datetime.now(UTC),
            confidence=0.70,
            evidence=[evidence],
            summary=f"Golden Arrow Bus (~{duration_minutes} min, fare varies)",
        )
        return [option]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None
