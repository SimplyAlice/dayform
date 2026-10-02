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
from app.infrastructure.mobility.geo import (
    estimate_network_distance_km,
    is_in_cape_town_service_area,
)


class BoltProvider(MobilityProviderPort):
    """Bolt ride-hail adapter supporting external provider handoff."""

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="bolt",
            name="Bolt",
            supported_modes=[TransportMode.RIDE_HAIL],
            has_route_data=True,
            has_timetable=False,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=False,
            booking_capability=BookingCapability.EXTERNAL_HANDOFF,
            api_available=False,
            auth_required=True,
            official_source_url="https://bolt.eu",
            is_enabled=True,
            notes="Hands off to Bolt ride-hailing service. Bolt does not provide an open public API; pricing and bookings are completed in the Bolt application.",
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # Bolt does not cover the whole country; declining outside the operating
        # area keeps it from becoming the default answer on legs it cannot serve.
        if not is_in_cape_town_service_area(
            requirement.origin
        ) or not is_in_cape_town_service_area(requirement.destination):
            return []

        distance_km = estimate_network_distance_km(
            requirement.origin,
            requirement.destination,
            requirement.origin_coordinates,
            requirement.destination_coordinates,
        )

        drive_minutes = max(5, int(round((distance_km / 35.0) * 60)))
        total_duration = drive_minutes + 4

        dep_time = requirement.departure_time or datetime.now(UTC)
        arr_time = requirement.arrival_time
        if arr_time is not None and requirement.departure_time is None:
            dep_time = arr_time - timedelta(minutes=total_duration)
        else:
            arr_time = dep_time + timedelta(minutes=total_duration)

        evidence = MobilityEvidence(
            claim="External handoff to Bolt ride-hailing.",
            source="Bolt Information Reference",
            source_type=MobilitySourceType.TRUSTED_THIRD_PARTY,
            observed_at=datetime.now(UTC),
            confidence=0.75,
            relevant_provider="bolt",
        )

        option = MobilityOption(
            id=f"bolt-ride-{uuid4().hex[:8]}",
            provider_id="bolt",
            provider_name="Bolt",
            mode=TransportMode.RIDE_HAIL,
            origin=requirement.origin,
            destination=requirement.destination,
            departure_time=dep_time,
            arrival_time=arr_time,
            duration_minutes=total_duration,
            cost=None,  # Unknown without authenticated API
            cost_is_unknown=True,
            currency="ZAR",
            walking_duration_minutes=0,
            transfers=0,
            availability="available",
            live_status=MobilityLiveStatus.UNKNOWN,
            booking_capability=BookingCapability.EXTERNAL_HANDOFF,
            booking_url="https://bolt.eu",
            source="Bolt External Service",
            source_type=MobilitySourceType.TRUSTED_THIRD_PARTY,
            retrieved_at=datetime.now(UTC),
            confidence=0.75,
            evidence=[evidence],
            summary=f"Bolt ride (~{total_duration} min drive, fare confirmed in app)",
        )
        return [option]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None
