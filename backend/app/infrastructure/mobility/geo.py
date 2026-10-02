from __future__ import annotations

import math
import re

# Reference Cape Town geographic locations (latitude, longitude)
CAPE_TOWN_LOCATIONS: dict[str, tuple[float, float]] = {
    "civic centre": (-33.9189, 18.4233),
    "cape town cbd": (-33.9249, 18.4241),
    "city bowl": (-33.9249, 18.4241),
    "cape town station": (-33.9219, 18.4247),
    "v&a waterfront": (-33.9036, 18.4205),
    "waterfront": (-33.9036, 18.4205),
    "gardens": (-33.9350, 18.4100),
    "kloof street": (-33.9300, 18.4110),
    "tamboerskloof": (-33.9280, 18.4050),
    "sea point": (-33.9180, 18.3880),
    "green point": (-33.9070, 18.4060),
    "camps bay": (-33.9510, 18.3780),
    "clifton": (-33.9380, 18.3750),
    "hout bay": (-34.0450, 18.3580),
    "woodstock": (-33.9300, 18.4480),
    "salt river": (-33.9330, 18.4610),
    "observatory": (-33.9370, 18.4720),
    "mowbray": (-33.9480, 18.4730),
    "rosebank": (-33.9570, 18.4780),
    "rondebosch": (-33.9630, 18.4830),
    "newlands": (-33.9740, 18.4590),
    "kirstenbosch": (-33.9853, 18.4437),
    "kirstenbosch national botanical garden": (-33.9882, 18.4330),
    "claremont": (-33.9810, 18.4660),
    "wynberg": (-34.0040, 18.4660),
    "kalk bay": (-34.1270, 18.4480),
    "muizenberg": (-34.1080, 18.4710),
    "fish hoek": (-34.1350, 18.4320),
    "simon's town": (-34.1930, 18.4320),
    "simons town": (-34.1930, 18.4320),
    "table view": (-33.8240, 18.4910),
    "dunoon": (-33.8050, 18.5370),
    "bellville": (-33.8940, 18.6290),
    "cape town international airport": (-33.9715, 18.6021),
    "airport": (-33.9715, 18.6021),
}


CITY_TOKENS = frozenset(
    {
        "cape town",
        "south africa",
        "western cape",
        "wc",
        "ct metro",
        "cape town metro",
        "city of cape town",
    }
)

# Rough operating envelope for the Cape Town metropolitan area, used to stop
# providers claiming service at addresses they do not reach. Centred on the
# city bowl at 30km, which keeps Bellville (13km) and Simon's Town (28.8km)
# inside the metro and puts Atlantis (37.3km), Somerset West (36km) and
# Stellenbosch (33.2km) outside it. That is roughly where metered ride-hail
# coverage actually stops.
METRO_CENTROID: tuple[float, float] = (-33.9400, 18.5000)
METRO_SERVICE_RADIUS_KM = 30.0

# Towns near the metro that ride-hail and transit do not usefully reach. Without
# these the service-area test cannot tell "Somerset West" from a Cape Town suburb,
# because neither resolves in CAPE_TOWN_LOCATIONS, and it has to default to
# "in area" — which is precisely the case the gate exists to catch. Real
# coordinates let it answer with evidence instead of a guess.
OUTER_TOWNS: dict[str, tuple[float, float]] = {
    "somerset west": (-34.0833, 18.8500),
    "belgravia": (-34.0364, 18.9478),
    "paarl": (-33.7333, 18.9667),
    "stellenbosch": (-33.9361, 18.8600),
    "franschhoek": (-33.7100, 19.0400),
    "stellenbosch university": (-33.9361, 18.8600),
    "atlantis": (-33.6667, 18.7333),
    "pocahontas": (-33.7167, 18.7000),
    "phoebedale": (-33.7500, 18.7400),
    "koeberg": (-33.6900, 18.6300),
    "west coast": (-33.2500, 18.3000),
    "durbanville": (-33.8333, 18.6333),
    "philippi": (-34.0333, 18.5333),
    "hout bay": (-34.0333, 18.3500),
    "lanzerac": (-34.0500, 18.3000),
    "wilderness": (-33.9833, 22.8833),
    "george": (-33.9600, 22.4600),
    "mossel bay": (-34.1833, 22.1333),
    "oudtshoorn": (-33.6000, 22.2700),
    "hermanus": (-34.4167, 19.2500),
    "calvinia": (-31.6333, 18.6333),
    "saldanha": (-32.9833, 17.9667),
    "ceres": (-33.3667, 19.3000),
    "cape argullas": (-32.3000, 18.3000),
}


def address_components(address: str) -> list[str]:
    """Comma components of an address with city/country components removed."""
    parts = [p.strip(" .").lower() for p in address.split(",")]
    parts = [p for p in parts if p]
    specific = [p for p in parts if p not in CITY_TOKENS]
    return specific or parts


def resolve_locality(address: str) -> str:
    """The specific locality of a Cape Town address, e.g. 'camps bay' or 'observatory'.

    City components are dropped so that '270 Victoria Rd, Camps Bay, Cape Town' resolves to
    'camps bay' rather than matching the 'Cape Town' rail station on every address. A leading
    venue/building component is also dropped when a street and suburb follow it, so
    'Cape Town Jazz Club, 1 Loop Street, Foreshore' resolves to 'foreshore'.
    """
    parts = address_components(address)
    if not parts:
        return ""
    if len(parts) >= 3:
        parts = parts[1:]
    return parts[-1]


def _place_matches_text(text: str, place: str) -> bool:
    if place in text:
        return True
    words = text.replace("-", " ").replace(",", " ").split()
    return any(word.strip(".") == place for word in words)


def address_serves_place(address: str, place: str) -> bool:
    """Whether a network place (station, bus stop or hub) genuinely serves this address.

    A provider must not claim a route merely because the city name appears in the address, so
    city-level place names never match and only the address's specific locality is considered.
    """
    place = place.strip(" .").lower()
    if not place or place in CITY_TOKENS:
        return False
    locality = resolve_locality(address)
    if not locality:
        return False
    return _place_matches_text(locality, place)


def is_in_cape_town_service_area(address: str) -> bool:
    """Whether an address lies inside the Cape Town metropolitan operating area.

    Ride-hail providers do not publish a geographic boundary we can verify, but
    that is not a reason to claim they operate everywhere. Without a gate they
    answer *every* origin/destination pair, so a journey to a town they do not
    serve still comes back "available" — and because ride-hail never declines,
    it becomes the only surviving option whenever a structured provider declines.
    That is how the planner came to show Uber alone.

    Resolvable addresses are judged by position. Addresses we cannot place at all
    are treated as in-area on purpose: an unrecognised place name is missing
    information, not proof of absence, and guessing "unavailable" would hide a
    working provider from users in suburbs the tables have not caught up with.
    """
    coords = find_coordinates(address) or _find_outer_town_coordinates(address)
    if coords is None:
        return True
    return haversine_distance_km(coords, METRO_CENTROID) <= METRO_SERVICE_RADIUS_KM


def _find_outer_town_coordinates(address: str) -> tuple[float, float] | None:
    """Coordinates for a known town outside the metro, matched on its locality."""
    locality = resolve_locality(address)
    candidates = [locality] if locality else []
    candidates.extend(p.strip(" .").lower() for p in address.split(",") if p.strip(" ."))
    for candidate in candidates:
        if candidate in OUTER_TOWNS:
            return OUTER_TOWNS[candidate]
    words = address.replace("-", " ").replace(",", " ").lower().split()
    for candidate in candidates:
        if any(candidate in word for word in words) and candidate in OUTER_TOWNS:
            return OUTER_TOWNS[candidate]
    for name, coords in sorted(OUTER_TOWNS.items(), key=lambda kv: -len(kv[0])):
        if _place_matches_text(address.lower(), name):
            return coords
    return None


def find_coordinates(location_name: str) -> tuple[float, float] | None:
    """Resolve known coordinates for a Cape Town location name."""
    clean = location_name.strip().lower()
    # Direct match
    if clean in CAPE_TOWN_LOCATIONS:
        return CAPE_TOWN_LOCATIONS[clean]
    # Locality match, most specific name first so 'sea point' beats shorter prefixes.
    candidates = sorted(CAPE_TOWN_LOCATIONS.items(), key=lambda kv: -len(kv[0]))
    for name, coords in candidates:
        if _place_matches_text(clean, name) or address_serves_place(clean, name):
            return coords
    return None


def place_within_radius_km(
    address: str, place_coordinates: tuple[float, float], radius_km: float
) -> bool:
    """Whether an address is within `radius_km` of a known point.

    Locality matching is the right test for a suburb, but it cannot express
    "this address is two streets from the station". Some of the most important
    transport nodes in the city are named after the city itself, so their
    locality test can never pass by construction; position is the honest way to
    ask whether a station is actually reachable on foot from an address.
    """
    coords = find_coordinates(address)
    if coords is None:
        return False
    return haversine_distance_km(coords, place_coordinates) <= radius_km


def haversine_distance_km(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    radius_earth_km = 6371.0

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_earth_km * c


def estimate_network_distance_km(
    origin: str,
    destination: str,
    origin_coords: tuple[float, float] | None = None,
    destination_coords: tuple[float, float] | None = None,
) -> float:
    """Estimate ground street distance between origin and destination in km."""
    coords1 = origin_coords or find_coordinates(origin)
    coords2 = destination_coords or find_coordinates(destination)

    if coords1 and coords2:
        direct_km = haversine_distance_km(coords1, coords2)
        # Urban circuity factor: real road networks are ~1.25 to 1.35x crow-flies distance
        return max(0.5, round(direct_km * 1.3, 1))

    # Fallback heuristic if unknown: conservative default 5.0 km
    return 5.0
