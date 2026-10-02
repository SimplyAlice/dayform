from __future__ import annotations

import urllib.parse
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
    find_coordinates,
    is_in_cape_town_service_area,
)


def build_uber_deeplink(
    destination: str,
    destination_coords: tuple[float, float] | None = None,
) -> str:
    """Build an official Uber Universal Link (m.uber.com/ul/) with pre-filled destination.

    Works without developer credentials on iOS and Android devices, opening the native Uber app
    or falling back to the mobile web.
    """
    params: list[tuple[str, str]] = [
        ("action", "setPickup"),
        ("pickup", "my_location"),
        ("dropoff[nickname]", destination),
        ("dropoff[formatted_address]", destination),
    ]

    coords = destination_coords or find_coordinates(destination)
    if coords:
        params.append(("dropoff[latitude]", str(coords[0])))
        params.append(("dropoff[longitude]", str(coords[1])))

    query = urllib.parse.urlencode(params)
    return f"https://m.uber.com/ul/?{query}"


class UberProvider(MobilityProviderPort):
    """Uber ride-hail adapter supporting official universal deep-link handoff."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="uber",
            name="Uber",
            supported_modes=[TransportMode.RIDE_HAIL],
            has_route_data=True,
            has_timetable=False,
            has_realtime=bool(self._api_key),
            has_service_alerts=False,
            has_fare_estimates=bool(self._api_key),
            booking_capability=BookingCapability.DEEPLINK,
            api_available=bool(self._api_key),
            auth_required=True,
            official_source_url="https://developer.uber.com",
            is_enabled=True,
            notes="Hands off to the native Uber application via universal deep-link. Dynamic fares and live driver locations are not fabricated and require authenticated Uber API credentials.",
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # Uber does not operate everywhere, so a journey outside the service area is
        # not offered rather than offered optimistically. Answering unconditionally
        # would make Uber the last surviving option on every leg.
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

        # Driving speed in urban Cape Town: ~35 km/h + 3 min dispatch pickup buffer
        drive_minutes = max(5, int(round((distance_km / 35.0) * 60)))
        total_duration = drive_minutes + 3

        dep_time = requirement.departure_time or datetime.now(UTC)
        arr_time = requirement.arrival_time
        if arr_time is not None and requirement.departure_time is None:
            dep_time = arr_time - timedelta(minutes=total_duration)
        else:
            arr_time = dep_time + timedelta(minutes=total_duration)

        deeplink_url = build_uber_deeplink(
            destination=requirement.destination,
            destination_coords=requirement.destination_coordinates,
        )

        evidence = MobilityEvidence(
            claim="Ride-hail on-demand transfer via Uber Universal Deep Link.",
            source="Uber Universal Link Specification",
            source_type=MobilitySourceType.APPROVED_PROVIDER_API,
            observed_at=datetime.now(UTC),
            confidence=0.80,
            relevant_provider="uber",
        )

        option = MobilityOption(
            id=f"uber-ride-{uuid4().hex[:8]}",
            provider_id="uber",
            provider_name="Uber",
            mode=TransportMode.RIDE_HAIL,
            origin=requirement.origin,
            destination=requirement.destination,
            departure_time=dep_time,
            arrival_time=arr_time,
            duration_minutes=total_duration,
            cost=None,  # Factual: dynamic fare requires live partner API
            cost_is_unknown=True,
            currency="ZAR",
            walking_duration_minutes=0,
            transfers=0,
            availability="available",
            live_status=MobilityLiveStatus.UNKNOWN,
            booking_capability=BookingCapability.DEEPLINK,
            booking_url=deeplink_url,
            source="Uber Mobile Deep Link",
            source_type=MobilitySourceType.APPROVED_PROVIDER_API,
            retrieved_at=datetime.now(UTC),
            confidence=0.80,
            evidence=[evidence],
            summary=f"Uber ride (~{total_duration} min drive, fare confirmed in app)",
        )
        return [option]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None
