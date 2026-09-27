from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.entities.planning.decision import CandidateType
from app.domain.entities.planning.plan_item import PlanItem, PlanItemType


class ChangeType(str, Enum):
    TIME_SHIFT = "time_shift"
    DEADLINE_CHANGED = "deadline_changed"
    DURATION_LIMIT_CHANGED = "duration_limit_changed"
    BUDGET_REDUCED = "budget_reduced"
    BUDGET_CHANGED = "budget_changed"
    GROUP_SIZE_CHANGED = "group_size_changed"
    LOCATION_CHANGED = "location_changed"
    EXCLUSION_ADDED = "exclusion_added"
    PREFERENCE_CHANGED = "preference_changed"
    VENUE_INVALIDATED = "venue_invalidated"
    MOBILITY_DISRUPTION = "mobility_disruption"
    MOBILITY_PREFERENCE_CHANGED = "mobility_preference_changed"
    OTHER = "other"


class ItemAction(str, Enum):
    KEPT = "kept"
    REPLACED = "replaced"
    REMOVED = "removed"
    RESCHEDULED = "rescheduled"
    ADDED = "added"


@dataclass
class ItemDiff:
    action: ItemAction
    original_item_id: UUID | None = None
    original_name: str | None = None
    new_name: str | None = None
    original_start_time: datetime | None = None
    new_start_time: datetime | None = None
    original_end_time: datetime | None = None
    new_end_time: datetime | None = None
    original_cost: Decimal | None = None
    new_cost: Decimal | None = None
    location: str | None = None
    item_type: PlanItemType | None = None
    reason: str = ""
    candidate_option_id: UUID | None = None
    candidate_option_type: CandidateType | None = None


@dataclass
class PlanAdaptation:
    plan_id: UUID
    changes_detected: list[ChangeType]
    narrative_summary: str
    diffs: list[ItemDiff]
    adapted_items: list[PlanItem] = field(default_factory=list)
    new_start_time: datetime | None = None
    new_end_time: datetime | None = None
    new_total_cost: Decimal = Decimal("0")
    budget_delta: Decimal | None = None
    is_feasible: bool = True
    feasibility_note: str | None = None
