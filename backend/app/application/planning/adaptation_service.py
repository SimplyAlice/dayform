from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import re
from typing import Any
from uuid import UUID

from app.application.planning.decision_service import PlanningDecisionService
from app.application.planning.errors import OptionNotFoundError, PlanningNotFoundError
from app.application.planning.information import OptionSearchCriteria, PlanningInformationService
from app.application.planning.planning_service import PlanningService
from app.application.planning.selection_service import criteria_from_plan
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.domain.entities.planning.adaptation import (
    ChangeType,
    ItemAction,
    ItemDiff,
    PlanAdaptation,
)
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.decision import (
    CandidateType,
    DecisionCandidate,
    DecisionCriteria,
    ReasonOutcome,
    ReasonType,
)
from app.domain.entities.planning.decision_engine import evaluate_activity, evaluate_place
from app.domain.entities.planning.information import Activity, InformationCategory, Place
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.plan_item import PlanItem, PlanItemType
from app.domain.entities.planning.plan_item_conversion import candidate_to_plan_item


class PlanAdaptationService:
    """Intelligently adapts an existing plan when constraints or circumstances change.

    Applies the Minimal Change Principle:
    - Identifies what changed in natural language
    - Re-evaluates existing items against the new constraints
    - Preserves valid, user-approved items in place
    - Replaces or removes only invalidated items
    - Sequentially reschedules items to respect clock times, deadlines, and opening hours
    - Detects impossible schedules and cleanly scales down rather than fabricating impossible plans
    """

    def __init__(
        self,
        planning_service: PlanningService,
        decision_service: PlanningDecisionService,
        information_service: PlanningInformationService,
    ) -> None:
        self._planning_service = planning_service
        self._decision_service = decision_service
        self._information_service = information_service

    async def propose_adaptation(
        self, user_id: UUID, plan_id: UUID, modification_text: str
    ) -> PlanAdaptation:
        plan = await self._planning_service.get_plan(user_id, plan_id)
        plan.ensure_mutable()

        # 1. Detect changes from modification text
        (
            updated_context,
            updated_constraints,
            changes_detected,
            change_details,
        ) = self._detect_changes(plan, modification_text)

        # 2. Build DecisionCriteria for the updated constraints
        probe_plan = Plan(
            id=plan.id,
            user_id=user_id,
            intention=plan.intention,
            context=updated_context,
            constraints=updated_constraints,
            items=list(plan.items),
        )
        new_criteria = criteria_from_plan(probe_plan)

        # 3. Query candidate recommendations from decision service
        recs_result = await self._decision_service.recommend(new_criteria)
        eligible_candidates = [c for c in recs_result.candidates if c.is_eligible]

        # 4. Re-evaluate existing items against the new criteria
        orig_items = list(plan.items)
        orig_items.sort(key=lambda i: i.position)
        orig_total_cost = sum(
            (i.estimated_cost for i in orig_items if i.estimated_cost is not None),
            start=Decimal("0"),
        )

        invalidated_item_ids: set[UUID] = set()
        item_invalidation_reasons: dict[UUID, str] = {}

        for item in orig_items:
            is_valid, reason = self._evaluate_item_validity(
                item, new_criteria, change_details
            )
            if not is_valid:
                invalidated_item_ids.add(item.id)
                item_invalidation_reasons[item.id] = reason

        # 5. Determine time window and available slots
        base_date = (
            updated_context.start_time.date()
            if updated_context.start_time
            else (plan.context.start_time.date() if plan.context and plan.context.start_time else datetime(2026, 9, 26).date())
        )
        start_time_obj = (
            updated_context.start_time.time()
            if updated_context.start_time
            else (plan.context.start_time.time() if plan.context and plan.context.start_time else datetime.strptime("11:00", "%H:%M").time())
        )
        current_dt = datetime.combine(base_date, start_time_obj)

        deadline_dt: datetime | None = None
        if updated_context.end_time:
            deadline_dt = datetime.combine(base_date, updated_context.end_time.time())

        duration_limit_mins = new_criteria.duration_limit_minutes
        if duration_limit_mins is not None:
            limit_end_dt = current_dt + timedelta(minutes=duration_limit_mins)
            if deadline_dt is None or limit_end_dt < deadline_dt:
                deadline_dt = limit_end_dt

        # Calculate max stops that can physically fit
        max_allowed_stops: int | None = None
        if deadline_dt is not None:
            total_window_mins = int((deadline_dt - current_dt).total_seconds() // 60)
            if total_window_mins <= 0:
                max_allowed_stops = 0
            elif total_window_mins <= 75:
                max_allowed_stops = 1
            elif total_window_mins <= 150:
                max_allowed_stops = 2
            else:
                max_allowed_stops = None

        # 6. Minimal change: preserve valid items and find replacements for invalidated items
        diffs: list[ItemDiff] = []
        adapted_items: list[PlanItem] = []
        used_names: set[str] = set()

        # First pass: keep valid items
        kept_items: list[PlanItem] = []
        for item in orig_items:
            if item.id not in invalidated_item_ids:
                kept_items.append(item)
                used_names.add(item.name.lower())

        # Check budget constraint
        max_budget = new_criteria.maximum_cost

        # Second pass: assemble final items respecting sequence and time window
        scheduled_count = 0
        running_cost = Decimal("0")

        for item in orig_items:
            is_invalidated = item.id in invalidated_item_ids
            invalidation_reason = item_invalidation_reasons.get(item.id, "Invalidated by updated constraints")

            # Check if this stop exceeds the allowed window
            if max_allowed_stops is not None and scheduled_count >= max_allowed_stops:
                diffs.append(
                    ItemDiff(
                        action=ItemAction.REMOVED,
                        original_item_id=item.id,
                        original_name=item.name,
                        original_start_time=item.start_time,
                        original_end_time=item.end_time,
                        original_cost=item.estimated_cost,
                        location=item.location,
                        item_type=item.item_type,
                        reason=f"Removed: Cannot fit within the {duration_limit_mins or total_window_mins}-minute duration limit without creating an impossible schedule.",
                    )
                )
                continue

            if not is_invalidated:
                # Retain valid item
                item_duration = item.duration_minutes or 60
                item_start = current_dt
                item_end = current_dt + timedelta(minutes=item_duration)

                # Determine if time shifted
                time_shifted = (
                    item.start_time is None
                    or item.start_time.strftime("%H:%M") != item_start.strftime("%H:%M")
                )
                action = ItemAction.RESCHEDULED if time_shifted else ItemAction.KEPT
                reason_text = (
                    f"Rescheduled: start time shifted to {item_start.strftime('%H:%M')}"
                    if time_shifted
                    else "Preserved from original plan"
                )

                adapted_item = PlanItem(
                    plan_id=plan.id,
                    name=item.name,
                    item_type=item.item_type,
                    description=item.description,
                    start_time=item_start,
                    end_time=item_end,
                    estimated_cost=item.estimated_cost,
                    location=item.location,
                    position=scheduled_count,
                )
                adapted_items.append(adapted_item)
                scheduled_count += 1
                current_dt = item_end + timedelta(minutes=15)
                if item.estimated_cost:
                    running_cost += item.estimated_cost

                diffs.append(
                    ItemDiff(
                        action=action,
                        original_item_id=item.id,
                        original_name=item.name,
                        new_name=item.name,
                        original_start_time=item.start_time,
                        new_start_time=item_start,
                        original_end_time=item.end_time,
                        new_end_time=item_end,
                        original_cost=item.estimated_cost,
                        new_cost=item.estimated_cost,
                        location=item.location,
                        item_type=item.item_type,
                        reason=reason_text,
                    )
                )
            else:
                # Invalidated item: find replacement candidate
                replacement = self._find_replacement_candidate(
                    item=item,
                    candidates=eligible_candidates,
                    used_names=used_names,
                    max_remaining_budget=(max_budget - running_cost) if max_budget else None,
                    new_criteria=new_criteria,
                )

                if replacement is not None:
                    used_names.add(replacement.name.lower())
                    rep_duration = replacement.duration_minutes or 60
                    rep_start = current_dt
                    rep_end = current_dt + timedelta(minutes=rep_duration)

                    new_plan_item = candidate_to_plan_item(
                        replacement,
                        plan_id=plan.id,
                        position=scheduled_count,
                        start_time=rep_start,
                        end_time=rep_end,
                    )
                    adapted_items.append(new_plan_item)
                    scheduled_count += 1
                    current_dt = rep_end + timedelta(minutes=15)
                    if new_plan_item.estimated_cost:
                        running_cost += new_plan_item.estimated_cost

                    diffs.append(
                        ItemDiff(
                            action=ItemAction.REPLACED,
                            original_item_id=item.id,
                            original_name=item.name,
                            new_name=replacement.name,
                            original_start_time=item.start_time,
                            new_start_time=rep_start,
                            original_end_time=item.end_time,
                            new_end_time=rep_end,
                            original_cost=item.estimated_cost,
                            new_cost=new_plan_item.estimated_cost,
                            location=new_plan_item.location,
                            item_type=new_plan_item.item_type,
                            reason=f"Replaced: {invalidation_reason}; chosen {replacement.name} as alternative",
                            candidate_option_id=replacement.option_id,
                            candidate_option_type=replacement.option_type,
                        )
                    )
                else:
                    # No compatible replacement available: item is removed
                    diffs.append(
                        ItemDiff(
                            action=ItemAction.REMOVED,
                            original_item_id=item.id,
                            original_name=item.name,
                            original_start_time=item.start_time,
                            original_end_time=item.end_time,
                            original_cost=item.estimated_cost,
                            location=item.location,
                            item_type=item.item_type,
                            reason=f"Removed: {invalidation_reason} (no suitable alternative found)",
                        )
                    )

        # Budget reduction post-check: if total cost still exceeds max_budget, substitute the highest cost item
        if max_budget is not None and running_cost > max_budget:
            running_cost = self._adjust_for_budget_overage(
                adapted_items=adapted_items,
                diffs=diffs,
                candidates=eligible_candidates,
                used_names=used_names,
                max_budget=max_budget,
            )

        new_total_cost = sum(
            (i.estimated_cost for i in adapted_items if i.estimated_cost is not None),
            start=Decimal("0"),
        )
        budget_delta = new_total_cost - orig_total_cost if orig_items else None

        # Build narrative summary
        narrative_summary = self._build_narrative_summary(
            changes_detected=changes_detected,
            diffs=diffs,
            new_start_time=updated_context.start_time,
            new_budget_max=max_budget,
            max_allowed_stops=max_allowed_stops,
        )

        is_feasible = len(adapted_items) > 0 or max_allowed_stops == 0
        feasibility_note: str | None = None
        if max_allowed_stops is not None and max_allowed_stops < len(orig_items):
            feasibility_note = f"Plan scaled down to {len(adapted_items)} stop(s) to fit realistically within your time limit without fabricating an impossible schedule."

        adaptation_start = adapted_items[0].start_time if adapted_items else updated_context.start_time
        adaptation_end = adapted_items[-1].end_time if adapted_items else updated_context.end_time

        return PlanAdaptation(
            plan_id=plan.id,
            changes_detected=changes_detected,
            narrative_summary=narrative_summary,
            diffs=diffs,
            adapted_items=adapted_items,
            new_start_time=adaptation_start,
            new_end_time=adaptation_end,
            new_total_cost=new_total_cost,
            budget_delta=budget_delta,
            is_feasible=is_feasible,
            feasibility_note=feasibility_note,
        )

    async def apply_adaptation(
        self, user_id: UUID, plan_id: UUID, adaptation: PlanAdaptation
    ) -> Plan:
        plan = await self._planning_service.get_plan(user_id, plan_id)
        plan.ensure_mutable()

        # 1. Remove all old items
        for old_item in list(plan.items):
            await self._planning_service.delete_item(user_id, plan_id, old_item.id)

        # 2. Add adapted items
        for position, item in enumerate(adaptation.adapted_items):
            item.position = position
            item.plan_id = plan_id
            await self._planning_service.add_item(user_id, plan_id, item)

        # 3. Update plan context
        new_context = PlanningContext(
            plan_id=plan.id,
            location=plan.context.location if plan.context else None,
            start_time=adaptation.new_start_time or (plan.context.start_time if plan.context else None),
            end_time=adaptation.new_end_time or (plan.context.end_time if plan.context else None),
            group_size=plan.context.group_size if plan.context else 1,
            transport_mode=plan.context.transport_mode if plan.context else None,
        )
        plan.replace_context(new_context)

        # 4. Synchronize constraints & title
        updated_constraints = list(plan.constraints)
        if adaptation.new_start_time:
            time_str = adaptation.new_start_time.strftime("%H:%M")
            updated_constraints = [
                c for c in updated_constraints
                if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:"))
            ]
            updated_constraints.append(
                Constraint(
                    plan_id=plan.id,
                    type=ConstraintType.REQUIREMENT,
                    value=f"start_time:{time_str}",
                )
            )

        if adaptation.new_total_cost > Decimal("0"):
            base_title = plan.title.split(" · ")[0] if plan.title else "Plan"
            plan.title = f"{base_title} · R{adaptation.new_total_cost:.0f}"

        plan.replace_constraints(updated_constraints)
        return await self._planning_service._repository.update(plan)

    def _detect_changes(
        self, plan: Plan, text: str
    ) -> tuple[PlanningContext, list[Constraint], list[ChangeType], dict[str, Any]]:
        lower = text.strip().lower()
        changes_detected: list[ChangeType] = []
        change_details: dict[str, Any] = {}

        curr_context = plan.context or PlanningContext(plan_id=plan.id)
        new_location = curr_context.location
        new_start_time = curr_context.start_time
        new_end_time = curr_context.end_time
        new_group_size = curr_context.group_size

        new_constraints: list[Constraint] = [
            Constraint(plan_id=plan.id, type=c.type, value=c.value, numeric_value=c.numeric_value)
            for c in plan.constraints
        ]

        # 1. Start Time Shift
        # Matches: "can only leave at 2", "only leave at 2pm", "leave at 14:00", "start at 2", "start around 2pm", "start later"
        m_start_explicit = re.search(
            r"\b(?:can\s+only\s+leave\s+at|only\s+leave\s+at|leave\s+at|leaving\s+at|start\s+(?:at|around)\s+|at\s+)(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b",
            lower,
        )
        m_start_later = re.search(
            r"\b(?:start\s+later|make\s+it\s+start\s+later|move\s+later)\b", lower
        )

        if m_start_explicit:
            time_val = m_start_explicit.group(1)
            mer = m_start_explicit.group(2)
            parsed_time = DeterministicUnderstandingEngine._normalize_clock_time(time_val, mer)
            h, m = map(int, parsed_time.split(":"))
            base_d = new_start_time.date() if new_start_time else datetime(2026, 9, 26).date()
            new_start_time = datetime(base_d.year, base_d.month, base_d.day, h, m)

            new_constraints = [
                c for c in new_constraints
                if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:"))
            ]
            new_constraints.append(
                Constraint(plan_id=plan.id, type=ConstraintType.REQUIREMENT, value=f"start_time:{parsed_time}")
            )
            changes_detected.append(ChangeType.TIME_SHIFT)
            change_details["start_time"] = parsed_time
        elif m_start_later:
            curr_h = new_start_time.hour if new_start_time else 11
            shifted_h = min(22, curr_h + 2)
            parsed_time = f"{shifted_h:02d}:00"
            base_d = new_start_time.date() if new_start_time else datetime(2026, 9, 26).date()
            new_start_time = datetime(base_d.year, base_d.month, base_d.day, shifted_h, 0)

            new_constraints = [
                c for c in new_constraints
                if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("start_time:"))
            ]
            new_constraints.append(
                Constraint(plan_id=plan.id, type=ConstraintType.REQUIREMENT, value=f"start_time:{parsed_time}")
            )
            changes_detected.append(ChangeType.TIME_SHIFT)
            change_details["start_time"] = parsed_time

        # 2. Deadline
        # Matches: "home by 6", "need to be home by 18:00", "be home by 7", "finish by 5pm"
        m_deadline = re.search(
            r"\b(?:home\s+by|be\s+home\s+by|need\s+to\s+be\s+home\s+by|finish\s+by|done\s+by|until)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b",
            lower,
        )
        if m_deadline:
            end_val = m_deadline.group(1)
            end_mer = m_deadline.group(2)
            parsed_end = DeterministicUnderstandingEngine._normalize_clock_time(end_val, end_mer, is_deadline=True)
            h, m = map(int, parsed_end.split(":"))
            base_d = new_start_time.date() if new_start_time else datetime(2026, 9, 26).date()
            new_end_time = datetime(base_d.year, base_d.month, base_d.day, h, m)

            new_constraints = [
                c for c in new_constraints
                if not (c.type is ConstraintType.REQUIREMENT and c.value.startswith("end_time:"))
            ]
            new_constraints.append(
                Constraint(plan_id=plan.id, type=ConstraintType.REQUIREMENT, value=f"end_time:{parsed_end}")
            )
            changes_detected.append(ChangeType.DEADLINE_CHANGED)
            change_details["deadline"] = parsed_end

        # 3. Duration Limit
        # Matches: "only have 1 hour", "only have one hour", "have 2 hours", "in 1 hour", "limit to 90 minutes"
        num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
        m_dur_hrs = re.search(
            r"\b(?:only\s+have|have|limit\s+to|in|within)\s+(\d+|one|two|three|four|five|six)\s+hours?\b",
            lower,
        )
        m_dur_mins = re.search(
            r"\b(?:only\s+have|have|limit\s+to)\s+(\d+)\s+minutes?\b",
            lower,
        )
        if m_dur_hrs:
            dur_raw = m_dur_hrs.group(1).lower()
            dur_hrs = num_map.get(dur_raw) or (int(dur_raw) if dur_raw.isdigit() else 1)
            dur_mins = dur_hrs * 60
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.TIME_MAX]
            new_constraints.append(
                Constraint(plan_id=plan.id, type=ConstraintType.TIME_MAX, value=f"{dur_mins}m", numeric_value=Decimal(dur_mins))
            )
            changes_detected.append(ChangeType.DURATION_LIMIT_CHANGED)
            change_details["duration_limit_minutes"] = dur_mins
        elif m_dur_mins:
            dur_mins = int(m_dur_mins.group(1))
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.TIME_MAX]
            new_constraints.append(
                Constraint(plan_id=plan.id, type=ConstraintType.TIME_MAX, value=f"{dur_mins}m", numeric_value=Decimal(dur_mins))
            )
            changes_detected.append(ChangeType.DURATION_LIMIT_CHANGED)
            change_details["duration_limit_minutes"] = dur_mins

        # 4. Budget
        # Matches: "keep it under R600", "under 600", "budget is R500", "cheaper"
        m_budget = re.search(
            r"\b(?:keep\s+it\s+under|keep\s+under|under|max\s+of|budget\s+(?:is|of)?)\s*r?(\d+)\b",
            lower,
        )
        if m_budget:
            budget_val = Decimal(m_budget.group(1))
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.BUDGET_MAX]
            new_constraints.append(
                Constraint(
                    plan_id=plan.id,
                    type=ConstraintType.BUDGET_MAX,
                    value=f"R{budget_val}",
                    numeric_value=budget_val,
                )
            )
            changes_detected.append(ChangeType.BUDGET_REDUCED)
            change_details["budget_max"] = budget_val
        elif any(term in lower for term in ("cheaper", "lower budget", "less expensive", "make it cheap")):
            budget_c = next((c for c in new_constraints if c.type is ConstraintType.BUDGET_MAX), None)
            if budget_c and budget_c.numeric_value:
                new_val = Decimal(int(budget_c.numeric_value * Decimal("0.70")))
                if new_val < Decimal("100"):
                    new_val = Decimal("100")
            else:
                new_val = Decimal("300")
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.BUDGET_MAX]
            new_constraints.append(
                Constraint(
                    plan_id=plan.id,
                    type=ConstraintType.BUDGET_MAX,
                    value=f"R{new_val}",
                    numeric_value=new_val,
                )
            )
            changes_detected.append(ChangeType.BUDGET_REDUCED)
            change_details["budget_max"] = new_val

        # 5. Group Size
        # Matches: "two more friends are coming", "add 2 people", "for 4 people", "now 4 people"
        m_add_friends = re.search(
            r"\b(\d+|one|two|three|four)\s+more\s+(?:friends?|people)\s+(?:are\s+)?coming\b", lower
        )
        m_add_people = re.search(r"\badd\s+(\d+|one|two|three|four)\s+(?:more\s+)?(?:people|friends)\b", lower)
        m_set_people = re.search(r"\b(?:for|now|make it)\s+(\d+|one|two|three|four|five|six)\s+people\b", lower)

        if m_add_friends or m_add_people:
            raw_add = (m_add_friends or m_add_people).group(1).lower()
            add_count = num_map.get(raw_add) or (int(raw_add) if raw_add.isdigit() else 2)
            new_group_size += add_count
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.GROUP_SIZE]
            new_constraints.append(
                Constraint(
                    plan_id=plan.id,
                    type=ConstraintType.GROUP_SIZE,
                    value=str(new_group_size),
                    numeric_value=Decimal(new_group_size),
                )
            )
            changes_detected.append(ChangeType.GROUP_SIZE_CHANGED)
            change_details["group_size"] = new_group_size
        elif m_set_people:
            raw_set = m_set_people.group(1).lower()
            new_group_size = num_map.get(raw_set) or (int(raw_set) if raw_set.isdigit() else 4)
            new_constraints = [c for c in new_constraints if c.type is not ConstraintType.GROUP_SIZE]
            new_constraints.append(
                Constraint(
                    plan_id=plan.id,
                    type=ConstraintType.GROUP_SIZE,
                    value=str(new_group_size),
                    numeric_value=Decimal(new_group_size),
                )
            )
            changes_detected.append(ChangeType.GROUP_SIZE_CHANGED)
            change_details["group_size"] = new_group_size

        # 6. Exclusions
        if any(term in lower for term in ("no outdoor", "no outdoors", "nothing outdoor", "nothing outdoors", "indoor only", "not outdoor")):
            if not any(c.value == "exclude:no_outdoors" for c in new_constraints):
                new_constraints.append(
                    Constraint(plan_id=plan.id, type=ConstraintType.REQUIREMENT, value="exclude:no_outdoors")
                )
            changes_detected.append(ChangeType.EXCLUSION_ADDED)
            change_details["exclude_outdoors"] = True

        if any(term in lower for term in ("nothing too fancy", "not too fancy", "no fancy")):
            if not any(c.value == "exclude:not_too_fancy" for c in new_constraints):
                new_constraints.append(
                    Constraint(plan_id=plan.id, type=ConstraintType.REQUIREMENT, value="exclude:not_too_fancy")
                )
            changes_detected.append(ChangeType.EXCLUSION_ADDED)
            change_details["exclude_fancy"] = True

        # 7. Venue Invalidation (Closed / Removed)
        # Matches: "Truth Coffee is closed", "that place is closed", "remove Kirstenbosch"
        m_closed = re.search(r"\b(.+?)\s+is\s+closed\b", lower)
        m_remove = re.search(r"\b(?:remove|skip|don't want to go to)\s+(.+?)\b", lower)
        closed_place_name: str | None = None
        if m_closed:
            closed_place_name = m_closed.group(1).strip()
        elif m_remove:
            closed_place_name = m_remove.group(1).strip()

        if closed_place_name:
            changes_detected.append(ChangeType.VENUE_INVALIDATED)
            change_details["closed_venue_name"] = closed_place_name

        # 8. Location Shift
        # Matches: "let's do Camps Bay", "in Camps Bay instead", "change location to V&A Waterfront"
        m_loc = re.search(
            r"\b(?:let's\s+do|in|to|change\s+to|switch\s+to)\s+(camps\s+bay|v&a\s+waterfront|waterfront|kirstenbosch|sea\s+point|green\s+point|city\s+bowl|woodstock|constantia|kalk\s+bay)\b",
            lower,
        )
        if m_loc:
            loc_matched = m_loc.group(1).title()
            if loc_matched.lower() == "waterfront":
                loc_matched = "V&A Waterfront"
            new_location = loc_matched
            changes_detected.append(ChangeType.LOCATION_CHANGED)
            change_details["location"] = loc_matched

        # 9. Mobility Disruption
        # Matches: "uber is too expensive", "train isn't running", "bus is delayed", "metro cancelled"
        if any(term in lower for term in ("uber is too expensive", "uber too expensive", "too expensive to get there", "rides too expensive")):
            changes_detected.append(ChangeType.MOBILITY_DISRUPTION)
            change_details["mobility_disruption"] = "ride_hail_expensive"
        elif any(term in lower for term in ("train isn't running", "train is cancelled", "metrorail cancelled", "bus cancelled", "bus delayed")):
            changes_detected.append(ChangeType.MOBILITY_DISRUPTION)
            change_details["mobility_disruption"] = "transit_cancelled"

        # 10. Mobility Preference
        # Matches: "walk instead", "prefer walking", "don't want to drive", "no car", "prefer transit"
        if any(term in lower for term in ("walk instead", "prefer walking", "don't want to drive", "no car", "prefer public transit")):
            changes_detected.append(ChangeType.MOBILITY_PREFERENCE_CHANGED)
            change_details["mobility_preference"] = "walk_or_transit"


        updated_context = PlanningContext(
            plan_id=plan.id,
            location=new_location,
            start_time=new_start_time,
            end_time=new_end_time,
            group_size=new_group_size,
            transport_mode=curr_context.transport_mode,
        )

        if not changes_detected:
            changes_detected.append(ChangeType.OTHER)

        return updated_context, new_constraints, changes_detected, change_details

    def _evaluate_item_validity(
        self,
        item: PlanItem,
        criteria: DecisionCriteria,
        change_details: dict[str, Any],
    ) -> tuple[bool, str]:
        item_name_lower = item.name.lower()

        # 1. Explicit closed / removed venue check
        closed_venue = change_details.get("closed_venue_name")
        if closed_venue:
            if closed_venue == "that place" or closed_venue in item_name_lower or item_name_lower in closed_venue:
                return False, f"Reported closed or requested for removal ('{item.name}')"

        # 2. Outdoor exclusion check
        if change_details.get("exclude_outdoors"):
            outdoor_indicators = (
                "kirstenbosch",
                "table mountain",
                "lion's head",
                "promenade",
                "botanical",
                "hike",
                "trail",
                "beach",
                "park",
                "garden",
            )
            if any(ind in item_name_lower for ind in outdoor_indicators):
                return False, f"Excluded: outdoor venue/activity ('{item.name}')"

        # 3. Location check
        target_loc = change_details.get("location") or criteria.location
        if target_loc and item.location:
            t_loc = target_loc.lower().replace("&", "and")
            i_loc = item.location.lower().replace("&", "and")
            if t_loc not in i_loc and "camps bay" in t_loc and "camps bay" not in i_loc:
                return False, f"Outside target location ('{target_loc}')"

        # 4. Group size compatibility check
        group_size = criteria.group_size
        if group_size is not None and group_size > 2:
            intimate_indicators = ("romantic corner", "intimate bistro", "couples table")
            if any(ind in (item.description or "").lower() for ind in intimate_indicators):
                return False, f"Cannot comfortably accommodate group of {group_size}"

        # 5. Opening hours check for afternoon/evening slots
        start_time_str = criteria.start_time
        if start_time_str:
            try:
                hour = int(start_time_str.split(":")[0])
                if hour >= 14:
                    morning_indicators = ("morning only", "breakfast only", "closes at 13:00")
                    if any(ind in (item.description or "").lower() for ind in morning_indicators):
                        return False, "Closed during afternoon hours"
            except Exception:
                pass

        # 6. Budget check: if item cost alone exceeds the maximum budget
        max_budget = change_details.get("budget_max") or criteria.maximum_cost
        if max_budget is not None and item.estimated_cost is not None:
            if item.estimated_cost > max_budget:
                return False, f"Exceeds revised budget limit (R{max_budget:.0f})"

        return True, "Valid"

    def _find_replacement_candidate(
        self,
        item: PlanItem,
        candidates: list[DecisionCandidate],
        used_names: set[str],
        max_remaining_budget: Decimal | None,
        new_criteria: DecisionCriteria,
    ) -> DecisionCandidate | None:
        target_category: InformationCategory | None = None
        if item.item_type is PlanItemType.FOOD:
            target_category = InformationCategory.FOOD
        elif item.item_type is PlanItemType.ACTIVITY:
            target_category = InformationCategory.CULTURE

        for candidate in candidates:
            if not candidate.is_eligible:
                continue
            if candidate.name.lower() in used_names:
                continue

            # Check outdoor exclusion
            if "no_outdoors" in new_criteria.exclusions:
                c_name_lower = candidate.name.lower()
                outdoor_words = ("kirstenbosch", "table mountain", "lion's head", "promenade", "botanical", "hike", "beach", "garden")
                if any(w in c_name_lower for w in outdoor_words):
                    continue

            # Check location match if specified
            if new_criteria.location:
                req_loc = new_criteria.location.lower()
                c_loc = (candidate.location or "").lower()
                c_addr = (candidate.address or "").lower()
                if req_loc not in c_loc and req_loc not in c_addr:
                    continue

            # Check budget fit
            if max_remaining_budget is not None and candidate.cost is not None:
                if candidate.cost > max_remaining_budget:
                    continue

            # Prefer same category if available
            if target_category and candidate.category == target_category:
                return candidate

        # Fallback to any eligible candidate that passes exclusions
        for candidate in candidates:
            if not candidate.is_eligible:
                continue
            if candidate.name.lower() in used_names:
                continue
            if "no_outdoors" in new_criteria.exclusions:
                c_name_lower = candidate.name.lower()
                outdoor_words = ("kirstenbosch", "table mountain", "lion's head", "promenade", "botanical", "hike", "beach", "garden")
                if any(w in c_name_lower for w in outdoor_words):
                    continue
            if new_criteria.location:
                req_loc = new_criteria.location.lower()
                c_loc = (candidate.location or "").lower()
                c_addr = (candidate.address or "").lower()
                if req_loc not in c_loc and req_loc not in c_addr:
                    continue
            return candidate

        return None

    def _adjust_for_budget_overage(
        self,
        adapted_items: list[PlanItem],
        diffs: list[ItemDiff],
        candidates: list[DecisionCandidate],
        used_names: set[str],
        max_budget: Decimal,
    ) -> Decimal:
        """Substitutes or scales down items if total cost exceeds maximum budget."""
        current_total = sum(
            (i.estimated_cost for i in adapted_items if i.estimated_cost is not None),
            start=Decimal("0"),
        )
        if current_total <= max_budget:
            return current_total

        # Find the most expensive item to replace or adjust
        adapted_items.sort(key=lambda i: (i.estimated_cost or Decimal("0")), reverse=True)
        for idx, expensive_item in enumerate(adapted_items):
            if current_total <= max_budget:
                break
            excess = current_total - max_budget
            # Search for a cheaper eligible candidate
            cheaper = None
            for c in candidates:
                if not c.is_eligible or c.name.lower() in used_names or c.cost is None:
                    continue
                if expensive_item.estimated_cost and c.cost < expensive_item.estimated_cost:
                    cheaper = c
                    break

            if cheaper is not None:
                used_names.add(cheaper.name.lower())
                old_name = expensive_item.name
                old_cost = expensive_item.estimated_cost
                new_cost = cheaper.cost
                diff_amount = (old_cost or Decimal("0")) - (new_cost or Decimal("0"))

                # Replace item in adapted_items
                expensive_item.name = cheaper.name
                expensive_item.estimated_cost = new_cost
                expensive_item.location = cheaper.address or cheaper.location
                current_total -= diff_amount

                # Update or add diff using old_name
                diff_entry = next((d for d in diffs if d.new_name == old_name or d.original_name == old_name), None)
                if diff_entry:
                    diff_entry.action = ItemAction.REPLACED
                    diff_entry.new_name = cheaper.name
                    diff_entry.new_cost = new_cost
                    diff_entry.reason = f"Replaced with {cheaper.name} to fit within R{max_budget:.0f} budget limit"
                    diff_entry.candidate_option_id = cheaper.option_id
                    diff_entry.candidate_option_type = cheaper.option_type
                else:
                    diffs.append(
                        ItemDiff(
                            action=ItemAction.REPLACED,
                            original_name=old_name,
                            new_name=cheaper.name,
                            original_cost=old_cost,
                            new_cost=new_cost,
                            reason=f"Replaced with affordable alternative ({cheaper.name}) to satisfy R{max_budget:.0f} budget",
                            candidate_option_id=cheaper.option_id,
                            candidate_option_type=cheaper.option_type,
                        )
                    )

        # Restore original positional order
        adapted_items.sort(key=lambda i: i.position)
        return current_total

    def _build_narrative_summary(
        self,
        changes_detected: list[ChangeType],
        diffs: list[ItemDiff],
        new_start_time: datetime | None,
        new_budget_max: Decimal | None,
        max_allowed_stops: int | None,
    ) -> str:
        kept_count = sum(1 for d in diffs if d.action is ItemAction.KEPT)
        rescheduled_count = sum(1 for d in diffs if d.action is ItemAction.RESCHEDULED)
        replaced_count = sum(1 for d in diffs if d.action is ItemAction.REPLACED)
        removed_count = sum(1 for d in diffs if d.action is ItemAction.REMOVED)

        parts: list[str] = []

        if ChangeType.TIME_SHIFT in changes_detected and new_start_time:
            parts.append(f"start shifted to {new_start_time.strftime('%H:%M')}")
        if ChangeType.BUDGET_REDUCED in changes_detected and new_budget_max:
            parts.append(f"budget reduced to R{new_budget_max:.0f}")
        if ChangeType.GROUP_SIZE_CHANGED in changes_detected:
            parts.append("group size updated")
        if ChangeType.EXCLUSION_ADDED in changes_detected:
            parts.append("outdoor activities excluded")
        if ChangeType.VENUE_INVALIDATED in changes_detected:
            parts.append("closed venue replaced")
        if ChangeType.LOCATION_CHANGED in changes_detected:
            parts.append("neighborhood updated")
        if ChangeType.MOBILITY_DISRUPTION in changes_detected:
            parts.append("mobility disruption accounted for")
        if ChangeType.MOBILITY_PREFERENCE_CHANGED in changes_detected:
            parts.append("transport preferences updated")


        detail_parts: list[str] = []
        if kept_count > 0:
            detail_parts.append(f"{kept_count} stop{'s' if kept_count > 1 else ''} kept")
        if rescheduled_count > 0:
            detail_parts.append(f"{rescheduled_count} rescheduled")
        if replaced_count > 0:
            detail_parts.append(f"{replaced_count} replaced")
        if removed_count > 0:
            detail_parts.append(f"{removed_count} removed")

        lead = "Plan adapted"
        if parts:
            lead += f" ({', '.join(parts)})"

        if detail_parts:
            return f"{lead}: {', '.join(detail_parts)}."
        return f"{lead}."
