"""Intent requirements: what the user actually asked for, kept as checkable facts.

The understanding layer used to flatten a request into broad categories and a
single list of vibes, so "local culture, historic streets, and craft food
markets" became just "culture" and nothing downstream could tell whether the
historic streets or the market had actually been included.

This module introduces three distinct concepts and keeps them separate:

* `EXPERIENCE` — a thing the user asked to do or see (culture, historic
  streets, a craft food market).
* `VIBE` — a quality of the day rather than an activity (pretty, intimate,
  relaxed).
* `PREFERENCE` — a soft constraint on how the day is shaped (outdoor,
  family-friendly, vegetarian).

Every requirement carries the terms that would *evidence* it. Coverage is only
ever claimed when a stop's real, retrieved text actually contains one of those
terms, so a requirement can never be marked satisfied by a broad category
alone, and nothing is ever asserted about a venue that its own data does not
support.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.domain.entities.planning.information import InformationCategory


class RequirementKind(str, Enum):
    """What sort of thing the user asked for."""

    EXPERIENCE = "experience"
    VIBE = "vibe"
    PREFERENCE = "preference"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    NOT_COVERED = "not_covered"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class IntentRequirement:
    """A distinct thing the user asked for, plus the evidence that would prove it.

    `evidence_terms` are matched against text Dayform actually holds about a
    candidate. A requirement with no matching term is reported as uncovered; it
    is never assumed from the candidate's category.
    """

    slug: str
    label: str
    kind: RequirementKind
    evidence_terms: tuple[str, ...]
    # Only used to corroborate, never to establish coverage on its own.
    related_categories: tuple[InformationCategory, ...] = ()

    def __post_init__(self) -> None:
        if not self.slug.strip():
            raise ValueError("Requirement slug cannot be empty.")
        if not self.label.strip():
            raise ValueError("Requirement label cannot be empty.")
        if self.kind is not RequirementKind.EXPERIENCE and not self.evidence_terms:
            raise ValueError(f"Requirement '{self.slug}' must declare its evidence terms.")


@dataclass(frozen=True)
class CandidateEvidence:
    """The verified text Dayform actually holds about a candidate.

    Everything here comes from the information provider. Fields may be absent;
    an absent field simply cannot evidence anything.
    """

    name: str = ""
    category: InformationCategory | None = None
    description: str = ""
    address: str = ""
    location: str = ""
    metadata: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_candidate(cls, candidate: object) -> CandidateEvidence:
        """Build evidence from a decision candidate without inventing fields."""
        metadata = getattr(candidate, "metadata", None) or {}
        return cls(
            name=getattr(candidate, "name", "") or "",
            category=getattr(candidate, "category", None),
            description=getattr(candidate, "description", "") or "",
            address=getattr(candidate, "address", None) or "",
            location=getattr(candidate, "location", None) or "",
            metadata=tuple(sorted((str(k), str(v)) for k, v in dict(metadata).items())),
        )

    def searchable_fields(self) -> tuple[tuple[str, str], ...]:
        """The field-level text evidence may be drawn from, with field names."""
        fields: list[tuple[str, str]] = [
            ("name", self.name),
            ("description", self.description),
            ("address", self.address),
            ("location", self.location),
        ]
        fields.extend((f"metadata.{key}", value) for key, value in self.metadata)
        return tuple((name, value) for name, value in fields if value and value.strip())


@dataclass(frozen=True)
class RequirementMatch:
    """Evidence that one candidate supports one requirement."""

    stop_name: str
    field: str
    term: str


@dataclass(frozen=True)
class RequirementCoverage:
    """Whether the plan as a whole represents one requirement."""

    requirement: IntentRequirement
    matches: tuple[RequirementMatch, ...]

    @property
    def is_covered(self) -> bool:
        return bool(self.matches)

    @property
    def status(self) -> CoverageStatus:
        return CoverageStatus.COVERED if self.matches else CoverageStatus.NOT_COVERED

    @property
    def supporting_stops(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(match.stop_name for match in self.matches))


@dataclass(frozen=True)
class IntentCoverage:
    """Coverage of every requirement the user stated, over the final plan."""

    items: tuple[RequirementCoverage, ...]

    @property
    def experience_items(self) -> tuple[RequirementCoverage, ...]:
        return tuple(
            item for item in self.items if item.requirement.kind is RequirementKind.EXPERIENCE
        )

    @property
    def status(self) -> CoverageStatus:
        """Overall status of the *experiences* the user explicitly asked for."""
        experiences = self.experience_items
        if not experiences:
            return CoverageStatus.NOT_APPLICABLE
        covered = sum(1 for item in experiences if item.is_covered)
        if covered == len(experiences):
            return CoverageStatus.COVERED
        if covered == 0:
            return CoverageStatus.NOT_COVERED
        return CoverageStatus.PARTIAL

    @property
    def is_fully_covered(self) -> bool:
        return self.status is CoverageStatus.COVERED

    @property
    def uncovered(self) -> tuple[RequirementCoverage, ...]:
        return tuple(item for item in self.items if not item.is_covered)

    def count(self) -> int:
        return len(self.items)


# The taxonomy of things Dayform knows how to look for. Each entry pairs a
# user-facing label with the words that would evidence it in a candidate's own
# data. Terms are deliberately concrete so a match means something.
REQUIREMENT_TAXONOMY: tuple[IntentRequirement, ...] = (
    IntentRequirement(
        slug="meal",
        label="Something to eat",
        kind=RequirementKind.EXPERIENCE,
        # Words a venue actually uses to describe eating, taken from the catalog's
        # own descriptions. A plan of two gardens and no lunch must not be able to
        # claim the user asked for lunch and got it.
        evidence_terms=(
            "restaurant",
            "cafe",
            "café",
            "coffee",
            "espresso",
            "taverna",
            "brasserie",
            "bistro",
            "trattoria",
            "meze",
            "tapas",
            "fine dining",
            "lunch",
            "dinner",
            "brunch",
            "breakfast",
            "street food",
            "food hall",
            "seafood",
            "pastries",
            "cuisine",
            "tasting menu",
        ),
        related_categories=(InformationCategory.FOOD,),
    ),
    IntentRequirement(
        slug="local_culture",
        label="Local culture",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "local culture",
            "culture",
            "cultural",
            "heritage",
            "artist",
            "craft",
            "community",
            "tradition",
        ),
        related_categories=(InformationCategory.CULTURE,),
    ),
    IntentRequirement(
        slug="museum",
        label="A museum",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=("museum",),
        related_categories=(InformationCategory.CULTURE,),
    ),
    IntentRequirement(
        slug="historic_streets",
        label="Historic streets",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "historic",
            "historical",
            "heritage",
            "old town",
            "old cape town",
            "colonial",
            "victorian",
            "bo-kaap",
            "bo kaap",
            "street art",
            "cobbled",
            "architecture",
            "national monument",
            "old building",
        ),
        related_categories=(InformationCategory.CULTURE,),
    ),
    IntentRequirement(
        slug="craft_food_market",
        label="Craft & food market",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "craft market",
            "food market",
            "farmers market",
            "farmers' market",
            "food hall",
            "market",
            "stalls",
            "bazaar",
            "artisan",
            "handmade",
        ),
        related_categories=(InformationCategory.SHOPPING, InformationCategory.FOOD),
    ),
    IntentRequirement(
        slug="local_market",
        label="Local market",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=("market", "stalls", "bazaar", "fresh produce", "food hall"),
        related_categories=(InformationCategory.SHOPPING,),
    ),
    IntentRequirement(
        slug="live_music",
        label="Live music",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "live music",
            "live jazz",
            "live band",
            "jazz",
            "concert",
            "music venue",
            "musician",
            "sings",
        ),
        related_categories=(InformationCategory.ENTERTAINMENT,),
    ),
    IntentRequirement(
        slug="scenic_views",
        label="Scenic views",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "scenic",
            "viewpoint",
            "panoramic",
            "mountain view",
            "sea view",
            "lookout",
            "viewpoint",
            "ocean view",
        ),
        related_categories=(InformationCategory.NATURE,),
    ),
    IntentRequirement(
        slug="beach",
        label="Beach",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=("beach", "seaside", "ocean", "coastline", "shore", "bay"),
        related_categories=(InformationCategory.NATURE,),
    ),
    IntentRequirement(
        slug="art",
        label="Art",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=("art", "gallery", "exhibition", "art district", "artist"),
        related_categories=(InformationCategory.CULTURE,),
    ),
    IntentRequirement(
        slug="shopping",
        label="Shopping",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=("shop", "shopping", "boutique", "retail", "mall", "curio", "vintage", "thrift", "antique", "store"),
        related_categories=(InformationCategory.SHOPPING,),
    ),
    IntentRequirement(
        slug="painting",
        label="Painting & creative outdoors",
        kind=RequirementKind.EXPERIENCE,
        evidence_terms=(
            "paint",
            "painting",
            "easel",
            "art",
            "sketch",
            "sketching",
            "plein air",
            "scenic",
            "view",
            "garden",
            "canvas",
            "landscape",
            "outdoors",
            "nature",
        ),
        related_categories=(InformationCategory.NATURE, InformationCategory.CULTURE),
    ),
    IntentRequirement(
        slug="quiet_focus",
        label="A quiet place to read or focus",
        kind=RequirementKind.EXPERIENCE,
        # Words a venue would actually use to describe itself. A candidate's
        # category alone never satisfies this: a restaurant is not a quiet place
        # to read, and a garden is not a study. This stays uncovered against any
        # catalog venue that does not speak of reading, study or quiet space.
        evidence_terms=(
            "reading",
            "read",
            "book",
            "books",
            "library",
            "bookshop",
            "bookstore",
            "study",
            "studying",
            "study space",
            "study room",
            "reading room",
            "nook",
            "alcove",
            "quiet",
            "peaceful",
            "secluded",
            "hushed",
            "silent",
            "desk",
            "workstation",
            "workspace",
            "study table",
        ),
        # Intentionally no related category: quiet-focus activity has no catalog
        # category, so it is never able to substitute one. Asking for a place to
        # read must not be satisfied by proposing lunch, a garden, or a museum.
        related_categories=(),
    ),
    IntentRequirement(
        slug="relaxed",
        label="Relaxed pace",
        kind=RequirementKind.VIBE,
        evidence_terms=("relaxed", "laid back", "laid-back", "unhurried", "quiet", "calm"),
    ),
    IntentRequirement(
        slug="intimate",
        label="Intimate",
        kind=RequirementKind.VIBE,
        evidence_terms=("intimate", "cosy", "cozy", "small group", "hidden gem"),
    ),
    IntentRequirement(
        slug="atmospheric",
        label="Atmospheric",
        kind=RequirementKind.VIBE,
        evidence_terms=("atmospheric", "charming", "character", "vintage", "rustic"),
    ),
    IntentRequirement(
        slug="romantic",
        label="Romantic",
        kind=RequirementKind.VIBE,
        evidence_terms=("romantic", "candlelit", "candle lit", "intimate dinner"),
    ),
    IntentRequirement(
        slug="pretty",
        label="Pretty",
        kind=RequirementKind.VIBE,
        evidence_terms=("pretty", "beautiful", "photogenic", "instagrammable", "scenic"),
    ),
    IntentRequirement(
        slug="outdoor",
        label="Outdoor",
        kind=RequirementKind.PREFERENCE,
        evidence_terms=("outdoor", "outdoors", "garden", "patio", "terrace", "open air"),
        related_categories=(InformationCategory.NATURE,),
    ),
    IntentRequirement(
        slug="family_friendly",
        label="Family-friendly",
        kind=RequirementKind.PREFERENCE,
        evidence_terms=("family friendly", "family-friendly", "kids", "children", "playground"),
    ),
    IntentRequirement(
        slug="vegetarian",
        label="Vegetarian",
        kind=RequirementKind.PREFERENCE,
        evidence_terms=("vegetarian", "vegan", "plant based", "plant-based"),
    ),
)

_BY_SLUG: dict[str, IntentRequirement] = {req.slug: req for req in REQUIREMENT_TAXONOMY}

# The words a user must actually use for a requirement to be recorded. These are
# deliberately the user's own phrasing, not the evidence terms: the two answer
# different questions ("did they ask for it?" vs "does a venue prove it?").
REQUIREMENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    # An explicit meal word always means the user wants to eat. "eat" and "food"
    # are deliberately not in this list: "food market" is a market, not a lunch.
    "meal": (
        r"\blunch\b",
        r"\bdinner\b",
        r"\bbreakfast\b",
        r"\bbrunch\b",
        r"\bmeals?\b",
        r"\brestaurants?\b",
        r"\bcaf[eé]\b",
        r"\bcoffee\b",
        r"\bespresso\b",
        r"\bdining\b",
    ),
    "local_culture": (
        r"\blocal culture\b",
        r"\bculture\b",
        r"\bcultural\b",
        r"\bheritage\b",
        r"\bcommunity culture\b",
    ),
    "museum": (
        r"\bmuseums?\b",
    ),
    "historic_streets": (
        r"\bhistoric\b",
        r"\bhistorical\b",
        r"\bheritage\b",
        r"\bold town\b",
        r"\bcolonial\b",
        r"\bbo[- ]?kaap\b",
        r"\bstreet art\b",
        r"\barchitecture\b",
        r"\bcobbled\b",
    ),
    "craft_food_market": (
        r"\bcraft\b",
        r"\bartisan\b",
        r"\bhandmade\b",
        r"\bfood market\b",
        r"\bcraft market\b",
        r"\bfarmers'? market\b",
        r"\bmarket\b",
        r"\bmarkets\b",
        r"\bfood hall\b",
    ),
    "local_market": (
        r"\bmarket\b",
        r"\bmarkets\b",
        r"\bbazaar\b",
        r"\bfood hall\b",
    ),
    "live_music": (
        r"\blive music\b",
        r"\blive band\b",
        r"\blive jazz\b",
        r"\bjazz\b",
        r"\bconcert\b",
        r"\bmusic\b",
    ),
    "scenic_views": (
        r"\bscenic\b",
        r"\bviews?\b",
        r"\bpanoramic\b",
        r"\blookout\b",
        r"\bviewpoint\b",
    ),
    "beach": (
        r"\bbeach\b",
        r"\bseaside\b",
        r"\bocean\b",
        r"\bcoastline\b",
        r"\bshore\b",
    ),
    "art": (
        r"\bart\b",
        r"\bart gallery\b",
        r"\bart galleries\b",
        r"\bgallery\b",
        r"\bgalleries\b",
        r"\bexhibition\b",
    ),
    "shopping": (
        r"\bshopping\b",
        r"\bshops?\b",
        r"\bboutique\b",
        r"\bmall\b",
        r"\bretail\b",
        r"\bvintage\s+shops?\b",
        r"\bbrowse\s+.*shops?\b",
        r"\bvintage\b",
    ),
    "painting": (
        r"\bpaint\b",
        r"\bpainting\b",
        r"\bsketch\b",
        r"\bsketching\b",
        r"\bplein air\b",
    ),
    "quiet_focus": (
        r"\bread\b",
        r"\breading\b",
        r"\bstudy(?:ing)?\b",
        r"\bbooks?\b",
        r"\blibrar(?:y|ies)\b",
        r"\bbookshop\b",
        r"\bbookstore\b",
        r"\b(?:place|somewhere)\s+to\s+work\b",
        r"\bwork\s+(?:for\s+)?(?:\d+\s+)?(?:hours?|mins?|minutes?)\b",
        r"\bworking(?:\s+quietly)?\b",
        r"\bwork\s+quietly\b",
        r"\bstudy\s+quietly\b",
        r"\bworkspace\b",
        r"\bco-?working\b",
        r"\bspend.*working\b",
    ),
    "relaxed": (
        r"\brelaxed\b",
        r"\blaid[ -]?back\b",
        r"\bunhurried\b",
        r"\beasygoing\b",
        r"\bchill\b",
        r"\bquiet\b",
    ),
    "intimate": (
        r"\bintimate\b",
        r"\bcosy\b",
        r"\bcozy\b",
        r"\bhidden gem\b",
    ),
    "atmospheric": (
        r"\batmospheric\b",
        r"\bcharming\b",
        r"\bvintage(?!\s+shops?)\b",
        r"\brustic\b",
    ),
    "romantic": (
        r"\bromantic\b",
        r"\bcandlelit\b",
        r"\bintimate dinner\b",
    ),
    "pretty": (
        r"\bpretty\b",
        r"\bbeautiful\b",
        r"\bphotogenic\b",
        r"\binstagrammable\b",
    ),
    "outdoor": (
        r"\boutdoors?\b",
        r"\bopen air\b",
        r"\bin the sun\b",
    ),
    "family_friendly": (
        r"\bfamily[ -]friendly\b",
        r"\bwith kids\b",
        r"\bwith children\b",
    ),
    "vegetarian": (
        r"\bvegetarian\b",
        r"\bvegan\b",
        r"\bplant[ -]based\b",
    ),
}


def requirement_by_slug(slug: str) -> IntentRequirement | None:
    return _BY_SLUG.get(slug.strip().lower())


def requirements_from_slugs(slugs: tuple[str, ...] | list[str]) -> tuple[IntentRequirement, ...]:
    """Resolve persisted requirement slugs, ignoring anything unrecognised."""
    resolved: list[IntentRequirement] = []
    for slug in slugs:
        found = requirement_by_slug(slug)
        if found is not None and found not in resolved:
            resolved.append(found)
    return tuple(resolved)


def _normalize(text: str) -> str:
    return text.lower().replace("’", "'").replace("‘", "'")


def _matches_term(text: str, term: str) -> bool:
    """Word-boundary aware containment, so 'art' does not match 'apart'."""
    pattern = r"(?<!\w)" + re.escape(term).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text) is not None


def match_requirement(
    requirement: IntentRequirement, evidence: CandidateEvidence, stop_name: str
) -> RequirementMatch | None:
    """The first real piece of evidence for `requirement`, or None.

    A candidate's category is deliberately not sufficient on its own: too many
    venues share a category for it to prove a specific request was met.
    """
    for field, value in evidence.searchable_fields():
        haystack = _normalize(value)
        for term in requirement.evidence_terms:
            if _matches_term(haystack, _normalize(term)):
                return RequirementMatch(stop_name=stop_name, field=field, term=term)
    return None


def evaluate_coverage(
    requirements: tuple[IntentRequirement, ...],
    stops: tuple[tuple[str, CandidateEvidence], ...],
) -> IntentCoverage:
    """Deterministic coverage of `requirements` by the stops actually in the plan.

    One stop can satisfy several requirements, and coverage never requires a
    dedicated stop per phrase. A requirement with no evidence in any stop is
    reported as not covered rather than quietly assumed.
    """
    items: list[RequirementCoverage] = []
    for requirement in requirements:
        matches = tuple(
            match
            for stop_name, evidence in stops
            if (match := match_requirement(requirement, evidence, stop_name)) is not None
        )
        items.append(RequirementCoverage(requirement=requirement, matches=matches))
    return IntentCoverage(items=tuple(items))
