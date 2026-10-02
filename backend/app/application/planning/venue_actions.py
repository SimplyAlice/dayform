"""Venue-level execution actions derived from verified business data.

M6 already derives execution actions for a *persisted* `PlanItem`. A proposed
itinerary has no `PlanItem` yet, but the user still needs to know how to actually
reach, contact or book a venue before confirming the plan. This module holds the
shared, item-independent part of that derivation so both the confirmed-plan path
and the pre-confirmation proposal path produce identical actions from identical
verified data.

Truthfulness rules encoded here:
  * An action exists only when the underlying datum exists and is well formed.
  * `Reserve` appears only for a real reservation URL. No booking URL is ever
    synthesised, and a venue without one simply offers no Reserve action.
  * Directions are derived from the venue's own recorded address, never invented.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from app.domain.entities.planning.execution import ExecutionActionType


@dataclass(frozen=True)
class VenueActionSpec:
    """One executable action for a venue, independent of any persisted item."""

    action_type: ExecutionActionType
    label: str
    target_url: str
    description: str


def is_valid_web_url(url: str | None) -> bool:
    """Accept only real http(s) destinations."""
    if not url or not isinstance(url, str):
        return False
    stripped = url.strip()
    return stripped.startswith("https://") or stripped.startswith("http://")


def build_directions_url(address: str) -> str:
    """Build a maps link that searches for the venue's recorded address."""
    encoded = urllib.parse.quote_plus(address.strip())
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"


def derive_venue_action_specs(
    *,
    name: str,
    location: str | None,
    source_url: str | None,
    phone: str | None,
    reservation_url: str | None,
) -> list[VenueActionSpec]:
    """Derive the truthful set of actions available for a venue.

    Each action is gated on real data. When nothing is known beyond an address,
    the result is a single Directions action rather than a fabricated booking path.
    """
    specs: list[VenueActionSpec] = []
    address = (location or "").strip()

    if source_url and is_valid_web_url(source_url):
        specs.append(
            VenueActionSpec(
                action_type=ExecutionActionType.OPEN_WEBSITE,
                label="Website",
                target_url=source_url.strip(),
                description=f"Visit the official website of {name}",
            )
        )

    if address:
        specs.append(
            VenueActionSpec(
                action_type=ExecutionActionType.DIRECTIONS,
                label="Directions",
                target_url=build_directions_url(address),
                description=f"Get directions to {address}",
            )
        )

    if phone and phone.strip():
        clean_digits = re.sub(r"[^\d+]", "", phone.strip())
        if clean_digits:
            specs.append(
                VenueActionSpec(
                    action_type=ExecutionActionType.CALL,
                    label="Call",
                    target_url=f"tel:{clean_digits}",
                    description=f"Call {phone.strip()}",
                )
            )

    # Reserve exists only when the venue publishes a real reservation URL.
    if reservation_url and is_valid_web_url(reservation_url):
        specs.append(
            VenueActionSpec(
                action_type=ExecutionActionType.RESERVE,
                label="Reserve",
                target_url=reservation_url.strip(),
                description=f"Open the official booking page for {name}",
            )
        )

    return specs


def contact_fallback_label(specs: list[VenueActionSpec]) -> str | None:
    """Describe how a user can reach a venue that offers no reservation system.

    A venue with no booking URL is not a dead end: it can still be called or
    visited. This returns a truthful short label for that path, or `None` when
    there is genuinely no way to make contact.
    """
    types = {spec.action_type for spec in specs}
    if ExecutionActionType.RESERVE in types:
        return None
    if ExecutionActionType.CALL in types:
        return "Contact venue"
    if ExecutionActionType.OPEN_WEBSITE in types:
        return "Visit website"
    return None
