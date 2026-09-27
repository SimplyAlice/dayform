from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Any
from uuid import UUID

from app.application.planning.dtos import ConstraintInput, CreatePlanData, PlanItemData, PlanningIntent
from app.application.planning.errors import PlanItemNotFoundError, PlanningNotFoundError
from app.application.planning.ports import PlanRepository
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.plan_item import PlanItem
from app.domain.entities.planning.understanding import BudgetKind, PlanningUnderstanding


class PlanningService:
    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository

    async def create_plan(self, data: CreatePlanData) -> Plan:
        plan = Plan(user_id=data.user_id, intention=data.intention, title=data.title)
        plan.replace_context(_context_from_data(plan.id, data))
        plan.replace_constraints(_constraints_from_inputs(plan.id, data.constraints or []))
        return await self._repository.create(plan)

    async def get_plan(self, user_id: UUID, plan_id: UUID) -> Plan:
        plan = await self._repository.get(plan_id, user_id)
        if plan is None:
            raise PlanningNotFoundError("Plan not found.")
        return plan

    async def list_plans(self, user_id: UUID) -> list[Plan]:
        return await self._repository.list_for_user(user_id)

    async def update_plan(self, user_id: UUID, plan_id: UUID, changes: dict[str, Any]) -> Plan:
        plan = await self.get_plan(user_id, plan_id)
        plan_changes = {key: value for key, value in changes.items() if key in {"intention", "title", "status"}}
        if plan_changes:
            plan.apply_patch(plan_changes)
        if "context" in changes:
            context_data = changes["context"]
            current = plan.context or PlanningContext(plan_id=plan.id)
            plan.replace_context(PlanningContext(
                plan_id=plan.id,
                location=context_data.get("location", current.location),
                start_time=context_data.get("start_time", current.start_time),
                end_time=context_data.get("end_time", current.end_time),
                group_size=context_data.get("group_size", current.group_size),
                transport_mode=context_data.get("transport_mode", current.transport_mode),
            ))
        if "constraints" in changes:
            constraints: list[ConstraintInput] = changes["constraints"]
            plan.replace_constraints(_constraints_from_inputs(plan.id, constraints))
        return await self._repository.update(plan)

    async def delete_plan(self, user_id: UUID, plan_id: UUID) -> None:
        plan = await self.get_plan(user_id, plan_id)
        plan.ensure_mutable()
        if not await self._repository.delete(plan_id, user_id):
            raise PlanningNotFoundError("Plan not found.")

    async def create_item(self, user_id: UUID, plan_id: UUID, data: PlanItemData) -> PlanItem:
        (await self.get_plan(user_id, plan_id)).ensure_mutable()
        position = 0 if data.position is None else data.position
        item = PlanItem(plan_id=plan_id, name=data.name, item_type=data.item_type, description=data.description,
                        start_time=data.start_time, end_time=data.end_time, estimated_cost=data.estimated_cost,
                        location=data.location, position=position)
        created = await self._repository.create_item(user_id, plan_id, item)
        if created is None:
            raise PlanningNotFoundError("Plan not found.")
        return created

    async def add_item(self, user_id: UUID, plan_id: UUID, item: PlanItem) -> PlanItem:
        """Persist an already-built PlanItem after enforcing plan mutability.

        Used by explicit selection flows. The PlanItem is authoritative
        input; this method only enforces aggregate rules and appends it.
        """
        if item.plan_id != plan_id:
            raise ValueError("Plan item belongs to another plan.")
        (await self.get_plan(user_id, plan_id)).ensure_mutable()
        created = await self._repository.create_item(user_id, plan_id, item)
        if created is None:
            raise PlanningNotFoundError("Plan not found.")
        return created

    async def list_items(self, user_id: UUID, plan_id: UUID) -> list[PlanItem]:
        items = await self._repository.list_items(user_id, plan_id)
        if items is None:
            raise PlanningNotFoundError("Plan not found.")
        return items

    async def update_item(self, user_id: UUID, plan_id: UUID, item_id: UUID, changes: dict[str, Any]) -> PlanItem:
        (await self.get_plan(user_id, plan_id)).ensure_mutable()
        item = await self._repository.get_item(user_id, plan_id, item_id)
        if item is None:
            raise PlanItemNotFoundError("Plan item not found.")
        item.apply_patch(changes)
        updated = await self._repository.update_item(user_id, plan_id, item)
        if updated is None:
            raise PlanItemNotFoundError("Plan item not found.")
        return updated

    async def delete_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> None:
        plan = await self.get_plan(user_id, plan_id)
        plan.ensure_mutable()
        if not await self._repository.delete_item(user_id, plan_id, item_id):
            raise PlanItemNotFoundError("Plan item not found.")

    async def create_plan_from_intent(self, intent: PlanningIntent) -> Plan:
        constraints: list[ConstraintInput] = []
        if intent.budget_max is not None:
            constraints.append(ConstraintInput(type=ConstraintType.BUDGET_MAX, value=f"R{intent.budget_max}", numeric_value=intent.budget_max))
        return await self.create_plan(CreatePlanData(user_id=intent.user_id, intention=intent.raw_request,
                                      location=intent.location, group_size=intent.group_size, constraints=constraints))

    async def create_plan_from_understanding(self, user_id: UUID, understanding: PlanningUnderstanding) -> Plan:
        constraints: list[ConstraintInput] = []
        if understanding.budget_amount is not None:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.BUDGET_MAX,
                    value=f"R{understanding.budget_amount}",
                    numeric_value=understanding.budget_amount,
                )
            )
        if understanding.people_count is not None:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.GROUP_SIZE,
                    value=str(understanding.people_count),
                    numeric_value=Decimal(understanding.people_count),
                )
            )
        for pref in understanding.preferences:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.PREFERENCE,
                    value=pref,
                )
            )
        if understanding.occasion:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.PREFERENCE,
                    value=f"occasion:{understanding.occasion}",
                )
            )
        for excl in understanding.exclusions:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"exclude:{excl}",
                )
            )
        for desc in understanding.semantic_descriptors:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.PREFERENCE,
                    value=f"descriptor:{desc}",
                )
            )
        if understanding.setting_preference:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"setting:{understanding.setting_preference}",
                )
            )
        if understanding.weather_context:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"weather:{understanding.weather_context}",
                )
            )
        if understanding.date_spec:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"date:{understanding.date_spec}",
                )
            )
        if understanding.time_window:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"time:{understanding.time_window}",
                )
            )
        if understanding.start_time:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"start_time:{understanding.start_time}",
                )
            )
        if understanding.end_time:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"end_time:{understanding.end_time}",
                )
            )
        if understanding.duration_limit_minutes:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.TIME_MAX,
                    value=f"{understanding.duration_limit_minutes}m",
                    numeric_value=Decimal(understanding.duration_limit_minutes),
                )
            )
        if understanding.deadline:
            constraints.append(
                ConstraintInput(
                    type=ConstraintType.REQUIREMENT,
                    value=f"deadline:{understanding.deadline}",
                )
            )
        if understanding.budget_model:
            if understanding.budget_model.stretch_amount is not None:
                constraints.append(
                    ConstraintInput(
                        type=ConstraintType.REQUIREMENT,
                        value=f"budget_stretch:{understanding.budget_model.stretch_amount}",
                        numeric_value=understanding.budget_model.stretch_amount,
                    )
                )
            if understanding.budget_model.priority_note:
                constraints.append(
                    ConstraintInput(
                        type=ConstraintType.PREFERENCE,
                        value=f"budget_priority:{understanding.budget_model.priority_note}",
                    )
                )

        start_dt = _resolve_iso_datetime(understanding.date_spec, understanding.start_time)
        end_dt = _resolve_iso_datetime(understanding.date_spec, understanding.end_time)

        group_size = understanding.people_count if understanding.people_count is not None else 1
        title = _generate_plan_title(understanding)
        return await self.create_plan(
            CreatePlanData(
                user_id=user_id,
                intention=understanding.raw_request,
                title=title,
                location=understanding.location,
                start_time=start_dt,
                end_time=end_dt,
                group_size=group_size,
                transport_mode=understanding.transport_mode,
                constraints=constraints,
            )
        )

    async def modify_plan(self, user_id: UUID, plan_id: UUID, modification_request: str) -> Plan:
        plan = await self.get_plan(user_id, plan_id)
        plan.ensure_mutable()

        mod_lower = modification_request.strip().lower()
        current_constraints = list(plan.constraints)
        current_context = plan.context or PlanningContext(plan_id=plan.id)

        new_constraints: list[ConstraintInput] = [
            ConstraintInput(type=c.type, value=c.value, numeric_value=c.numeric_value)
            for c in current_constraints
        ]
        new_group_size = current_context.group_size
        new_location = current_context.location

        # 1. Cheaper / Lower budget
        if any(term in mod_lower for term in ("cheaper", "lower budget", "less expensive", "make it cheap")):
            budget_idx = next(
                (i for i, c in enumerate(new_constraints) if c.type is ConstraintType.BUDGET_MAX),
                None,
            )
            if budget_idx is not None and new_constraints[budget_idx].numeric_value is not None:
                old_val = new_constraints[budget_idx].numeric_value
                new_val = Decimal(int(old_val * Decimal("0.70")))
                if new_val < Decimal("100"):
                    new_val = Decimal("100")
                new_constraints[budget_idx] = ConstraintInput(
                    type=ConstraintType.BUDGET_MAX,
                    value=f"R{new_val}",
                    numeric_value=new_val,
                )
            else:
                new_constraints.append(
                    ConstraintInput(
                        type=ConstraintType.BUDGET_MAX,
                        value="R300",
                        numeric_value=Decimal("300"),
                    )
                )
            if not any(c.value == "affordable" for c in new_constraints if c.type is ConstraintType.PREFERENCE):
                new_constraints.append(
                    ConstraintInput(type=ConstraintType.PREFERENCE, value="affordable")
                )

        # 2. Exclude outdoors
        if any(term in mod_lower for term in ("no outdoor", "no outdoors", "nothing outdoors", "indoor only", "not outdoor")):
            if not any(c.value == "exclude:no_outdoors" for c in new_constraints):
                new_constraints.append(
                    ConstraintInput(type=ConstraintType.REQUIREMENT, value="exclude:no_outdoors")
                )
            new_constraints = [c for c in new_constraints if c.value not in {"outdoors", "nature"}]

        # 3. Exclude fancy
        if any(term in mod_lower for term in ("nothing too fancy", "not too fancy", "no fancy")):
            if not any(c.value == "exclude:not_too_fancy" for c in new_constraints):
                new_constraints.append(
                    ConstraintInput(type=ConstraintType.REQUIREMENT, value="exclude:not_too_fancy")
                )
            new_constraints = [c for c in new_constraints if c.value != "fancy"]

        # 4. Group size adjustments
        add_match = re.search(r"\badd\s+(\d+)\s+(?:more\s+)?people\b", mod_lower)
        if add_match:
            new_group_size += int(add_match.group(1))
        else:
            set_match = re.search(r"\b(?:for|now|make it)\s+(\d+)\s+people\b", mod_lower)
            if set_match:
                new_group_size = int(set_match.group(1))

        new_constraints = [c for c in new_constraints if c.type is not ConstraintType.GROUP_SIZE]
        new_constraints.append(
            ConstraintInput(
                type=ConstraintType.GROUP_SIZE,
                value=str(new_group_size),
                numeric_value=Decimal(new_group_size),
            )
        )

        # 5. Date adjustment
        for day in ("saturday", "sunday", "friday", "thursday", "wednesday", "tuesday", "monday"):
            if re.search(rf"\b(?:make it|change to|actually|on)\s+{day}\b", mod_lower):
                new_constraints = [
                    c for c in new_constraints
                    if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("date:"))
                ]
                new_constraints.append(
                    ConstraintInput(type=ConstraintType.REQUIREMENT, value=f"date:{day.capitalize()}")
                )
                break

        # 6. Start time modifications: "make it start later", "start around 1pm", "start at 13:00"
        m_start_later = re.search(r"\b(?:start\s+later|make\s+it\s+start\s+later|move\s+later)\b", mod_lower)
        m_new_start = re.search(r"\b(?:start\s+(?:at|around)\s+|at\s+)(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b", mod_lower)
        if m_new_start:
            new_time_val = m_new_start.group(1)
            mer = m_new_start.group(2)
            parsed_start = DeterministicUnderstandingEngine._normalize_clock_time(new_time_val, mer)
            new_constraints = [c for c in new_constraints if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:"))]
            new_constraints.append(ConstraintInput(type=ConstraintType.REQUIREMENT, value=f"start_time:{parsed_start}"))
        elif m_start_later:
            curr_start_c = next((c for c in new_constraints if c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:")), None)
            if curr_start_c:
                try:
                    curr_time = curr_start_c.value.split(":", 1)[1]
                    curr_h = int(curr_time.split(":")[0])
                    shifted_h = min(22, curr_h + 2)
                    shifted_time = f"{shifted_h:02d}:00"
                except Exception:
                    shifted_time = "13:00"
            else:
                shifted_time = "13:00"
            new_constraints = [c for c in new_constraints if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:"))]
            new_constraints.append(ConstraintInput(type=ConstraintType.REQUIREMENT, value=f"start_time:{shifted_time}"))

        # 7. End time / deadline modifications: "home by 6", "need to be home by 6", "be home by 7", "until 5"
        m_deadline = re.search(r"\b(?:home\s+by|be\s+home\s+by|need\s+to\s+be\s+home\s+by|finish\s+by|until)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b", mod_lower)
        if m_deadline:
            end_val = m_deadline.group(1)
            end_mer = m_deadline.group(2)
            parsed_end = DeterministicUnderstandingEngine._normalize_clock_time(end_val, end_mer, is_deadline=True)
            new_constraints = [c for c in new_constraints if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("end_time:"))]
            new_constraints.append(ConstraintInput(type=ConstraintType.REQUIREMENT, value=f"end_time:{parsed_end}"))

        # 8. Duration limit modifications: "only have 3 hours", "we only have three hours", "have 2 hours"
        m_mod_dur = re.search(r"\b(?:only\s+have|have|limit\s+to)\s+(\d+|one|two|three|four|five)\s+hours?\b", mod_lower)
        if m_mod_dur:
            dur_word = m_mod_dur.group(1).lower()
            num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
            dur_hrs = num_map.get(dur_word) or (int(dur_word) if dur_word.isdigit() else 3)
            dur_mins = dur_hrs * 60
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.TIME_MAX]
            new_constraints.append(ConstraintInput(type=ConstraintType.TIME_MAX, value=f"{dur_mins}m", numeric_value=Decimal(dur_mins)))

        start_c = next((c for c in new_constraints if c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:")), None)
        end_c = next((c for c in new_constraints if c.type is ConstraintType.REQUIREMENT and c.value.startswith("end_time:")), None)
        date_c = next((c for c in new_constraints if c.type is ConstraintType.REQUIREMENT and c.value.startswith("date:")), None)
        day_spec = date_c.value.split(":", 1)[1] if date_c else None

        new_start_dt = _resolve_iso_datetime(day_spec, start_c.value.split(":", 1)[1] if start_c else None) or current_context.start_time
        new_end_dt = _resolve_iso_datetime(day_spec, end_c.value.split(":", 1)[1] if end_c else None) or current_context.end_time

        plan.replace_context(
            PlanningContext(
                plan_id=plan.id,
                location=new_location,
                start_time=new_start_dt,
                end_time=new_end_dt,
                group_size=new_group_size,
                transport_mode=current_context.transport_mode,
            )
        )
        # Synchronize plan title with updated budget, date, or time
        budget_c = next((c for c in new_constraints if c.type is ConstraintType.BUDGET_MAX), None)
        base_title = plan.title.split(" · ")[0] if plan.title else "Plan"
        if budget_c and budget_c.numeric_value:
            plan.title = f"{base_title} · ~R{budget_c.numeric_value}"
        elif date_c and start_c:
            plan.title = f"{base_title} · {date_c.value.split(':', 1)[1]} ~{start_c.value.split(':', 1)[1]}"
        elif date_c:
            plan.title = f"{base_title} · {date_c.value.split(':', 1)[1]}"


        plan.replace_constraints(_constraints_from_inputs(plan.id, new_constraints))
        return await self._repository.update(plan)


def _generate_plan_title(understanding: PlanningUnderstanding) -> str:
    loc = understanding.location or "Cape Town"
    if understanding.occasion == "date":
        partner = understanding.relationship_context or "couple"
        if partner in {"boyfriend", "girlfriend", "partner", "husband", "wife"}:
            who = f"Date with {partner.capitalize()}"
        else:
            who = "Date for 2"
    elif understanding.occasion == "birthday":
        if understanding.relationship_context in {"mom", "mother", "dad", "father", "friend", "partner"}:
            who = f"Birthday for {understanding.relationship_context.capitalize()}"
        else:
            who = "Birthday Celebration"
    elif understanding.occasion == "friends":
        who = "Outing with Friends"
    elif understanding.occasion == "solo":
        who = "Solo Exploration"
    else:
        who = "Day Out"

    if understanding.budget_amount is not None:
        amount_str = f"R{understanding.budget_amount}"
        if understanding.budget_kind == BudgetKind.HARD_MAX:
            budget_str = f"Under {amount_str}"
        elif understanding.budget_kind == BudgetKind.APPROXIMATE:
            budget_str = f"~{amount_str}"
        else:
            budget_str = amount_str
        return f"{loc} {who} · {budget_str}"

    if understanding.date_spec:
        return f"{loc} {who} · {understanding.date_spec}"

    return f"{loc} {who}"


def _context_from_data(plan_id: UUID, data: CreatePlanData) -> PlanningContext:
    return PlanningContext(plan_id=plan_id, location=data.location, start_time=data.start_time, end_time=data.end_time,
                           group_size=data.group_size, transport_mode=data.transport_mode)


def _constraints_from_inputs(plan_id: UUID, inputs: list[ConstraintInput]) -> list[Constraint]:
    return [Constraint(plan_id=plan_id, type=item.type, value=item.value, numeric_value=item.numeric_value) for item in inputs]


def _resolve_iso_datetime(date_str: str | None, time_str: str | None) -> datetime | None:
    if not time_str:
        return None
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
    except Exception:
        return None

    # Base reference date: 2026-09-26 is a Saturday
    weekday_offsets = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    base_year, base_month, base_day = 2026, 9, 21  # 2026-09-21 was Monday
    if date_str:
        clean_date = date_str.lower().strip()
        offset = weekday_offsets.get(clean_date)
        if offset is not None:
            day = base_day + offset
            return datetime(base_year, base_month, day, hour, minute)
    return datetime(2026, 9, 26, hour, minute)
