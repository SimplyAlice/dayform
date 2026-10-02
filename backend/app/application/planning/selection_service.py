"""Explicit "select a candidate and add it to my plan" operation.

This service is the only place where a decision candidate becomes a
persisted `PlanItem`. Nothing here runs automatically: a caller must
choose an option. Candidate data is never trusted from the client — the
option is re-fetched from the information layer and re-evaluated so the
PlanItem is built from authoritative values.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.application.planning.errors import OptionNotFoundError
from app.application.planning.information import PlanningInformationService
from app.application.planning.planning_service import PlanningService
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.decision import CandidateType, DecisionCandidate, DecisionCriteria
from app.domain.entities.planning.decision_engine import evaluate_activity, evaluate_place
from app.domain.entities.planning.information import InformationCategory
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.plan_item import PlanItem
from app.domain.entities.planning.plan_item_conversion import candidate_to_plan_item


class PlanSelectionService:
    """Adds an explicitly selected option to a plan as a PlanItem."""

    def __init__(self, plans: PlanningService, information: PlanningInformationService) -> None:
        self._plans = plans
        self._information = information

    async def select_option(
        self,
        user_id: UUID,
        plan_id: UUID,
        option_id: UUID,
        option_type: CandidateType,
        *,
        position: int | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> PlanItem:
        # Ownership and existence are enforced by the existing service, which
        # raises the same not-found error for missing and foreign plans so a
        # private plan's existence is never leaked.
        plan = await self._plans.get_plan(user_id, plan_id)
        plan.ensure_mutable()

        candidate = await self._resolve_candidate(option_id, option_type, plan)

        if end_time is None and start_time is not None and candidate.duration_minutes is not None:
            end_time = start_time + timedelta(minutes=candidate.duration_minutes)

        item = candidate_to_plan_item(
            candidate,
            plan_id=plan_id,
            position=position if position is not None else _next_position(plan.items),
            start_time=start_time,
            end_time=end_time,
        )
        return await self._plans.add_item(user_id, plan_id, item)

    async def _resolve_candidate(
        self, option_id: UUID, option_type: CandidateType, plan: Plan
    ) -> DecisionCandidate:
        criteria = criteria_from_plan(plan)
        if option_type is CandidateType.PLACE:
            place = await self._information.get_place(option_id)
            if place is None:
                raise OptionNotFoundError("Option not found.")
            return evaluate_place(place, criteria)
        if option_type is CandidateType.ACTIVITY:
            activity = await self._information.get_activity(option_id)
            if activity is None:
                raise OptionNotFoundError("Option not found.")
            return evaluate_activity(activity, criteria)
        raise OptionNotFoundError("Option not found.")


def criteria_from_plan(plan: Plan) -> DecisionCriteria:
    """Derive decision criteria from the plan's existing context/constraints.

    Reuses the plan's own location, group size, category, budget/duration,
    preferences, exclusions, occasion, and temporal constraints.
    """
    location = plan.context.location if plan.context is not None else None
    return DecisionCriteria(
        location=location,
        category=_category_from_constraints(plan.constraints),
        maximum_cost=_budget_maximum(plan.constraints),
        group_size=_group_size(plan),
        maximum_duration_minutes=_duration_maximum(plan.constraints),
        occasion=_occasion_from_constraints(plan.constraints),
        preferences=_preferences_from_constraints(plan.constraints),
        exclusions=_exclusions_from_constraints(plan.constraints),
        experience_requirements=_experience_requirements_from_constraints(plan.constraints),
        semantic_descriptors=_semantic_descriptors_from_constraints(plan.constraints),
        setting_preference=_setting_preference_from_constraints(plan.constraints),
        weather_context=_weather_context_from_constraints(plan.constraints),
        day_of_week=_day_of_week_from_constraints(plan),
        start_time=_start_time_from_constraints(plan),
        end_time=_end_time_from_constraints(plan),
        deadline=_deadline_from_constraints(plan),
        time_window=_time_window_from_constraints(plan),
        duration_limit_minutes=_duration_limit_from_constraints(plan),
        stretch_amount=_stretch_amount_from_constraints(plan),
        priority_note=_priority_note_from_constraints(plan),
    )


def _day_of_week_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("date:"):
            return constraint.value.split(":", 1)[1]
    if plan.context and plan.context.start_time:
        return plan.context.start_time.strftime("%A")
    return None


def _start_time_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("start_time:"):
            return constraint.value.split(":", 1)[1]
    if plan.context and plan.context.start_time:
        return plan.context.start_time.strftime("%H:%M")
    return None


def _end_time_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("end_time:"):
            return constraint.value.split(":", 1)[1]
    if plan.context and plan.context.end_time:
        return plan.context.end_time.strftime("%H:%M")
    return None


def _deadline_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("deadline:"):
            return constraint.value.split(":", 1)[1]
    return None


def _stretch_amount_from_constraints(plan: Plan) -> Decimal | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("budget_stretch:"):
            return constraint.numeric_value
    return None


def _priority_note_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.PREFERENCE and constraint.value.startswith("budget_priority:"):
            return constraint.value.split(":", 1)[1]
    return None


def _time_window_from_constraints(plan: Plan) -> str | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("time:"):
            return constraint.value.split(":", 1)[1]
    return None


def _duration_limit_from_constraints(plan: Plan) -> int | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.TIME_MAX:
            if constraint.numeric_value is not None:
                return int(constraint.numeric_value)
            digits = "".join(filter(str.isdigit, constraint.value))
            if digits:
                return int(digits)
    return None


def _occasion_from_constraints(constraints: list[Constraint]) -> str | None:
    for constraint in constraints:
        if constraint.type is ConstraintType.PREFERENCE and constraint.value.startswith("occasion:"):
            return constraint.value.split(":", 1)[1]
    return None


def _preferences_from_constraints(constraints: list[Constraint]) -> tuple[str, ...]:
    prefs: list[str] = []
    for constraint in constraints:
        if constraint.type is ConstraintType.PREFERENCE and not constraint.value.startswith("occasion:"):
            prefs.append(constraint.value)
    return tuple(prefs)


def _exclusions_from_constraints(constraints: list[Constraint]) -> tuple[str, ...]:
    exclusions: list[str] = []
    for constraint in constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("exclude:"):
            exclusions.append(constraint.value.split(":", 1)[1])
    return tuple(exclusions)


def _experience_requirements_from_constraints(constraints: list[Constraint]) -> tuple[str, ...]:
    reqs: list[str] = []
    for constraint in constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("requirement:"):
            reqs.append(constraint.value.split(":", 1)[1])
    return tuple(reqs)


def _semantic_descriptors_from_constraints(constraints: list[Constraint]) -> tuple[str, ...]:
    descs: list[str] = []
    for constraint in constraints:
        if constraint.type is ConstraintType.PREFERENCE and constraint.value.startswith("descriptor:"):
            descs.append(constraint.value.split(":", 1)[1])
    return tuple(descs)


def _setting_preference_from_constraints(constraints: list[Constraint]) -> str | None:
    for constraint in constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("setting:"):
            return constraint.value.split(":", 1)[1]
    return None


def _weather_context_from_constraints(constraints: list[Constraint]) -> str | None:
    for constraint in constraints:
        if constraint.type is ConstraintType.REQUIREMENT and constraint.value.startswith("weather:"):
            return constraint.value.split(":", 1)[1]
    return None


def _category_from_constraints(constraints: list[Constraint]) -> InformationCategory | None:
    for constraint in constraints:
        try:
            return InformationCategory(constraint.value.strip().lower())
        except ValueError:
            continue
    return None


def _group_size(plan: Plan) -> int | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.GROUP_SIZE:
            if constraint.numeric_value is not None:
                return int(constraint.numeric_value)
            if constraint.value.isdigit():
                return int(constraint.value)
    if plan.context is not None:
        return plan.context.group_size
    return None


def _duration_maximum(constraints: list[Constraint]) -> int | None:
    for constraint in constraints:
        if constraint.type is ConstraintType.TIME_MAX:
            if constraint.numeric_value is not None:
                return int(constraint.numeric_value)
            if constraint.value.isdigit():
                return int(constraint.value)
    return None


def _budget_maximum(constraints: list[Constraint]) -> Decimal | None:
    for constraint in constraints:
        if constraint.type is ConstraintType.BUDGET_MAX and constraint.numeric_value is not None:
            return constraint.numeric_value
    return None


def _next_position(items: list[PlanItem]) -> int:
    return max((item.position for item in items), default=-1) + 1
