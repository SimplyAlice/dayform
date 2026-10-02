from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.entities.planning.constraint import ConstraintType
from app.domain.entities.planning.plan_item import PlanItemType


@dataclass(frozen=True)
class ConstraintInput:
    type: ConstraintType
    value: str
    numeric_value: Decimal | None = None


@dataclass(frozen=True)
class CreatePlanData:
    user_id: UUID
    intention: str
    title: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    group_size: int = 1
    transport_mode: str | None = None
    origin: str | None = None
    constraints: list[ConstraintInput] | None = None


@dataclass(frozen=True)
class PlanningIntent:
    user_id: UUID
    raw_request: str
    goal: str
    location: str | None = None
    date: date_type | None = None
    group_size: int = 1
    budget_max: Decimal | None = None
    activities: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlanItemData:
    name: str
    item_type: PlanItemType
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_cost: Decimal | None = None
    location: str | None = None
    position: int | None = None
