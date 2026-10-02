"""Execution layer service for Dayform.

Connects approved plan items to authentic, verified real-world actions:
- Visit website (verified source_url)
- Get directions (verified physical address)
- Call venue (verified phone number)
- Reserve (verified external reservation URL)
- Add to calendar (chronological start/end times)
- Mark complete (user confirmation of stop execution)

Follows the Core Principle:
"Recommend -> Prepare -> User approves -> Execute where supported -> Confirm"
Never fabricates actions, availability, bookings, or confirmations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import urllib.parse
from uuid import UUID

from app.application.planning.errors import OptionNotFoundError, PlanItemNotFoundError, PlanningNotFoundError
from app.application.planning.information import PlanningInformationService
from app.application.planning.planning_service import PlanningService
from app.application.planning.venue_actions import (
    contact_fallback_label,
    derive_venue_action_specs,
    is_valid_web_url,
)
from app.domain.entities.planning.execution import (
    ExecutionAction,
    ExecutionActionStatus,
    ExecutionActionType,
    ExecutionResult,
    PlanExecutionStatus,
    PlanItemStatus,
)
from app.domain.entities.planning.information import Activity, Place
from app.domain.entities.planning.plan import Plan, PlanStatus
from app.domain.entities.planning.plan_item import PlanItem


@dataclass(frozen=True)
class PlanItemActions:
    item_id: UUID
    item_name: str
    item_status: str
    actions: list[ExecutionAction]
    opening_hours: str | None = None
    address: str | None = None
    contact_hint: str | None = None


@dataclass(frozen=True)
class PlanActions:
    plan_id: UUID
    plan_status: str
    items: list[PlanItemActions]


class PlanExecutionService:
    """Manages the derivation, validation, and execution of plan item actions."""

    def __init__(
        self,
        planning_service: PlanningService,
        information_service: PlanningInformationService,
    ) -> None:
        self._plans = planning_service
        self._information = information_service

    async def get_plan_actions(self, user_id: UUID, plan_id: UUID) -> PlanActions:
        """Derive all available execution actions for each item in the plan."""
        plan = await self._plans.get_plan(user_id, plan_id)

        all_places = await self._get_all_places()
        all_activities = await self._get_all_activities()

        item_actions_list: list[PlanItemActions] = []
        completed_count = 0

        for item in plan.items:
            matched_option = self._match_item_to_option(item, all_places, all_activities)
            actions = self._derive_item_actions(item, matched_option)
            hint = self._derive_item_hint(item, matched_option)
            item_status_val = (
                item.status.value if hasattr(item.status, "value") else str(item.status)
            )
            if item_status_val == PlanItemStatus.COMPLETED.value:
                completed_count += 1

            matched_hours = getattr(matched_option, "opening_hours", None) if matched_option else None
            matched_address = (getattr(matched_option, "address", None) if matched_option else None) or item.location

            item_actions_list.append(
                PlanItemActions(
                    item_id=item.id,
                    item_name=item.name,
                    item_status=item_status_val,
                    actions=actions,
                    opening_hours=matched_hours,
                    address=matched_address,
                    contact_hint=hint,
                )
            )

        # Derive aggregate execution progression
        if len(plan.items) > 0 and completed_count == len(plan.items):
            plan_status_val = PlanExecutionStatus.COMPLETED.value
        elif completed_count > 0:
            plan_status_val = PlanExecutionStatus.IN_PROGRESS.value
        else:
            plan_status_val = PlanExecutionStatus.READY.value

        return PlanActions(
            plan_id=plan.id,
            plan_status=plan_status_val,
            items=item_actions_list,
        )

    async def execute_action(
        self,
        user_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        action_type: ExecutionActionType,
        target_url: str | None = None,
    ) -> ExecutionResult:
        """Execute a specific action for a plan item safely and honestly."""
        plan = await self._plans.get_plan(user_id, plan_id)
        item = next((i for i in plan.items if i.id == item_id), None)
        if item is None:
            raise PlanItemNotFoundError("Plan item not found.")

        # Re-derive actions to confirm genuine availability
        all_places = await self._get_all_places()
        all_activities = await self._get_all_activities()
        matched_option = self._match_item_to_option(item, all_places, all_activities)
        derived_actions = self._derive_item_actions(item, matched_option)

        action = next((a for a in derived_actions if a.action_type is action_type), None)
        if action is None or not action.is_available:
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.UNAVAILABLE,
                message=f"The requested action '{action_type.value}' is not available for this venue. The plan is unchanged.",
                target_url=None,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        destination_url = target_url or action.target_url

        # Validate destination URL security if an external destination is used
        if destination_url:
            security_error = self._validate_url_security(destination_url)
            if security_error:
                return ExecutionResult(
                    action_type=action_type,
                    status=ExecutionActionStatus.FAILED,
                    message=f"Action failed security validation: {security_error}. The plan is unchanged.",
                    target_url=None,
                    item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                    plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
                )

        # Handle action outcomes
        if action_type is ExecutionActionType.MARK_COMPLETE:
            updated_item = await self.complete_item(user_id, plan_id, item_id)
            plan_actions = await self.get_plan_actions(user_id, plan_id)
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.COMPLETED,
                message=f"'{item.name}' marked as completed.",
                target_url=None,
                item_status=PlanItemStatus.COMPLETED.value,
                plan_status=plan_actions.plan_status,
            )

        if action_type is ExecutionActionType.RESERVE:
            # Truthful reservation response: external reservation page opened, not confirmed
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.IN_PROGRESS,
                message=f"Reservation page opened for '{item.name}'. Please complete your reservation directly on the venue's booking portal.",
                target_url=destination_url,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        if action_type is ExecutionActionType.DIRECTIONS:
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.COMPLETED,
                message=f"Directions to '{item.name}' opened in Google Maps.",
                target_url=destination_url,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        if action_type is ExecutionActionType.CALL:
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.COMPLETED,
                message=f"Initiating call to '{item.name}'.",
                target_url=destination_url,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        if action_type is ExecutionActionType.OPEN_WEBSITE:
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.COMPLETED,
                message=f"Official website opened for '{item.name}'.",
                target_url=destination_url,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        if action_type is ExecutionActionType.ADD_TO_CALENDAR:
            return ExecutionResult(
                action_type=action_type,
                status=ExecutionActionStatus.COMPLETED,
                message=f"Calendar event template prepared for '{item.name}'. Save it to your calendar.",
                target_url=destination_url,
                item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            )

        return ExecutionResult(
            action_type=action_type,
            status=ExecutionActionStatus.FAILED,
            message="Unrecognized action type.",
            target_url=None,
            item_status=item.status.value if hasattr(item.status, "value") else str(item.status),
            plan_status=plan.status.value if hasattr(plan.status, "value") else str(plan.status),
        )

    async def complete_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> PlanItem:
        """Mark an individual item as completed."""
        plan = await self._plans.get_plan(user_id, plan_id)
        item = next((i for i in plan.items if i.id == item_id), None)
        if item is None:
            raise PlanItemNotFoundError("Plan item not found.")

        updated_item = await self._plans.update_item(
            user_id,
            plan_id,
            item_id,
            {"status": PlanItemStatus.COMPLETED},
        )
        return updated_item

    async def uncomplete_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> PlanItem:
        """Revert an individual item back to planned."""
        plan = await self._plans.get_plan(user_id, plan_id)
        item = next((i for i in plan.items if i.id == item_id), None)
        if item is None:
            raise PlanItemNotFoundError("Plan item not found.")

        updated_item = await self._plans.update_item(
            user_id,
            plan_id,
            item_id,
            {"status": PlanItemStatus.PLANNED},
        )
        return updated_item

    def _derive_item_actions(
        self,
        item: PlanItem,
        matched: Place | Activity | None,
    ) -> list[ExecutionAction]:
        """Derive truthful, contextual execution actions for an item.

        The venue-level actions come from the shared derivation so a proposed
        (not yet persisted) stop offers exactly the same actions as a saved one.
        """
        actions: list[ExecutionAction] = []
        source_url = matched.source_url if matched else None
        address = (matched.address if matched and matched.address else None) or item.location
        phone = matched.phone if matched else None
        reservation_url = matched.reservation_url if matched else None

        labels = {
            ExecutionActionType.OPEN_WEBSITE: "Visit website",
            ExecutionActionType.DIRECTIONS: "Get directions",
        }
        for spec in derive_venue_action_specs(
            name=item.name,
            location=address,
            source_url=source_url,
            phone=phone,
            reservation_url=reservation_url,
        ):
            actions.append(
                ExecutionAction(
                    id=f"act-{spec.action_type.value}-{item.id}",
                    item_id=item.id,
                    action_type=spec.action_type,
                    label=labels.get(spec.action_type, spec.label),
                    target_url=spec.target_url,
                    is_available=True,
                    status=ExecutionActionStatus.AVAILABLE,
                    description=spec.description,
                )
            )

        # 5. Add to Calendar (if item has start and end times)
        if item.start_time and item.end_time:
            calendar_url = self._build_google_calendar_url(item, address)
            actions.append(
                ExecutionAction(
                    id=f"act-cal-{item.id}",
                    item_id=item.id,
                    action_type=ExecutionActionType.ADD_TO_CALENDAR,
                    label="Add to calendar",
                    target_url=calendar_url,
                    is_available=True,
                    status=ExecutionActionStatus.AVAILABLE,
                    description="Open calendar event template",
                )
            )

        # 6. Mark Complete
        item_status_val = (
            item.status.value if hasattr(item.status, "value") else str(item.status)
        )
        actions.append(
            ExecutionAction(
                id=f"act-complete-{item.id}",
                item_id=item.id,
                action_type=ExecutionActionType.MARK_COMPLETE,
                label="Undo complete" if item_status_val == PlanItemStatus.COMPLETED.value else "Mark complete",
                target_url=None,
                is_available=True,
                status=ExecutionActionStatus.COMPLETED if item_status_val == PlanItemStatus.COMPLETED.value else ExecutionActionStatus.AVAILABLE,
                description="Mark this stop as completed",
            )
        )

        return actions

    def _derive_item_hint(
        self,
        item: PlanItem,
        matched: Place | Activity | None,
    ) -> str | None:
        """Derive truthful contact hint when venue publishes no direct booking path."""
        source_url = matched.source_url if matched else None
        address = (matched.address if matched and matched.address else None) or item.location
        phone = matched.phone if matched else None
        reservation_url = matched.reservation_url if matched else None

        specs = derive_venue_action_specs(
            name=item.name,
            location=address,
            source_url=source_url,
            phone=phone,
            reservation_url=reservation_url,
        )
        return contact_fallback_label(specs)

    def _match_item_to_option(
        self,
        item: PlanItem,
        places: list[Place],
        activities: list[Activity],
    ) -> Place | Activity | None:
        """Find the underlying Place or Activity matching the item."""
        norm_name = item.name.strip().casefold()

        # Check places first
        for p in places:
            if p.name.strip().casefold() == norm_name:
                return p

        # Check activities
        for a in activities:
            if a.name.strip().casefold() == norm_name:
                return a

        # Substring matching fallback
        for p in places:
            if norm_name in p.name.strip().casefold() or p.name.strip().casefold() in norm_name:
                return p
        for a in activities:
            if norm_name in a.name.strip().casefold() or a.name.strip().casefold() in norm_name:
                return a

        return None

    async def _get_all_places(self) -> list[Place]:
        try:
            from app.infrastructure.planning.openstreetmap_provider import PLACES_CATALOG
            return list(PLACES_CATALOG)
        except ImportError:
            return []

    async def _get_all_activities(self) -> list[Activity]:
        try:
            from app.infrastructure.planning.openstreetmap_provider import ACTIVITIES_CATALOG
            return list(ACTIVITIES_CATALOG)
        except ImportError:
            return []

    def _is_valid_web_url(self, url: str) -> bool:
        return is_valid_web_url(url)

    def _validate_url_security(self, url: str) -> str | None:
        """Validate protocol whitelist and prevent injection."""
        clean = url.strip().lower()
        if clean.startswith("javascript:") or clean.startswith("file:") or clean.startswith("data:text/html"):
            return "Unsafe URI scheme prohibited"
        if not (clean.startswith("https://") or clean.startswith("tel:") or clean.startswith("data:text/calendar")):
            return "Only HTTPS web destinations, tel: dialers, and calendar events are permitted"
        return None

    def _build_google_calendar_url(self, item: PlanItem, address: str | None) -> str:
        """Construct a Google Calendar template link for honest user-initiated scheduling."""
        if not item.start_time or not item.end_time:
            return ""
        start_fmt = item.start_time.strftime("%Y%m%dT%H%M%SZ")
        end_fmt = item.end_time.strftime("%Y%m%dT%H%M%SZ")
        params = {
            "action": "TEMPLATE",
            "text": item.name,
            "dates": f"{start_fmt}/{end_fmt}",
            "details": f"Planned with Dayform: {item.description or item.name}",
            "location": address or item.location or "Cape Town",
        }
        return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"
