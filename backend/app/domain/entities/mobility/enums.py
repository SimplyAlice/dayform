from __future__ import annotations

from enum import Enum


class TransportMode(str, Enum):
    WALK = "walk"
    BUS = "bus"
    TRAIN = "train"
    RIDE_HAIL = "ride_hail"
    CYCLE = "cycle"
    SHUTTLE = "shuttle"
    OTHER = "other"


class BookingCapability(str, Enum):
    NO_BOOKING = "no_booking"
    EXTERNAL_HANDOFF = "external_handoff"
    DEEPLINK = "deeplink"
    EMBEDDED = "embedded"
    API_BOOKING = "api_booking"


class MobilityLiveStatus(str, Enum):
    SCHEDULED = "scheduled"
    ESTIMATED = "estimated"
    LIVE = "live"
    OPERATING_NORMAL = "operating_normal"
    DELAYED = "delayed"
    DISRUPTED = "disrupted"
    CANCELLED = "cancelled"
    SERVICE_UNAVAILABLE = "service_unavailable"
    UNKNOWN = "unknown"


class MobilityLiveAvailability(str, Enum):
    """How trustworthy the live status itself is.

    Separates "we asked a live source and it answered" from "we have no live source
    at all", so a provider without a public feed is never presented as merely unknown
    data rather than a genuinely absent capability.
    """

    LIVE = "live"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


#: Statuses that mean the service cannot be relied upon as planned.
BLOCKING_LIVE_STATUSES = frozenset(
    {
        MobilityLiveStatus.CANCELLED,
        MobilityLiveStatus.DISRUPTED,
        MobilityLiveStatus.SERVICE_UNAVAILABLE,
    }
)


class MobilitySourceType(str, Enum):
    OFFICIAL_REALTIME = "official_realtime"
    OFFICIAL_TIMETABLE = "official_timetable"
    APPROVED_PROVIDER_API = "approved_provider_api"
    TRUSTED_THIRD_PARTY = "trusted_third_party"
    CROWD_REPORT = "crowd_report"
    CALCULATED = "calculated"
    UNKNOWN = "unknown"


def get_source_hierarchy_weight(source_type: MobilitySourceType) -> int:
    """Return numeric trust weight for evidence comparison. Higher is more trusted."""
    weights = {
        MobilitySourceType.OFFICIAL_REALTIME: 100,
        MobilitySourceType.OFFICIAL_TIMETABLE: 80,
        MobilitySourceType.APPROVED_PROVIDER_API: 70,
        MobilitySourceType.TRUSTED_THIRD_PARTY: 50,
        MobilitySourceType.CALCULATED: 40,
        MobilitySourceType.CROWD_REPORT: 20,
        MobilitySourceType.UNKNOWN: 0,
    }
    return weights.get(source_type, 0)
