from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from app.application.mobility.service import MobilityService
from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveStatus,
    TransportMode,
)
from app.domain.entities.mobility.models import MobilityOption, MobilityRequirement
from app.domain.entities.planning.constraint import ConstraintType
from app.domain.entities.planning.decision import DecisionReason, ReasonOutcome, ReasonType
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.plan_item import PlanItem
from app.domain.entities.planning.transition import ItineraryFeasibility, PlanTransition

logger = logging.getLogger(__name__)


class MobilityPlanningService:
    """Evaluates physical transport feasibility between itinerary stops in a plan."""

    def __init__(self, mobility_service: MobilityService) -> None:
        self._mobility_service = mobility_service

    async def evaluate_transitions(
        self,
        plan: Plan,
        party_size: int = 1,
        preferred_modes: list[TransportMode] | None = None,
    ) -> list[PlanTransition]:
        """Compute mobility transitions between sequential stops in a plan."""
        # Sort items by position and start_time
        items = sorted(
            [item for item in plan.items if item.location and item.location.strip()],
            key=lambda x: (x.position, x.start_time or datetime.min),
        )

        if len(items) < 2:
            return []

        transitions: list[PlanTransition] = []

        for i in range(len(items) - 1):
            item_a = items[i]
            item_b = items[i + 1]

            loc_a = item_a.location.strip()  # type: ignore[union-attr]
            loc_b = item_b.location.strip()  # type: ignore[union-attr]

            if loc_a.lower() == loc_b.lower():
                continue

            dep_time = item_a.end_time or item_a.start_time
            arr_time = item_b.start_time or item_b.end_time

            req = MobilityRequirement(
                origin=loc_a,
                destination=loc_b,
                departure_time=dep_time,
                arrival_time=arr_time,
                party_size=party_size,
                preferred_modes=preferred_modes or [],
            )

            try:
                options = await self._mobility_service.find_options_for_requirement(req)
            except Exception as e:
                logger.error(
                    "Error querying mobility options between %s and %s: %s",
                    loc_a,
                    loc_b,
                    e,
                    exc_info=True,
                )
                options = []

            if not options:
                # Default unknown transition when no provider has verified data
                transition = PlanTransition(
                    from_item_id=item_a.id,
                    to_item_id=item_b.id,
                    from_location=loc_a,
                    to_location=loc_b,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    mode=TransportMode.OTHER,
                    provider_id="unknown",
                    provider_name="Transport",
                    cost=None,
                    cost_known=False,
                    summary=f"Travel from {loc_a} to {loc_b}",
                    is_feasible=True,
                )
                transitions.append(transition)
                continue

            # Pick the primary recommended option:
            # 1. Preferred mode if matched
            # 2. Walking if duration <= 15 minutes
            # 3. Lowest duration option
            primary = self._select_primary_option(options, preferred_modes)

            # Feasibility evaluation: check available time window between stops
            is_feasible = True
            feasibility_issue = None

            if item_a.end_time and item_b.start_time:
                available_mins = int((item_b.start_time - item_a.end_time).total_seconds() // 60)
                if primary.duration_minutes is not None and primary.duration_minutes > available_mins:
                    is_feasible = False
                    feasibility_issue = (
                        f"Travel time ({primary.duration_minutes} min via {primary.provider_name}) "
                        f"exceeds available window ({available_mins} min) between '{item_a.name}' and '{item_b.name}'."
                    )

            # Compute actual departure/arrival times for the travel leg
            leg_dep = dep_time or (
                arr_time - timedelta(minutes=primary.duration_minutes)
                if arr_time and primary.duration_minutes
                else None
            )
            leg_arr = arr_time or (
                leg_dep + timedelta(minutes=primary.duration_minutes)
                if leg_dep and primary.duration_minutes
                else None
            )

            transition = PlanTransition(
                from_item_id=item_a.id,
                to_item_id=item_b.id,
                from_location=loc_a,
                to_location=loc_b,
                departure_time=leg_dep,
                arrival_time=leg_arr,
                duration_minutes=primary.duration_minutes,
                mode=primary.mode,
                provider_id=primary.provider_id,
                provider_name=primary.provider_name,
                cost=primary.cost,
                cost_known=not primary.cost_is_unknown,
                currency=primary.currency,
                transfers=primary.transfers,
                confidence=primary.confidence,
                live_status=primary.live_status,
                booking_capability=primary.booking_capability,
                booking_url=primary.booking_url,
                summary=primary.summary or f"{primary.provider_name} to {loc_b}",
                evidence=tuple(primary.evidence),
                available_options=tuple(options),
                is_feasible=is_feasible,
                feasibility_issue=feasibility_issue,
            )
            transitions.append(transition)

        return transitions

    def check_plan_feasibility(
        self,
        plan: Plan,
        transitions: list[PlanTransition],
    ) -> ItineraryFeasibility:
        """Evaluate overall plan feasibility against budget, deadlines, and transit time."""
        issues: list[str] = []
        warnings: list[str] = []

        # 1. Transition feasibility
        transitions_feasible = True
        for t in transitions:
            if not t.is_feasible:
                transitions_feasible = False
                if t.feasibility_issue:
                    issues.append(t.feasibility_issue)

        # 2. Budget feasibility
        venue_cost = sum(
            (item.estimated_cost for item in plan.items if item.estimated_cost is not None),
            Decimal("0"),
        )
        known_transit_cost = sum(
            (t.cost for t in transitions if t.cost is not None),
            Decimal("0"),
        )
        has_unknown_transit = any(not t.cost_known for t in transitions)
        if has_unknown_transit:
            warnings.append(
                "Some transport options (e.g. Uber/Bolt) have dynamic pricing confirmed in-app."
            )

        budget_constraint = next(
            (c for c in plan.constraints if c.type is ConstraintType.BUDGET_MAX and c.numeric_value is not None),
            None,
        )
        budget_respected = True
        if budget_constraint is not None:
            max_budget = budget_constraint.numeric_value
            total_known = venue_cost + known_transit_cost
            if total_known > max_budget:
                budget_respected = False
                issues.append(
                    f"Total planned cost (R{total_known:.2f}, including R{known_transit_cost:.2f} transport) "
                    f"exceeds maximum budget of R{max_budget:.2f}."
                )

        # 3. Deadline feasibility
        deadline_respected = True
        deadline_constraint = next(
            (
                c
                for c in plan.constraints
                if c.type is ConstraintType.REQUIREMENT and c.value.startswith("deadline:")
            ),
            None,
        )
        context_end = plan.context.end_time if plan.context else None

        deadline_str = deadline_constraint.value.split(":", 1)[1] if deadline_constraint else None

        if deadline_str or context_end:
            # Check last stop end time
            items_with_end = [i for i in plan.items if i.end_time]
            if items_with_end:
                last_end = max(i.end_time for i in items_with_end)  # type: ignore[type-var]
                if context_end and last_end > context_end:
                    deadline_respected = False
                    issues.append(
                        f"Itinerary concludes at {last_end.strftime('%H:%M')}, which exceeds the time limit of {context_end.strftime('%H:%M')}."
                    )

        total_trans_duration = sum(
            (t.duration_minutes for t in transitions if t.duration_minutes is not None), 0
        )
        is_overall_feasible = transitions_feasible and budget_respected and deadline_respected

        return ItineraryFeasibility(
            is_feasible=is_overall_feasible,
            deadline_respected=deadline_respected,
            budget_respected=budget_respected,
            transitions_feasible=transitions_feasible,
            issues=issues,
            warnings=warnings,
            total_transition_duration_minutes=total_trans_duration,
            total_known_transition_cost=known_transit_cost,
            has_unknown_transition_costs=has_unknown_transit,
        )

    def evaluate_candidate_mobility_score(
        self,
        origin_location: str,
        candidate_location: str,
        available_time_minutes: int | None = None,
        budget_remaining: Decimal | None = None,
    ) -> tuple[int, DecisionReason]:
        """Explainable scoring modifier during candidate evaluation reflecting mobility impact."""
        from app.infrastructure.mobility.geo import estimate_network_distance_km

        dist_km = estimate_network_distance_km(origin_location, candidate_location)

        # Walking distance: <= 1.5km (~18 min)
        if dist_km <= 1.5:
            duration = int(round(dist_km * 12.5))
            return (
                15,
                DecisionReason(
                    type=ReasonType.MOBILITY,
                    outcome=ReasonOutcome.SUPPORTED,
                    message=f"Convenient walking distance ({dist_km:.1f} km, ~{duration}m) with zero transport cost.",
                ),
            )

        # Moderate distance (1.5km - 6km): reachable by short bus or ride-hail
        if dist_km <= 6.0:
            duration = int(round((dist_km / 30.0) * 60)) + 4
            if available_time_minutes is not None and duration > available_time_minutes:
                return (
                    -15,
                    DecisionReason(
                        type=ReasonType.MOBILITY,
                        outcome=ReasonOutcome.VIOLATED,
                        message=f"Travel time (~{duration}m) threatens available time window of {available_time_minutes}m.",
                    ),
                )
            return (
                5,
                DecisionReason(
                    type=ReasonType.MOBILITY,
                    outcome=ReasonOutcome.SUPPORTED,
                    message=f"Easily accessible via local transit or ride-hail (~{duration}m travel).",
                ),
            )

        # Longer distance (>6km): check time window
        duration = int(round((dist_km / 35.0) * 60)) + 6
        if available_time_minutes is not None and duration > available_time_minutes:
            return (
                -25,
                DecisionReason(
                    type=ReasonType.MOBILITY,
                    outcome=ReasonOutcome.VIOLATED,
                    message=f"Cross-city journey (~{dist_km:.1f} km, {duration}m) exceeds available transit window.",
                ),
            )

        return (
            0,
            DecisionReason(
                type=ReasonType.MOBILITY,
                outcome=ReasonOutcome.NEUTRAL,
                message=f"Cross-city connection ({dist_km:.1f} km, ~{duration}m travel).",
            ),
        )

    def _select_primary_option(
        self,
        options: list[MobilityOption],
        preferred_modes: list[TransportMode] | None = None,
    ) -> MobilityOption:
        """Select the most appropriate primary option to anchor the transition."""
        if not options:
            raise ValueError("Cannot select from empty options list.")

        # If user explicitly preferred a mode, pick the top option matching it
        if preferred_modes:
            for mode in preferred_modes:
                for opt in options:
                    if opt.mode == mode:
                        return opt

        # Otherwise: walking if <= 15 minutes
        walk_opt = next(
            (
                opt
                for opt in options
                if opt.mode == TransportMode.WALK
                and opt.duration_minutes is not None
                and opt.duration_minutes <= 15
            ),
            None,
        )
        if walk_opt:
            return walk_opt

        # Public transit if direct & verified
        bus_opt = next(
            (
                opt
                for opt in options
                if opt.mode in {TransportMode.BUS, TransportMode.TRAIN} and opt.transfers == 0
            ),
            None,
        )
        if bus_opt:
            return bus_opt

        # Fallback to the first option
        return options[0]
