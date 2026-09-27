"""Live service-status sources for mobility providers.

Each source is provider-specific and lives in infrastructure. A provider with no
publicly reachable live feed is wired to `UnavailableLiveStatusSource` so that the
product reports "live status unavailable" instead of implying it is tracking the
service.
"""

from __future__ import annotations

from app.infrastructure.mobility.live.http_json_source import HttpJsonLiveStatusSource
from app.infrastructure.mobility.live.unavailable_source import UnavailableLiveStatusSource

__all__ = ["HttpJsonLiveStatusSource", "UnavailableLiveStatusSource"]
