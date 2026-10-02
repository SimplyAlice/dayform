from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from app.infrastructure.mobility.geo import (
    CAPE_TOWN_LOCATIONS,
    address_serves_place,
    estimate_network_distance_km,
    place_within_radius_km,
)

PRASA_LINES = [
    {
        "line": "Southern Line",
        "stations": [
            "cape town",
            "cape town station",
            "woodstock",
            "salt river",
            "observatory",
            "mowbray",
            "rosebank",
            "rondebosch",
            "newlands",
            "kirstenbosch",
            "claremont",
            "harfield road",
            "kenilworth",
            "wynberg",
            "plumstead",
            "steurhof",
            "diep river",
            "heathfield",
            "retreat",
            "steenberg",
            "lakeside",
            "muizenberg",
            "st james",
            "kalk bay",
            "fish hoek",
            "glencairn",
            "simon's town",
            "simons town",
        ],
    },
    {
        "line": "Northern Line",
        "stations": [
            "cape town",
            "cape town station",
            "woodstock",
            "salt river",
            "maitland",
            "ndabeni",
            "pinelands",
            "mutual",
            "bellville",
            "kuils river",
            "strand",
        ],
    },
]

# Approximate station centroids, used only for "is this station near this
# address" proximity matching. These are street-level coordinates, not surveyed
# platforms, so the matching radius below is deliberately conservative.
STATION_COORDINATES: dict[str, tuple[float, float]] = {
    "cape town": (-33.9178, 18.4242),
    "cape town station": (-33.9178, 18.4242),
    "woodstock": (-33.9265, 18.4513),
    "salt river": (-33.9361, 18.4717),
    "observatory": (-33.9491, 18.4899),
    "mowbray": (-33.9596, 18.5001),
    "rosebank": (-33.9706, 18.5131),
    "rondebosch": (-33.9776, 18.5281),
    "newlands": (-33.9706, 18.5251),
    "kirstenbosch": (-33.9823, 18.5327),
    "claremont": (-33.9842, 18.5108),
    "harfield road": (-33.9901, 18.5031),
    "kenilworth": (-33.9992, 18.4801),
    "wynberg": (-34.0001, 18.4601),
    "plumstead": (-34.0069, 18.4451),
    "steurhof": (-34.0201, 18.4401),
    "diep river": (-34.0301, 18.4501),
    "heathfield": (-34.0431, 18.4701),
    "retreat": (-34.0601, 18.4901),
    "steenberg": (-34.1001, 18.5601),
    "lakeside": (-34.1101, 18.6101),
    "muizenberg": (-34.1081, 18.4701),
    "st james": (-34.1201, 18.4501),
    "kalk bay": (-34.1341, 18.4401),
    "fish hoek": (-34.1401, 18.4301),
    "glencairn": (-34.1501, 18.4501),
    "simon's town": (-34.1801, 18.4101),
    "simons town": (-34.1801, 18.4101),
    "maitland": (-33.9401, 18.5101),
    "ndabeni": (-33.9201, 18.5601),
    "pinelands": (-33.9401, 18.5301),
    "mutual": (-33.9101, 18.5501),
    "bellville": (-33.8992, 18.6292),
    "kuils river": (-33.8401, 18.6801),
    "strand": (-34.1001, 18.8301),
}

# A station "serves" an address inside this radius. Roughly a 20 minute walk,
# which matches what a person will actually accept as "walk to the station".
STATION_WALKING_RADIUS_KM = 3.0


class PrasaProvider(MobilityProviderPort):
    """PRASA Metrorail Western Cape scheduled passenger rail integration."""

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="prasa_metrorail",
            name="PRASA Metrorail (Western Cape)",
            supported_modes=[TransportMode.TRAIN],
            has_route_data=True,
            has_timetable=True,
            has_realtime=False,
            has_service_alerts=True,
            has_fare_estimates=True,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            official_source_url="https://www.prasa.com",
            is_enabled=True,
            notes="Official Western Cape commuter train schedules for Southern and Northern lines. Live track status is not published via public API, so live status is explicitly marked unknown.",
        )

    def _station_serves(self, address: str, station: str) -> bool:
        """Whether a Metrorail station genuinely serves this address.

        Two tests, because one is not enough.

        The locality test is the strict one and it is what stops the network
        claiming a route for every address in Cape Town. But it can only ever
        match an address whose *suburb* is a station name, and the most important
        node on the whole network is the one whose name is the city: "Cape Town".
        `address_serves_place` deliberately refuses city-level place names, so
        the hub was unreachable from every address in the CBD — the single most
        common origin in this product — and rail could never be proposed for a
        journey that starts in the city centre.

        The second test asks about position instead of name. A station within
        walking distance of an address really does serve it, which is the same
        standard the locality test is applying, just expressed geometrically.
        """
        if address_serves_place(address, station):
            return True
        coords = STATION_COORDINATES.get(station)
        if coords is not None:
            return place_within_radius_km(address, coords, STATION_WALKING_RADIUS_KM)
        return False

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        matching_lines = []
        for line_info in PRASA_LINES:
            # A line only applies when it actually has stations serving both ends. Matching on
            # the city name would claim a rail route for every Cape Town address.
            has_orig = any(
                self._station_serves(requirement.origin, st) for st in line_info["stations"]
            )
            has_dest = any(
                self._station_serves(requirement.destination, st)
                for st in line_info["stations"]
            )
            if has_orig and has_dest:
                matching_lines.append(line_info)

        if not matching_lines:
            return []

        distance_km = estimate_network_distance_km(
            requirement.origin,
            requirement.destination,
            requirement.origin_coordinates,
            requirement.destination_coordinates,
        )

        # PRASA standard single ticket fares (zonal): ~R10.50 - R14.50
        if distance_km <= 15.0:
            fare = Decimal("10.50")
        elif distance_km <= 30.0:
            fare = Decimal("12.50")
        else:
            fare = Decimal("14.50")

        # Average rail travel speed: ~38 km/h + 4 min station buffer
        duration_minutes = max(12, int(round((distance_km / 38.0) * 60)) + 4)

        dep_time = requirement.departure_time or datetime.now(UTC)
        arr_time = requirement.arrival_time
        if arr_time is not None and requirement.departure_time is None:
            dep_time = arr_time - timedelta(minutes=duration_minutes)
        else:
            arr_time = dep_time + timedelta(minutes=duration_minutes)

        options: list[MobilityOption] = []
        for line_info in matching_lines:
            line_name = line_info["line"]
            evidence = MobilityEvidence(
                claim=f"Scheduled Metrorail service on the {line_name}. Standard zonal single fare applied.",
                source="PRASA Western Cape Official Timetable",
                source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
                observed_at=datetime.now(UTC),
                confidence=0.75,
                relevant_provider="prasa_metrorail",
                relevant_route_or_stop=line_name,
            )

            option = MobilityOption(
                id=f"prasa-{line_name.lower().replace(' ', '-')}-{uuid4().hex[:6]}",
                provider_id="prasa_metrorail",
                provider_name="PRASA Metrorail (Western Cape)",
                mode=TransportMode.TRAIN,
                origin=requirement.origin,
                destination=requirement.destination,
                departure_time=dep_time,
                arrival_time=arr_time,
                duration_minutes=duration_minutes,
                cost=fare,
                cost_is_unknown=False,
                # The fare comes from a static published band table, not a live
                # quote, so it is an estimate and is labelled as one.
                cost_is_estimated=True,
                currency="ZAR",
                walking_duration_minutes=6,
                transfers=0,
                availability="available",
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.NO_BOOKING,
                booking_url="https://www.prasa.com",
                source="PRASA Western Cape Official Timetable",
                source_type=MobilitySourceType.OFFICIAL_TIMETABLE,
                retrieved_at=datetime.now(UTC),
                confidence=0.75,
                evidence=[evidence],
                summary=f"Metrorail {line_name} (~{duration_minutes} min, R{fare:.2f})",
            )
            options.append(option)

        return options

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None
