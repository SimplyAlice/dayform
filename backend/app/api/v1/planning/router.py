from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import (
    get_intent_interpreter,
    get_live_intelligence_service,
    get_mobility_planning_service,
    get_plan_adaptation_service,
    get_plan_execution_service,
    get_plan_selection_service,
    get_planning_decision_service,
    get_planning_information_service,
    get_planning_service,
    get_planning_understanding_service,
)
from app.api.v1.auth import get_current_user
from app.api.v1.planning.information import DecisionCandidateRead, RecommendationResponse
from app.application.planning.adaptation_service import PlanAdaptationService
from app.application.planning.decision_service import PlanningDecisionService
from app.application.planning.dtos import ConstraintInput, CreatePlanData, PlanItemData
from app.application.planning.errors import OptionNotFoundError, PlanItemNotFoundError, PlanningNotFoundError
from app.application.planning.execution_service import PlanExecutionService
from app.application.planning.information import PlanningInformationService
from app.application.planning.intent_interpreter import IntentInterpreter
from app.application.planning.live_intelligence_service import LiveIntelligenceService
from app.application.planning.mobility_planning_service import (
    MobilityPlanningService,
    StopSequencePoint,
)
from app.application.planning.planning_service import PlanningService
from app.application.planning.ports import PlanningUnderstandingPort
from app.application.planning.selection_service import PlanSelectionService, criteria_from_plan
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption
from app.domain.entities.planning.adaptation import ItemAction, ItemDiff, PlanAdaptation
from app.domain.entities.planning.constraint import ConstraintType
from app.domain.entities.planning.decision import CandidateType
from app.domain.entities.planning.transition import ItineraryFeasibility, PlanTransition
from app.domain.entities.planning.execution import (
    ExecutionAction,
    ExecutionActionStatus,
    ExecutionActionType,
    ExecutionResult,
    PlanExecutionStatus,
    PlanItemStatus,
)
from app.domain.entities.planning.live_intelligence import (
    LiveChangeType,
    LiveSignal,
    LiveSignalType,
    PlanHealthCheckResult,
    PlanHealthStatus,
)
from app.domain.entities.planning.plan import Plan, PlanStatus
from app.domain.entities.planning.plan_item import PlanItem, PlanItemType
from app.domain.entities.planning.understanding import PlanningUnderstanding
from app.infrastructure.db.models import User

router = APIRouter(prefix="/planning", tags=["planning"])


class ConstraintWrite(BaseModel):
    type: ConstraintType
    value: str = Field(..., min_length=1)
    numeric_value: Decimal | None = Field(default=None, ge=0)

    def to_input(self) -> ConstraintInput:
        return ConstraintInput(type=self.type, value=self.value, numeric_value=self.numeric_value)


class ContextWrite(BaseModel):
    location: str | None = Field(default=None, max_length=255)
    start_time: datetime | None = None
    end_time: datetime | None = None
    group_size: int = Field(default=1, ge=1)
    transport_mode: str | None = Field(default=None, max_length=100)

    def to_changes(self) -> dict[str, object]:
        return self.model_dump()


class ContextPatch(BaseModel):
    location: str | None = Field(default=None, max_length=255)
    start_time: datetime | None = None
    end_time: datetime | None = None
    group_size: int | None = Field(default=None, ge=1)
    transport_mode: str | None = Field(default=None, max_length=100)

    def to_changes(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True)


class CreatePlanRequest(ContextWrite):
    intention: str = Field(..., min_length=1, max_length=5000)
    title: str | None = Field(default=None, max_length=255)
    constraints: list[ConstraintWrite] = Field(default_factory=list)

    def to_data(self, user_id: UUID) -> CreatePlanData:
        return CreatePlanData(user_id=user_id, intention=self.intention, title=self.title, location=self.location,
                              start_time=self.start_time, end_time=self.end_time, group_size=self.group_size,
                              transport_mode=self.transport_mode, constraints=[item.to_input() for item in self.constraints])


class PlanPatchRequest(BaseModel):
    intention: str | None = Field(default=None, min_length=1, max_length=5000)
    title: str | None = Field(default=None, max_length=255)
    status: PlanStatus | None = None
    context: ContextPatch | None = None
    constraints: list[ConstraintWrite] | None = None

    def to_changes(self) -> dict[str, object]:
        changes: dict[str, object] = {}
        if "intention" in self.model_fields_set:
            changes["intention"] = self.intention
        if "title" in self.model_fields_set:
            changes["title"] = self.title
        if "status" in self.model_fields_set:
            changes["status"] = self.status
        if "context" in self.model_fields_set and self.context is not None:
            changes["context"] = self.context.to_changes()
        if "constraints" in self.model_fields_set:
            changes["constraints"] = [item.to_input() for item in self.constraints or []]
        return changes


class PlanItemCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    item_type: PlanItemType
    description: str | None = Field(default=None, max_length=5000)
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=255)
    position: int | None = Field(default=None, ge=0)

    def to_data(self) -> PlanItemData:
        return PlanItemData(**self.model_dump())


class PlanItemPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    item_type: PlanItemType | None = None
    description: str | None = Field(default=None, max_length=5000)
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=255)
    position: int | None = Field(default=None, ge=0)

    def to_changes(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True)


class UnderstandingRead(BaseModel):
    goal: str
    occasion: str | None = None
    people_count: int | None = None
    relationship_context: str | None = None
    date_spec: str | None = None
    time_window: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    time_confidence: str = "approximate"
    duration_limit_minutes: int | None = None
    location: str | None = None
    location_is_inferred: bool = False
    transport_mode: str | None = None
    budget_amount: Decimal | None = None
    budget_kind: str = "none"
    preferences: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    activity_types: list[str] = Field(default_factory=list)
    semantic_descriptors: list[str] = Field(default_factory=list)
    setting_preference: str | None = None
    weather_context: str | None = None
    ambiguities: list[str] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_understanding(cls, u: PlanningUnderstanding) -> UnderstandingRead:
        return cls(
            goal=u.goal,
            occasion=u.occasion,
            people_count=u.people_count,
            relationship_context=u.relationship_context,
            date_spec=u.date_spec,
            time_window=u.time_window,
            start_time=u.start_time,
            end_time=u.end_time,
            time_confidence=u.time_confidence,
            duration_limit_minutes=u.duration_limit_minutes,
            location=u.location,
            location_is_inferred=u.location_is_inferred,
            transport_mode=u.transport_mode,
            budget_amount=u.budget_amount,
            budget_kind=u.budget_kind.value,
            preferences=list(u.preferences),
            exclusions=list(u.exclusions),
            activity_types=[cat.value for cat in u.activity_types],
            semantic_descriptors=list(u.semantic_descriptors),
            setting_preference=u.setting_preference,
            weather_context=u.weather_context,
            ambiguities=list(u.ambiguities),
            provenance=dict(u.provenance),
        )


class PlanModifyRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=5000)


class CreatePlanFromIntentRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=5000)


class SelectOptionRequest(BaseModel):
    """Explicitly select an information-layer option to add to a plan."""

    option_id: UUID
    option_type: CandidateType
    position: int | None = Field(default=None, ge=0)
    start_time: datetime | None = None
    end_time: datetime | None = None


class ContextRead(BaseModel):
    location: str | None
    start_time: datetime | None
    end_time: datetime | None
    group_size: int
    transport_mode: str | None


class ConstraintRead(BaseModel):
    id: UUID
    type: ConstraintType
    value: str
    numeric_value: Decimal | None


class PlanItemRead(BaseModel):
    id: UUID
    name: str
    item_type: PlanItemType
    description: str | None
    start_time: datetime | None
    end_time: datetime | None
    duration_minutes: int | None
    estimated_cost: Decimal | None
    location: str | None
    position: int
    status: str = "planned"

    @classmethod
    def from_item(cls, item: PlanItem) -> PlanItemRead:
        item_status_val = (
            item.status.value if hasattr(item.status, "value") else str(item.status)
        )
        return cls(id=item.id, name=item.name, item_type=item.item_type, description=item.description,
                   start_time=item.start_time, end_time=item.end_time, duration_minutes=item.duration_minutes,
                   estimated_cost=item.estimated_cost, location=item.location, position=item.position,
                   status=item_status_val)


class BudgetRead(BaseModel):
    budget_maximum: Decimal | None
    total_planned_cost: Decimal
    remaining_budget: Decimal | None
    is_over_budget: bool


class PlanTransitionOptionRead(BaseModel):
    provider_id: str
    provider_name: str
    mode: str
    duration_minutes: int | None
    cost: Decimal | None
    cost_known: bool
    currency: str = "ZAR"
    transfers: int = 0
    confidence: float
    live_status: str
    booking_capability: str
    booking_url: str | None = None
    summary: str

    @classmethod
    def from_option(cls, opt: MobilityOption) -> PlanTransitionOptionRead:
        return cls(
            provider_id=opt.provider_id,
            provider_name=opt.provider_name,
            mode=opt.mode.value if hasattr(opt.mode, "value") else str(opt.mode),
            duration_minutes=opt.duration_minutes,
            cost=opt.cost,
            cost_known=not opt.cost_is_unknown,
            currency=opt.currency,
            transfers=opt.transfers,
            confidence=opt.confidence,
            live_status=opt.live_status.value if hasattr(opt.live_status, "value") else str(opt.live_status),
            booking_capability=opt.booking_capability.value if hasattr(opt.booking_capability, "value") else str(opt.booking_capability),
            booking_url=opt.booking_url,
            summary=opt.summary,
        )


class PlanTransitionRead(BaseModel):
    id: str
    from_item_id: UUID | None = None
    to_item_id: UUID | None = None
    from_location: str
    to_location: str
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    duration_minutes: int | None = None
    mode: str
    provider_id: str
    provider_name: str
    cost: Decimal | None = None
    cost_known: bool
    currency: str = "ZAR"
    transfers: int = 0
    confidence: float
    live_status: str
    booking_capability: str
    booking_url: str | None = None
    summary: str
    is_feasible: bool = True
    feasibility_issue: str | None = None
    # M16 live mobility state. `unavailable` means no live source exists for this
    # provider, which is distinct from live data that simply could not be fetched.
    live_availability: str = "unavailable"
    live_explanation: str | None = None
    live_source: str | None = None
    live_source_type: str = "unknown"
    live_observed_at: datetime | None = None
    live_confidence: float = 0.0
    live_delay_minutes: int | None = None
    available_options: list[PlanTransitionOptionRead] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, t: PlanTransition) -> PlanTransitionRead:
        return cls(
            id=t.id,
            from_item_id=t.from_item_id,
            to_item_id=t.to_item_id,
            from_location=t.from_location,
            to_location=t.to_location,
            departure_time=t.departure_time,
            arrival_time=t.arrival_time,
            duration_minutes=t.duration_minutes,
            mode=t.mode.value if hasattr(t.mode, "value") else str(t.mode),
            provider_id=t.provider_id,
            provider_name=t.provider_name,
            cost=t.cost,
            cost_known=t.cost_known,
            currency=t.currency,
            transfers=t.transfers,
            confidence=t.confidence,
            live_status=t.live_status.value if hasattr(t.live_status, "value") else str(t.live_status),
            booking_capability=t.booking_capability.value if hasattr(t.booking_capability, "value") else str(t.booking_capability),
            booking_url=t.booking_url,
            summary=t.summary,
            is_feasible=t.is_feasible,
            feasibility_issue=t.feasibility_issue,
            live_availability=t.live_availability.value if hasattr(t.live_availability, "value") else str(t.live_availability),
            live_explanation=t.live_explanation,
            live_source=t.live_source,
            live_source_type=t.live_source_type.value if hasattr(t.live_source_type, "value") else str(t.live_source_type),
            live_observed_at=t.live_observed_at,
            live_confidence=t.live_confidence,
            live_delay_minutes=t.live_delay_minutes,
            available_options=[PlanTransitionOptionRead.from_option(o) for o in t.available_options],
        )


class ItineraryFeasibilityRead(BaseModel):
    is_feasible: bool
    deadline_respected: bool
    budget_respected: bool
    transitions_feasible: bool
    issues: list[str]
    warnings: list[str]
    total_transition_duration_minutes: int
    total_known_transition_cost: Decimal
    has_unknown_transition_costs: bool

    @classmethod
    def from_domain(cls, f: ItineraryFeasibility) -> ItineraryFeasibilityRead:
        return cls(
            is_feasible=f.is_feasible,
            deadline_respected=f.deadline_respected,
            budget_respected=f.budget_respected,
            transitions_feasible=f.transitions_feasible,
            issues=list(f.issues),
            warnings=list(f.warnings),
            total_transition_duration_minutes=f.total_transition_duration_minutes,
            total_known_transition_cost=f.total_known_transition_cost,
            has_unknown_transition_costs=f.has_unknown_transition_costs,
        )


class PlanTransitionsResponse(BaseModel):
    plan_id: UUID
    transitions: list[PlanTransitionRead]
    feasibility: ItineraryFeasibilityRead


class EvaluateTransitionsRequest(BaseModel):
    preferred_modes: list[str] | None = None
    party_size: int = Field(default=1, ge=1)


class ProposedStopRead(BaseModel):
    """A stop in a proposed itinerary that has not yet been persisted as a plan item."""

    name: str = Field(default="", max_length=255)
    location: str = Field(..., min_length=1, max_length=255)
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)

    def to_point(self) -> StopSequencePoint:
        return StopSequencePoint(
            location=self.location,
            name=self.name,
            start_time=self.start_time,
            end_time=self.end_time,
            estimated_cost=self.estimated_cost,
        )


class ProposedTransitionsRequest(BaseModel):
    stops: list[ProposedStopRead] = Field(..., min_length=2, max_length=20)
    preferred_modes: list[str] | None = None
    party_size: int = Field(default=1, ge=1)


def _preferred_modes_from_context(transport_mode: str | None) -> list[TransportMode]:
    """Translate an extracted transport preference into concrete M14 transport modes.

    A preference such as "public transport" spans several modes, so it maps to a set
    rather than a single `TransportMode`. An unrecognised or absent preference yields
    no modes, leaving mobility selection to the default ranking.
    """
    if not transport_mode:
        return []
    normalized = transport_mode.strip().lower()
    if normalized in {"public_transport", "transit", "public_transit"}:
        return [TransportMode.BUS, TransportMode.TRAIN, TransportMode.SHUTTLE]
    if normalized == "walk":
        return [TransportMode.WALK]
    if normalized in {"ride_hail", "taxi"}:
        return [TransportMode.RIDE_HAIL]
    try:
        return [TransportMode(normalized)]
    except ValueError:
        return []


class PlanRead(BaseModel):
    id: UUID
    intention: str
    title: str | None
    status: PlanStatus
    created_at: datetime
    updated_at: datetime
    context: ContextRead | None
    constraints: list[ConstraintRead]
    items: list[PlanItemRead]
    budget: BudgetRead
    understanding: UnderstandingRead | None = None
    transitions: list[PlanTransitionRead] = Field(default_factory=list)
    feasibility: ItineraryFeasibilityRead | None = None

    @classmethod
    def from_plan(
        cls,
        plan: Plan,
        understanding: PlanningUnderstanding | None = None,
        transitions: list[PlanTransition] | None = None,
        feasibility: ItineraryFeasibility | None = None,
    ) -> PlanRead:
        context = None if plan.context is None else ContextRead(
            location=plan.context.location, start_time=plan.context.start_time, end_time=plan.context.end_time,
            group_size=plan.context.group_size, transport_mode=plan.context.transport_mode,
        )
        budget = plan.budget_summary()
        u_read = (
            UnderstandingRead.from_understanding(understanding)
            if understanding is not None
            else _build_plan_understanding_read(plan)
        )
        return cls(
            id=plan.id,
            intention=plan.intention,
            title=plan.title,
            status=plan.status,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            context=context,
            constraints=[
                ConstraintRead(
                    id=item.id,
                    type=item.type,
                    value=item.value,
                    numeric_value=item.numeric_value,
                )
                for item in plan.constraints
            ],
            items=[PlanItemRead.from_item(item) for item in plan.items],
            budget=BudgetRead(**budget.__dict__),
            understanding=u_read,
            transitions=[PlanTransitionRead.from_domain(t) for t in (transitions or [])],
            feasibility=ItineraryFeasibilityRead.from_domain(feasibility) if feasibility is not None else None,
        )


class ItemDiffRead(BaseModel):
    action: str
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
    item_type: str | None = None
    reason: str = ""
    candidate_option_id: UUID | None = None
    candidate_option_type: str | None = None

    @classmethod
    def from_domain(cls, diff: ItemDiff) -> ItemDiffRead:
        return cls(
            action=diff.action.value,
            original_item_id=diff.original_item_id,
            original_name=diff.original_name,
            new_name=diff.new_name,
            original_start_time=diff.original_start_time,
            new_start_time=diff.new_start_time,
            original_end_time=diff.original_end_time,
            new_end_time=diff.new_end_time,
            original_cost=diff.original_cost,
            new_cost=diff.new_cost,
            location=diff.location,
            item_type=diff.item_type.value if diff.item_type else None,
            reason=diff.reason,
            candidate_option_id=diff.candidate_option_id,
            candidate_option_type=diff.candidate_option_type.value if diff.candidate_option_type else None,
        )


class PlanAdaptationRead(BaseModel):
    plan_id: UUID
    changes_detected: list[str]
    narrative_summary: str
    diffs: list[ItemDiffRead]
    adapted_items: list[PlanItemRead]
    new_start_time: datetime | None = None
    new_end_time: datetime | None = None
    new_total_cost: Decimal = Decimal("0")
    budget_delta: Decimal | None = None
    is_feasible: bool = True
    feasibility_note: str | None = None

    @classmethod
    def from_domain(cls, adaptation: PlanAdaptation) -> PlanAdaptationRead:
        return cls(
            plan_id=adaptation.plan_id,
            changes_detected=[c.value for c in adaptation.changes_detected],
            narrative_summary=adaptation.narrative_summary,
            diffs=[ItemDiffRead.from_domain(d) for d in adaptation.diffs],
            adapted_items=[PlanItemRead.from_item(i) for i in adaptation.adapted_items],
            new_start_time=adaptation.new_start_time,
            new_end_time=adaptation.new_end_time,
            new_total_cost=adaptation.new_total_cost,
            budget_delta=adaptation.budget_delta,
            is_feasible=adaptation.is_feasible,
            feasibility_note=adaptation.feasibility_note,
        )


class ApplyAdaptationRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=5000)


class ExecutionActionRead(BaseModel):
    id: str
    item_id: UUID
    action_type: str
    label: str
    target_url: str | None = None
    is_available: bool = True
    status: str = "available"
    description: str | None = None

    @classmethod
    def from_domain(cls, action: ExecutionAction) -> ExecutionActionRead:
        return cls(
            id=action.id,
            item_id=action.item_id,
            action_type=action.action_type.value,
            label=action.label,
            target_url=action.target_url,
            is_available=action.is_available,
            status=action.status.value,
            description=action.description,
        )


class PlanItemActionsRead(BaseModel):
    item_id: UUID
    item_name: str
    item_status: str
    actions: list[ExecutionActionRead]


class PlanActionsRead(BaseModel):
    plan_id: UUID
    plan_status: str
    items: list[PlanItemActionsRead]


class ExecuteActionRequest(BaseModel):
    action_type: ExecutionActionType
    target_url: str | None = None


class ExecutionResultRead(BaseModel):
    action_type: str
    status: str
    message: str
    target_url: str | None = None
    item_status: str
    plan_status: str

    @classmethod
    def from_domain(cls, result: ExecutionResult) -> ExecutionResultRead:
        return cls(
            action_type=result.action_type.value,
            status=result.status.value,
            message=result.message,
            target_url=result.target_url,
            item_status=result.item_status,
            plan_status=result.plan_status,
        )


class LiveSignalRead(BaseModel):
    source: str
    signal_type: str
    observed_at: datetime
    freshness: str
    target_name: str
    target_item_id: UUID | None = None
    change_type: str
    is_meaningful_change: bool
    message: str

    @classmethod
    def from_domain(cls, signal: LiveSignal) -> LiveSignalRead:
        return cls(
            source=signal.source,
            signal_type=signal.signal_type.value,
            observed_at=signal.observed_at,
            freshness=signal.freshness.value if hasattr(signal.freshness, "value") else str(signal.freshness),
            target_name=signal.target_name,
            target_item_id=signal.target_item_id,
            change_type=signal.change_type.value if hasattr(signal.change_type, "value") else str(signal.change_type),
            is_meaningful_change=signal.is_meaningful_change,
            message=signal.message,
        )


class PlanHealthCheckRead(BaseModel):
    plan_id: UUID
    health_status: str
    headline: str
    narrative: str
    signals: list[LiveSignalRead]
    checked_at: datetime
    recommended_adaptation_prompt: str | None = None
    proposed_adaptation: PlanAdaptationRead | None = None

    @classmethod
    def from_domain(cls, result: PlanHealthCheckResult) -> PlanHealthCheckRead:
        return cls(
            plan_id=result.plan_id,
            health_status=result.health_status.value,
            headline=result.headline,
            narrative=result.narrative,
            signals=[LiveSignalRead.from_domain(s) for s in result.signals],
            checked_at=result.checked_at,
            recommended_adaptation_prompt=result.recommended_adaptation_prompt,
            proposed_adaptation=PlanAdaptationRead.from_domain(result.proposed_adaptation) if result.proposed_adaptation else None,
        )




def _build_plan_understanding_read(plan: Plan) -> UnderstandingRead:
    engine = DeterministicUnderstandingEngine()
    try:
        parsed = engine.parse(plan.intention)
    except Exception:
        parsed = None

    stored_exclusions: list[str] = []
    stored_preferences: list[str] = []
    stored_occasion: str | None = None
    stored_date: str | None = None
    stored_time: str | None = None
    stored_start_time: str | None = None
    stored_end_time: str | None = None
    stored_duration_limit: int | None = None

    for c in plan.constraints:
        if c.type is ConstraintType.REQUIREMENT:
            if c.value.startswith("exclude:"):
                stored_exclusions.append(c.value.split(":", 1)[1])
            elif c.value.startswith("date:"):
                stored_date = c.value.split(":", 1)[1]
            elif c.value.startswith("time:"):
                stored_time = c.value.split(":", 1)[1]
            elif c.value.startswith("start_time:"):
                stored_start_time = c.value.split(":", 1)[1]
            elif c.value.startswith("end_time:"):
                stored_end_time = c.value.split(":", 1)[1]
        elif c.type is ConstraintType.PREFERENCE:
            if c.value.startswith("occasion:"):
                stored_occasion = c.value.split(":", 1)[1]
            else:
                stored_preferences.append(c.value)
        elif c.type is ConstraintType.TIME_MAX:
            if c.numeric_value is not None:
                stored_duration_limit = int(c.numeric_value)
            else:
                digits = "".join(filter(str.isdigit, c.value))
                if digits:
                    stored_duration_limit = int(digits)

    budget_c = next((c for c in plan.constraints if c.type is ConstraintType.BUDGET_MAX), None)
    budget_amount = budget_c.numeric_value if budget_c else (parsed.budget_amount if parsed else None)
    budget_kind = parsed.budget_kind.value if parsed else ("hard_max" if budget_amount else "none")

    group_size = plan.context.group_size if plan.context else (parsed.people_count if parsed else 1)
    location = plan.context.location if plan.context else (parsed.location if parsed else "Cape Town")

    merged_exclusions = list(dict.fromkeys((list(parsed.exclusions) if parsed else []) + stored_exclusions))
    merged_preferences = list(dict.fromkeys((list(parsed.preferences) if parsed else []) + stored_preferences))

    context_start = plan.context.start_time.strftime("%H:%M") if plan.context and plan.context.start_time else None
    context_end = plan.context.end_time.strftime("%H:%M") if plan.context and plan.context.end_time else None

    return UnderstandingRead(
        goal=plan.title or (parsed.goal if parsed else plan.intention),
        occasion=stored_occasion or (parsed.occasion if parsed else None),
        people_count=group_size,
        relationship_context=parsed.relationship_context if parsed else None,
        date_spec=stored_date or (parsed.date_spec if parsed else None),
        time_window=stored_time or (parsed.time_window if parsed else None),
        start_time=stored_start_time or (parsed.start_time if parsed else context_start),
        end_time=stored_end_time or (parsed.end_time if parsed else context_end),
        time_confidence=parsed.time_confidence if parsed else "approximate",
        duration_limit_minutes=stored_duration_limit or (parsed.duration_limit_minutes if parsed else None),
        location=location,
        location_is_inferred=parsed.location_is_inferred if parsed else True,
        budget_amount=budget_amount,
        budget_kind=budget_kind,
        preferences=merged_preferences,
        exclusions=merged_exclusions,
        activity_types=[cat.value for cat in parsed.activity_types] if parsed else [],
        ambiguities=list(parsed.ambiguities) if parsed else [],
        provenance=dict(parsed.provenance) if parsed else {},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/plans", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def create_plan(body: CreatePlanRequest, current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> PlanRead:
    try:
        return PlanRead.from_plan(await service.create_plan(body.to_data(current_user.id)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/requests", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def create_plan_from_request(
    body: CreatePlanFromIntentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    understanding_engine: Annotated[PlanningUnderstandingPort, Depends(get_planning_understanding_service)],
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanRead:
    understanding = await understanding_engine.understand(current_user.id, body.request)
    plan = await service.create_plan_from_understanding(current_user.id, understanding)
    return PlanRead.from_plan(plan, understanding=understanding)


@router.post("/plans/{plan_id}/modifications", response_model=PlanRead)
async def modify_plan(
    plan_id: UUID,
    body: PlanModifyRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanRead:
    try:
        updated = await service.modify_plan(current_user.id, plan_id, body.request)
        return PlanRead.from_plan(updated)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plans/{plan_id}/adapt", response_model=PlanAdaptationRead)
async def adapt_plan(
    plan_id: UUID,
    body: PlanModifyRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    adaptation_service: Annotated[PlanAdaptationService, Depends(get_plan_adaptation_service)],
) -> PlanAdaptationRead:
    try:
        adaptation = await adaptation_service.propose_adaptation(current_user.id, plan_id, body.request)
        return PlanAdaptationRead.from_domain(adaptation)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plans/{plan_id}/adapt/apply", response_model=PlanRead)
async def apply_adaptation(
    plan_id: UUID,
    body: ApplyAdaptationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    adaptation_service: Annotated[PlanAdaptationService, Depends(get_plan_adaptation_service)],
) -> PlanRead:
    try:
        adaptation = await adaptation_service.propose_adaptation(current_user.id, plan_id, body.request)
        updated = await adaptation_service.apply_adaptation(current_user.id, plan_id, adaptation)
        return PlanRead.from_plan(updated)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



@router.get("/plans", response_model=list[PlanRead])
async def list_plans(current_user: Annotated[User, Depends(get_current_user)],
                     service: Annotated[PlanningService, Depends(get_planning_service)]) -> list[PlanRead]:
    return [PlanRead.from_plan(plan) for plan in await service.list_plans(current_user.id)]


@router.get("/plans/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: UUID, current_user: Annotated[User, Depends(get_current_user)],
                   service: Annotated[PlanningService, Depends(get_planning_service)]) -> PlanRead:
    try:
        return PlanRead.from_plan(await service.get_plan(current_user.id, plan_id))
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/plans/{plan_id}/recommendations", response_model=RecommendationResponse)
async def get_plan_recommendations(
    plan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlanningService, Depends(get_planning_service)],
    decision: Annotated[PlanningDecisionService, Depends(get_planning_decision_service)],
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
) -> RecommendationResponse:
    try:
        plan = await service.get_plan(current_user.id, plan_id)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc

    criteria = criteria_from_plan(plan)
    result = await decision.recommend(criteria)
    return RecommendationResponse(
        data_source=result.source,
        is_live=result.is_live,
        attribution=result.attribution,
        freshness=result.freshness,
        trade_off_summary=result.trade_off_summary,
        candidates=[DecisionCandidateRead.from_candidate(candidate) for candidate in result.candidates],
    )


@router.patch("/plans/{plan_id}", response_model=PlanRead)
async def update_plan(plan_id: UUID, body: PlanPatchRequest, current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> PlanRead:
    try:
        return PlanRead.from_plan(await service.update_plan(current_user.id, plan_id, body.to_changes()))
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(plan_id: UUID, current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> Response:
    try:
        await service.delete_plan(current_user.id, plan_id)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/plans/{plan_id}/items", response_model=PlanItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(plan_id: UUID, body: PlanItemCreateRequest, current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> PlanItemRead:
    try:
        return PlanItemRead.from_item(await service.create_item(current_user.id, plan_id, body.to_data()))
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plans/{plan_id}/items/from-option", response_model=PlanItemRead, status_code=status.HTTP_201_CREATED)
async def select_option(plan_id: UUID, body: SelectOptionRequest,
                        current_user: Annotated[User, Depends(get_current_user)],
                        service: Annotated[PlanSelectionService, Depends(get_plan_selection_service)]) -> PlanItemRead:
    try:
        item = await service.select_option(current_user.id, plan_id, body.option_id, body.option_type,
                                           position=body.position, start_time=body.start_time, end_time=body.end_time)
        return PlanItemRead.from_item(item)
    except (PlanningNotFoundError, OptionNotFoundError) as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plans/{plan_id}/items", response_model=list[PlanItemRead])
async def list_items(plan_id: UUID, current_user: Annotated[User, Depends(get_current_user)],
                     service: Annotated[PlanningService, Depends(get_planning_service)]) -> list[PlanItemRead]:
    try:
        return [PlanItemRead.from_item(item) for item in await service.list_items(current_user.id, plan_id)]
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/plans/{plan_id}/items/{item_id}", response_model=PlanItemRead)
async def update_item(plan_id: UUID, item_id: UUID, body: PlanItemPatchRequest,
                      current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> PlanItemRead:
    try:
        return PlanItemRead.from_item(await service.update_item(current_user.id, plan_id, item_id, body.to_changes()))
    except (PlanningNotFoundError, PlanItemNotFoundError) as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/plans/{plan_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(plan_id: UUID, item_id: UUID, current_user: Annotated[User, Depends(get_current_user)],
                      service: Annotated[PlanningService, Depends(get_planning_service)]) -> Response:
    try:
        await service.delete_item(current_user.id, plan_id, item_id)
    except (PlanningNotFoundError, PlanItemNotFoundError) as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/plans/{plan_id}/actions", response_model=PlanActionsRead)
async def get_plan_actions(
    plan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[PlanExecutionService, Depends(get_plan_execution_service)],
) -> PlanActionsRead:
    try:
        actions_data = await execution_service.get_plan_actions(current_user.id, plan_id)
        return PlanActionsRead(
            plan_id=actions_data.plan_id,
            plan_status=actions_data.plan_status,
            items=[
                PlanItemActionsRead(
                    item_id=item_acts.item_id,
                    item_name=item_acts.item_name,
                    item_status=item_acts.item_status,
                    actions=[ExecutionActionRead.from_domain(a) for a in item_acts.actions],
                )
                for item_acts in actions_data.items
            ],
        )
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/plans/{plan_id}/items/{item_id}/actions/execute", response_model=ExecutionResultRead)
async def execute_plan_action(
    plan_id: UUID,
    item_id: UUID,
    body: ExecuteActionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[PlanExecutionService, Depends(get_plan_execution_service)],
) -> ExecutionResultRead:
    try:
        result = await execution_service.execute_action(
            current_user.id, plan_id, item_id, body.action_type, body.target_url
        )
        return ExecutionResultRead.from_domain(result)
    except (PlanningNotFoundError, PlanItemNotFoundError) as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plans/{plan_id}/items/{item_id}/complete", response_model=PlanItemRead)
async def complete_item(
    plan_id: UUID,
    item_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[PlanExecutionService, Depends(get_plan_execution_service)],
) -> PlanItemRead:
    try:
        item = await execution_service.complete_item(current_user.id, plan_id, item_id)
        return PlanItemRead.from_item(item)
    except (PlanningNotFoundError, PlanItemNotFoundError) as exc:
        raise _not_found(exc) from exc


@router.post("/plans/{plan_id}/items/{item_id}/uncomplete", response_model=PlanItemRead)
async def uncomplete_item(
    plan_id: UUID,
    item_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[PlanExecutionService, Depends(get_plan_execution_service)],
) -> PlanItemRead:
    try:
        item = await execution_service.uncomplete_item(current_user.id, plan_id, item_id)
        return PlanItemRead.from_item(item)
    except (PlanningNotFoundError, PlanItemNotFoundError) as exc:
        raise _not_found(exc) from exc


@router.post("/plans/{plan_id}/health-check", response_model=PlanHealthCheckRead)
async def check_plan_health(
    plan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    live_service: Annotated[LiveIntelligenceService, Depends(get_live_intelligence_service)],
) -> PlanHealthCheckRead:
    try:
        result = await live_service.check_plan_health(current_user.id, plan_id)
        return PlanHealthCheckRead.from_domain(result)
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plans/{plan_id}/transitions", response_model=PlanTransitionsResponse)
async def get_plan_transitions(
    plan_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    planning_service: Annotated[PlanningService, Depends(get_planning_service)],
    mobility_service: Annotated[MobilityPlanningService, Depends(get_mobility_planning_service)],
) -> PlanTransitionsResponse:
    try:
        plan = await planning_service.get_plan(current_user.id, plan_id)
        preferred_modes = _preferred_modes_from_context(
            plan.context.transport_mode if plan.context else None
        )
        transitions = await mobility_service.evaluate_transitions(
            plan,
            party_size=plan.context.group_size if plan.context else 1,
            preferred_modes=preferred_modes or None,
        )
        feasibility = mobility_service.check_plan_feasibility(plan, transitions)
        return PlanTransitionsResponse(
            plan_id=plan.id,
            transitions=[PlanTransitionRead.from_domain(t) for t in transitions],
            feasibility=ItineraryFeasibilityRead.from_domain(feasibility),
        )
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/plans/{plan_id}/transitions/evaluate", response_model=PlanTransitionsResponse)
async def evaluate_plan_transitions(
    plan_id: UUID,
    body: EvaluateTransitionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    planning_service: Annotated[PlanningService, Depends(get_planning_service)],
    mobility_service: Annotated[MobilityPlanningService, Depends(get_mobility_planning_service)],
) -> PlanTransitionsResponse:
    try:
        plan = await planning_service.get_plan(current_user.id, plan_id)
        pref_modes: list[TransportMode] = []
        if body.preferred_modes:
            for m in body.preferred_modes:
                try:
                    pref_modes.append(TransportMode(m.lower()))
                except ValueError:
                    pass
        transitions = await mobility_service.evaluate_transitions(
            plan,
            party_size=body.party_size,
            preferred_modes=pref_modes or None,
        )
        feasibility = mobility_service.check_plan_feasibility(plan, transitions)
        return PlanTransitionsResponse(
            plan_id=plan.id,
            transitions=[PlanTransitionRead.from_domain(t) for t in transitions],
            feasibility=ItineraryFeasibilityRead.from_domain(feasibility),
        )
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/plans/{plan_id}/transitions/proposed", response_model=PlanTransitionsResponse)
async def evaluate_proposed_transitions(
    plan_id: UUID,
    body: ProposedTransitionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    planning_service: Annotated[PlanningService, Depends(get_planning_service)],
    mobility_service: Annotated[MobilityPlanningService, Depends(get_mobility_planning_service)],
) -> PlanTransitionsResponse:
    """Evaluate mobility across a proposed itinerary before any stop is saved.

    A proposal is assembled from ranked candidates and only persisted once the user
    confirms it, so the saved plan has no items to derive transitions from at this
    point. This endpoint takes the proposed stop sequence directly and reuses the
    same M15 evaluation the saved-plan path uses.
    """
    try:
        plan = await planning_service.get_plan(current_user.id, plan_id)

        pref_modes: list[TransportMode] = []
        if body.preferred_modes:
            for mode in body.preferred_modes:
                try:
                    pref_modes.append(TransportMode(mode.lower()))
                except ValueError:
                    continue
        if not pref_modes:
            pref_modes = _preferred_modes_from_context(
                plan.context.transport_mode if plan.context else None
            )

        transitions = await mobility_service.evaluate_stop_sequence(
            [stop.to_point() for stop in body.stops],
            party_size=body.party_size or (plan.context.group_size if plan.context else 1),
            preferred_modes=pref_modes or None,
        )

        # Budget/deadline feasibility is assessed against the real plan's constraints
        # combined with the proposed stops' own costs.
        proposed_plan = Plan(
            id=plan.id,
            user_id=current_user.id,
            intention=plan.intention,
            status=plan.status,
            context=plan.context,
            constraints=plan.constraints,
            items=[
                PlanItem(
                    plan_id=plan.id,
                    name=stop.name or stop.location,
                    item_type=PlanItemType.ACTIVITY,
                    location=stop.location,
                    start_time=stop.start_time,
                    end_time=stop.end_time,
                    estimated_cost=stop.estimated_cost,
                    position=idx,
                )
                for idx, stop in enumerate(body.stops)
            ],
        )
        feasibility = mobility_service.check_plan_feasibility(proposed_plan, transitions)

        return PlanTransitionsResponse(
            plan_id=plan.id,
            transitions=[PlanTransitionRead.from_domain(t) for t in transitions],
            feasibility=ItineraryFeasibilityRead.from_domain(feasibility),
        )
    except PlanningNotFoundError as exc:
        raise _not_found(exc) from exc

