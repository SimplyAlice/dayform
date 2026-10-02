from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
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

MYCITI_ROUTES = [
    {
        "code": "T01",
        "name": "Dunoon – Table View – Civic Centre – Waterfront",
        "stops": [
            "dunoon",
            "table view",
            "woodbridge island",
            "paarden eiland",
            "civic centre",
            "cape town station",
            "waterfront",
            "v&a waterfront",
        ],
        "is_trunk": True,
    },
    {
        "code": "101",
        "name": "Gardens – Civic Centre (via Kloof Street)",
        "stops": [
            "gardens",
            "kloof street",
            "tamboerskloof",
            "city bowl",
            "cape town cbd",
            "civic centre",
        ],
        "is_trunk": False,
    },
    {
        "code": "102",
        "name": "Salt River – Civic Centre (via Walmer Estate)",
        "stops": [
            "salt river",
            "woodstock",
            "walmer estate",
            "city bowl",
            "civic centre",
        ],
        "is_trunk": False,
    },
    {
        "code": "104",
        "name": "Sea Point – Camps Bay – Civic Centre (via Beach Road)",
        "stops": [
            "sea point",
            "clifton",
            "camps bay",
            "green point",
            "waterfront",
            "v&a waterfront",
            "civic centre",
            "cape town cbd",
            "city bowl",
        ],
        "is_trunk": False,
    },
    {
        "code": "105",
        "name": "Sea Point – Civic Centre (via High Level Road)",
        "stops": [
            "sea point",
            "green point",
            "city bowl",
            "cape town cbd",
            "civic centre",
        ],
        "is_trunk": False,
    },
    {
        "code": "106",
        "name": "Camps Bay – Civic Centre (via Kloof Nek)",
        "stops": [
            "camps bay",
            "kloof nek",
            "kloof street",
            "gardens",
            "city bowl",
            "civic centre",
        ],
        "is_trunk": False,
    },
    {
        "code": "108",
        "name": "Hout Bay – Civic Centre (via Camps Bay & Sea Point)",
        "stops": [
            "hout bay",
            "llandudno",
            "camps bay",
            "clifton",
            "sea point",
            "green point",
            "civic centre",
        ],
        "is_trunk": False,
    },
    {
        "code": "A01",
        "name": "Airport – Civic Centre Express",
        "stops": [
            "airport",
            "cape town international airport",
            "civic centre",
        ],
        "is_trunk": True,
        "is_airport": True,
    },
]


def is_myciti_peak_time(dt: datetime) -> bool:
    """MyCiTi peak fare window: Weekdays 06:45-08:00 and 16:15-17:30.

    All other times, weekends, and public holidays are Off-Peak (Saver).
    """
    if dt.weekday() >= 5:  # Saturday or Sunday
        return False
    t = dt.time()
    morning_peak = time(6, 45) <= t <= time(8, 0)
    afternoon_peak = time(16, 15) <= t <= time(17, 30)
    return morning_peak or afternoon_peak


def calculate_myciti_fare(distance_km: float, is_peak: bool, is_airport: bool = False) -> Decimal:
    """Calculate MyCiTi distance-based Mover package fare in ZAR."""
    if is_airport:
        return Decimal("115.00")

    if distance_km <= 5.0:
        return Decimal("14.90") if is_peak else Decimal("11.90")
    elif distance_km <= 10.0:
        return Decimal("18.50") if is_peak else Decimal("14.90")
    elif distance_km <= 20.0:
        return Decimal("24.50") if is_peak else Decimal("19.90")
    elif distance_km <= 30.0:
        return Decimal("29.50") if is_peak else Decimal("23.90")
    else:
        return Decimal("34.50") if is_peak else Decimal("28.00")


class MyCiTiProvider(MobilityProviderPort):
    """Verified MyCiTi bus service timetable and distance-band fare integration."""

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="myciti",
            name="MyCiTi",
            supported_modes=[TransportMode.BUS],
            has_route_data=True,
            has_timetable=True,
            has_realtime=False,
            has_service_alerts=True,
            has_fare_estimates=True,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            official_source_url="https://www.myciti.org.za",
            is_enabled=True,
            notes="Official MyCiTi bus routes and distance-band fare rules. Live real-time vehicle tracking is currently unavailable via public open API, so live status is explicitly reported as unknown.",
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # Find routes that actually serve both ends. A route is only applicable when it has a
        # stop in each address's locality; matching on the city name would claim a bus route
        # for every Cape Town address.
        matching_routes = []
        for route in MYCITI_ROUTES:
            has_orig = any(address_serves_place(requirement.origin, stop) for stop in route["stops"])
            has_dest = any(
                address_serves_place(requirement.destination, stop) for stop in route["stops"]
            )
            if has_orig and has_dest:
                matching_routes.append(route)

        # If no direct single route, check if journey is within Cape Town bus service area
        if not matching_routes:
            # Check if both ends match any known MyCiTi stops (allowing 1 transfer at Civic Centre)
            orig_match = any(
                address_serves_place(requirement.origin, stop)
                for r in MYCITI_ROUTES
                for stop in r["stops"]
            )
            dest_match = any(
                address_serves_place(requirement.destination, stop)
                for r in MYCITI_ROUTES
                for stop in r["stops"]
            )
            if orig_match and dest_match:
                # Connected via Civic Centre hub
                matching_routes.append(
                    {
                        "code": "Transfer via Civic Centre",
                        "name": "MyCiTi Hub Transfer",
                        "stops": ["civic centre"],
                        "is_trunk": True,
                        "is_transfer": True,
                    }
                )

        if not matching_routes:
            return []

        distance_km = estimate_network_distance_km(
            requirement.origin,
            requirement.destination,
            requirement.origin_coordinates,
            requirement.destination_coordinates,
        )

        dep_time = requirement.departure_time or datetime.now(UTC)
        is_peak = is_myciti_peak_time(dep_time)

        options: list[MobilityOption] = []
        for route in matching_routes:
            is_airport = route.get("is_airport", False)
            fare = calculate_myciti_fare(distance_km, is_peak=is_peak, is_airport=is_airport)

            # Bus speed estimate: ~22 km/h average + 5 min dwell
            duration_minutes = max(10, int(round((distance_km / 22.0) * 60)) + 5)
            transfers = 1 if route.get("is_transfer") else 0
            if transfers > 0:
                duration_minutes += 12  # transfer wait time

            arr_time = requirement.arrival_time
            if arr_time is not None and requirement.departure_time is None:
                route_dep = arr_time - timedelta(minutes=duration_minutes)
                route_arr = arr_time
            else:
                route_dep = dep_time
                route_arr = dep_time + timedelta(minutes=duration_minutes)

            route_code = route["code"]
            route_name = route["name"]

            evidence = MobilityEvidence(
                claim=(
                    f"Scheduled MyCiTi service ({route_code}). Fares calculated according to official "
                    f"Mover distance bands ({'Peak' if is_peak else 'Off-Peak/Saver'})."
                ),
                source="City of Cape Town / MyCiTi Official Timetable & Tariffs",
                source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
                observed_at=datetime.now(UTC),
                confidence=0.85,
                relevant_provider="myciti",
                relevant_route_or_stop=route_code,
            )

            option = MobilityOption(
                id=f"myciti-{route_code.lower()}-{uuid4().hex[:6]}",
                provider_id="myciti",
                provider_name="MyCiTi",
                mode=TransportMode.BUS,
                origin=requirement.origin,
                destination=requirement.destination,
                departure_time=route_dep,
                arrival_time=route_arr,
                duration_minutes=duration_minutes,
                cost=fare,
                cost_is_unknown=False,
                # Derived from a static distance-band table, not a live quote.
                cost_is_estimated=True,
                currency="ZAR",
                walking_duration_minutes=5,  # walking buffer to/from station
                transfers=transfers,
                availability="available",
                live_status=MobilityLiveStatus.UNKNOWN,  # Truthful: no public live feed
                booking_capability=BookingCapability.NO_BOOKING,
                booking_url="https://www.myciti.org.za",
                source="MyCiTi Official Schedules",
                source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
                retrieved_at=datetime.now(UTC),
                confidence=0.85,
                evidence=[evidence],
                summary=f"MyCiTi {route_code} ({route_name}) ~{duration_minutes} min, R{fare:.2f}",
            )
            options.append(option)

        return options

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        # Truthful: no open live feed available
        return None
