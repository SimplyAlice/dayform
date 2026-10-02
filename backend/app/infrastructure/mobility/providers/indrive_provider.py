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


class InDriveProvider(MobilityProviderPort):
    """inDrive ride-hail adapter supporting external provider handoff."""

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="indrive",
            name="inDrive",
            supported_modes=[TransportMode.RIDE_HAIL],
            has_route_data=True,
            has_timetable=False,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=False,
            booking_capability=BookingCapability.EXTERNAL_HANDOFF,
            api_available=False,
            auth_required=True,
            official_source_url="https://indrive.com",
            is_enabled=True,
            notes="Hands off to inDrive peer-to-peer ride-hailing. Fares are bid dynamically between passenger and driver in-app and are unknown in advance.",
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # inDrive depends on nearby drivers, so it does not operate everywhere.
        # Declining outside the operating area avoids it becoming the default
        # answer on legs it has no chance of serving.
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
        total_duration = drive_minutes + 5

        dep_time = requirement.departure_time or datetime.now(UTC)
        arr_time = requirement.arrival_time
        if arr_time is not None and requirement.departure_time is None:
            dep_time = arr_time - timedelta(minutes=total_duration)
        else:
            arr_time = dep_time + timedelta(minutes=total_duration)

        evidence = MobilityEvidence(
            claim="External handoff to inDrive peer-to-peer ride negotiation.",
            source="inDrive Information Reference",
            source_type=MobilitySourceType.TRUSTED_THIRD_PARTY,
            observed_at=datetime.now(UTC),
            confidence=0.70,
            relevant_provider="indrive",
        )

        option = MobilityOption(
            id=f"indrive-ride-{uuid4().hex[:8]}",
            provider_id="indrive",
            provider_name="inDrive",
            mode=TransportMode.RIDE_HAIL,
            origin=requirement.origin,
            destination=requirement.destination,
            departure_time=dep_time,
            arrival_time=arr_time,
            duration_minutes=total_duration,
            cost=None,  # Factual: inDrive uses negotiated peer-to-peer bidding
            cost_is_unknown=True,
            currency="ZAR",
            walking_duration_minutes=0,
            transfers=0,
            availability="available",
            live_status=MobilityLiveStatus.UNKNOWN,
            booking_capability=BookingCapability.EXTERNAL_HANDOFF,
            booking_url="https://indrive.com",
            source="inDrive Mobile Platform",
            source_type=MobilitySourceType.TRUSTED_THIRD_PARTY,
            retrieved_at=datetime.now(UTC),
            confidence=0.70,
            evidence=[evidence],
            summary=f"inDrive ride (~{total_duration} min drive, fare negotiated in app)",
        )
        return [option]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None
