"""Geographic intent as a first-class planning constraint.

A user who says "in Southern Suburbs" has stated where the day must happen. That
is a planning constraint, not descriptive text: the planner may not substitute
"somewhere else in Cape Town" and merely mention the area afterwards.

Two rules shape this module.

First, "Cape Town" is not a constraint. A city-level request leaves every venue
in the city eligible, which is what `resolve_area_scope` returning `None` means.

Second, a request for a group of suburbs is answered by the group's own
geography, not by substring matching. Every catalog venue carries
`location="Cape Town"`, so a venue is placed by its address locality and its
coordinates. "270 Victoria Rd, Camps Bay, Cape Town" is in Camps Bay and must
not satisfy a request for the Southern Suburbs just because both are in the same
city.

Unknown is kept distinct from outside. A venue with no address and no
coordinates cannot be shown to be in the requested area, and it is not shown to
be outside it either, so it is reported as `UNKNOWN` rather than guessed either
way. Callers decide what an unknown is worth; this module never invents a match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class AreaStatus(str, Enum):
    """Whether a candidate can be shown to satisfy a requested area."""

    MATCH = "match"
    OUTSIDE = "outside"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AreaVerdict:
    status: AreaStatus
    reason: str


@dataclass(frozen=True)
class AreaScope:
    """A named area, resolved from something the user actually said.

    `localities` are the locality names that belong to the area and are matched
    against a candidate's address. `anchor_localities` names the localities whose
    coordinates are looked up in the existing Cape Town locality table, so a
    venue whose address is not specific enough to name its suburb can still be
    placed by where it physically is. `radius_km` bounds that placement.
    """

    label: str
    localities: tuple[str, ...]
    anchor_localities: tuple[str, ...] = ()
    radius_km: float = 0.0


# Requests that name the whole city. They place no constraint on a venue, so no
# scope is produced and candidate location is left unconstrained.
CITY_LEVEL = frozenset(
    {"cape town", "town", "around town", "in town", "city", "ct", "the city", "s metro"}
)

# Regions the product has to reason about as a group, because a user asking for
# one means the whole group and not one suburb inside it. This is a definition of
# the region, not a catalogue of Cape Town: any other area a user names is
# handled by the single-locality path below and needs no entry here.
NAMED_AREAS: dict[str, AreaScope] = {
    "southern suburbs": AreaScope(
        label="Southern Suburbs",
        localities=(
            "bishopscourt",
            "claremont",
            "constantia",
            "newlands",
            "rosebank",
            "rondebosch",
            "wynberg",
            "kirstenbosch",
        ),
        anchor_localities=("claremont", "newlands", "rondebosch", "rosebank", "wynberg"),
        radius_km=3.5,
    ),
    "city bowl": AreaScope(
        label="City Bowl",
        localities=(
            "city bowl",
            "cbd",
            "cape town cbd",
            "gardens",
            "tamboerskloof",
            "bo-kaap",
            "bo kaap",
            "de waterkant",
            "foreshore",
            "oranjezicht",
            "higgovale",
            "vredehoek",
            "kloof street",
            "bree street",
            "long street",
        ),
        anchor_localities=("city bowl", "cape town cbd", "gardens", "tamboerskloof"),
        radius_km=3.0,
    ),
    "atlantic seaboard": AreaScope(
        label="Atlantic Seaboard",
        localities=(
            "atlantic seaboard",
            "sea point",
            "green point",
            "camps bay",
            "clifton",
            "mouille point",
            "bantry bay",
            "fresnaye",
            "bakoven",
        ),
        anchor_localities=("sea point", "green point", "camps bay", "clifton"),
        radius_km=4.5,
    ),
    "kirstenbosch": AreaScope(
        label="Kirstenbosch",
        localities=(
            "kirstenbosch",
        ),
        anchor_localities=("kirstenbosch", "newlands"),
        radius_km=2.0,
    ),
}

LANDMARK_AREAS = frozenset(
    {
        "kirstenbosch",
        "table mountain",
        "v&a waterfront",
        "waterfront",
        "signal hill",
        "lion's head",
        "cape point",
    }
)

_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _words(value: str) -> list[str]:
    return [w for w in _NON_WORD.split(value.strip().lower()) if w]


def resolve_area_scope(area: str | None) -> AreaScope | None:
    """The geographic constraint a stated area imposes, if it imposes one.

    `None` means the user did not restrict the day geographically, either
    because they said nothing or because they named the city as a whole. A
    single named place becomes a scope of that one locality, so no catalogue
    entry is needed for it to be enforced.
    """
    if area is None:
        return None
    clean = _ARTICLE.sub("", area.strip().casefold()).strip(" .,")
    if not clean or clean in CITY_LEVEL:
        return None
    named = NAMED_AREAS.get(clean)
    if named is not None:
        return named
    if len(_words(clean)) == 0:
        return None
    return AreaScope(label=area.strip(), localities=(clean,))


def _locality_in_scope(locality: str, scope: AreaScope) -> bool:
    """Whether an address locality names a place inside the scope.

    Matched as a run of whole words rather than a raw substring, so "v&a
    waterfront" contains the Waterfront and "constantia nek" belongs to
    Constantia, while a suburb that merely shares a fragment with another
    ("Kloof Street" asked for as "Street") is not mistaken for a match.
    """
    words = _words(locality)
    if not words:
        return False
    for candidate in scope.localities:
        target = _words(candidate)
        if not target or len(target) > len(words):
            continue
        if any(
            words[i : i + len(target)] == target for i in range(len(words) - len(target) + 1)
        ):
            return True
    return False


def _anchor_distances_km(
    scope: AreaScope, latitude: float, longitude: float
) -> list[float]:
    """Distances from a point to each of the area's anchors, nearest first."""
    from app.infrastructure.mobility.geo import CAPE_TOWN_LOCATIONS, haversine_distance_km

    point = (latitude, longitude)
    distances = [
        haversine_distance_km(point, coords)
        for name in scope.anchor_localities
        if (coords := CAPE_TOWN_LOCATIONS.get(name)) is not None
    ]
    return sorted(distances)


def classify_in_area(
    scope: AreaScope | None,
    address: str | None = None,
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    name: str | None = None,
) -> AreaVerdict:
    """Place a candidate inside or outside a requested area, from its own data."""
    if scope is None:
        return AreaVerdict(AreaStatus.MATCH, "No specific area was requested")

    # Name match first: only for landmark destinations (e.g. "Kirstenbosch", "Table Mountain")
    # A standard suburb name (like "Gardens") must not match any venue with the word in its name (like "Arderne Gardens" in Claremont).
    is_landmark_scope = (
        scope.label.casefold() in LANDMARK_AREAS
        or any(loc in LANDMARK_AREAS for loc in scope.localities)
    )
    if name and is_landmark_scope:
        name_words = _words(name)
        for loc in scope.localities:
            target = _words(loc)
            if target and any(
                name_words[i : i + len(target)] == target
                for i in range(len(name_words) - len(target) + 1)
            ):
                return AreaVerdict(
                    AreaStatus.MATCH, f"'{name}' matches requested destination '{scope.label}'"
                )

    # Locality first: it is the venue's own statement about where it is.
    from app.infrastructure.mobility.geo import resolve_locality

    locality = ""
    for raw in (address, location):
        if raw:
            locality = resolve_locality(raw)
            if locality:
                break

    if locality:
        from app.infrastructure.mobility.geo import CAPE_TOWN_LOCATIONS

        if _locality_in_scope(locality, scope):
            return AreaVerdict(
                AreaStatus.MATCH, f"Located in {locality}, which is in the {scope.label}"
            )
        if locality in CAPE_TOWN_LOCATIONS:
            return AreaVerdict(
                AreaStatus.OUTSIDE,
                f"Located in {locality}, which is not in the {scope.label}",
            )

    # Then coordinates, for a venue whose address does not name its suburb.
    if latitude is not None and longitude is not None and scope.radius_km > 0:
        distances = _anchor_distances_km(scope, latitude, longitude)
        if distances:
            nearest = distances[0]
            if nearest <= scope.radius_km:
                return AreaVerdict(
                    AreaStatus.MATCH,
                    f"About {nearest:.1f} km inside the {scope.label}, near {locality or 'the area'}",
                )
            return AreaVerdict(
                AreaStatus.OUTSIDE,
                f"About {nearest:.1f} km outside the {scope.label}",
            )

    if not locality and latitude is None:
        return AreaVerdict(
            AreaStatus.UNKNOWN,
            f"Could not confirm this is in the {scope.label} from the information available",
        )

    return AreaVerdict(
        AreaStatus.OUTSIDE,
        f"Located in {locality}, which is not in the {scope.label}",
    )
