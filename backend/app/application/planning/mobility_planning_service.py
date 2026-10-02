from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from app.application.mobility.service import MobilityService
from app.application.mobility.live_service import LiveMobilityService
from app.domain.entities.mobility.live import MobilityLiveStatusReport
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


@dataclass(frozen=True)
class StopSequencePoint:
    """A single ordered stop in a proposed itinerary, independent of plan persistence.

    A proposed itinerary is assembled before any `PlanItem` is persisted, so mobility
    between stops must be evaluable from location + timing alone.
    """

    location: str
    name: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_cost: Decimal | None = None


class MobilityPlanningService:
    """Evaluates physical transport feasibility between itinerary stops in a plan."""

    def __init__(
        self,
        mobility_service: MobilityService,
        live_mobility_service: LiveMobilityService | None = None,
    ) -> None:
        self._mobility_service = mobility_service
        # Live intelligence is optional: without it transitions still evaluate,
        # they simply carry no live state and stay truthfully 'unavailable'.
        self._live_mobility_service = live_mobility_service

    async def evaluate_stop_sequence(
        self,
        stops: Sequence[StopSequencePoint],
        party_size: int = 1,
        preferred_modes: list[TransportMode] | None = None,
    ) -> list[PlanTransition]:
        """Compute mobility transitions across an ordered stop sequence.

        Used for proposed itineraries that have not yet been persisted as `PlanItem`s.
        """
        points = [s for s in stops if s.location and s.location.strip()]
        if len(points) < 2:
            return []

        transitions: list[PlanTransition] = []
        for transition in await self.evaluate_aligned_legs(
            points, party_size=party_size, preferred_modes=preferred_modes
        ):
            if transition is not None:
                transitions.append(transition)
        return transitions

    async def evaluate_aligned_legs(
        self,
        stops: Sequence[StopSequencePoint],
        party_size: int = 1,
        preferred_modes: list[TransportMode] | None = None,
    ) -> list[PlanTransition | None]:
        """Evaluate consecutive legs, preserving one slot per adjacent pair.

        `evaluate_stop_sequence` drops legs that need no travel, which shifts the
        remaining results. Scheduling code cannot use that shape, because it has
        to know which leg belongs to which pair of stops. This variant keeps a
        `None` in the slot for a pair that needs no travel, so index `i` always
        describes the move from point `i` to point `i + 1`.
        """
        points = [s for s in stops if s.location and s.location.strip()]
        if len(points) < 2:
            return []

        legs: list[PlanTransition | None] = []
        for a, b in zip(points, points[1:], strict=False):
            transition = await self._build_transition(
                origin=a.location.strip(),
                destination=b.location.strip(),
                from_name=a.name,
                to_name=b.name,
                departure_time=a.end_time or a.start_time,
                arrival_time=b.start_time or b.end_time,
                party_size=party_size,
                preferred_modes=preferred_modes or [],
            )
            if transition is not None:
                await self._apply_live_status(transition, a.location.strip(), b.location.strip())
            legs.append(transition)
        return legs

    async def _build_transition(
        self,
        origin: str,
        destination: str,
        from_name: str,
        to_name: str,
        departure_time: datetime | None,
        arrival_time: datetime | None,
        party_size: int,
        preferred_modes: list[TransportMode],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> PlanTransition | None:
        """Query M14 for one leg and map the result onto a `PlanTransition`.

        Returns None when both stops are at the same location (no travel leg needed).
        Provider failures degrade to an unknown-cost transition rather than propagating.
        """
        if origin.lower() == destination.lower():
            return None

        req = MobilityRequirement(
            origin=origin,
            destination=destination,
            departure_time=departure_time,
            arrival_time=arrival_time,
            party_size=party_size,
            preferred_modes=preferred_modes,
        )

        try:
            options = await self._mobility_service.find_options_for_requirement(req)
        except Exception as e:
            logger.error(
                "Error querying mobility options between %s and %s: %s",
                origin,
                destination,
                e,
                exc_info=True,
            )
            options = []

        if not options:
            # Unknown remains unknown: no provider verified this leg, so no fare is claimed.
            return PlanTransition(
                from_location=origin,
                to_location=destination,
                departure_time=departure_time,
                arrival_time=arrival_time,
                mode=TransportMode.OTHER,
                provider_id="unknown",
                provider_name="Transport",
                cost=None,
                cost_known=False,
                summary=f"Travel from {origin} to {destination}",
                is_feasible=True,
            )

        primary, substitution_reason = self._select_primary_option(options, preferred_modes)

        is_feasible = True
        feasibility_issue = None
        gap_start = window_start if window_start is not None else departure_time
        gap_end = window_end if window_end is not None else arrival_time
        if gap_start and gap_end:
            available_mins = int((gap_end - gap_start).total_seconds() // 60)
            if primary.duration_minutes is not None and primary.duration_minutes > available_mins:
                is_feasible = False
                feasibility_issue = (
                    f"Travel time ({primary.duration_minutes} min via {primary.provider_name}) "
                    f"exceeds available window ({available_mins} min) between '{from_name}' and '{to_name}'."
                )

        leg_dep = departure_time
        leg_arr = arrival_time
        if leg_dep is None and leg_arr is not None and primary.duration_minutes:
            leg_dep = leg_arr - timedelta(minutes=primary.duration_minutes)
        if leg_arr is None and leg_dep is not None and primary.duration_minutes:
            leg_arr = leg_dep + timedelta(minutes=primary.duration_minutes)

        return PlanTransition(
            from_location=origin,
            to_location=destination,
            departure_time=leg_dep,
            arrival_time=leg_arr,
            duration_minutes=primary.duration_minutes,
            mode=primary.mode,
            provider_id=primary.provider_id,
            provider_name=primary.provider_name,
            cost=primary.cost,
            cost_known=not primary.cost_is_unknown,
            cost_is_estimated=primary.cost_is_estimated,
            currency=primary.currency,
            transfers=primary.transfers,
            confidence=primary.confidence,
            live_status=primary.live_status,
            booking_capability=primary.booking_capability,
            booking_url=primary.booking_url,
            summary=primary.summary or f"{primary.provider_name} to {destination}",
            evidence=tuple(primary.evidence),
            available_options=tuple(options),
            is_feasible=is_feasible,
            feasibility_issue=feasibility_issue,
            mode_substitution_reason=substitution_reason,
        )

    async def _apply_live_status(
        self, transition: PlanTransition, origin: str, destination: str
    ) -> None:
        """Overlay M16 live service state onto a transition, if a live layer exists.

        Failures degrade to the transition's default 'unavailable' live state; a
        live outage must never prevent an itinerary from being produced.
        """
        if self._live_mobility_service is None:
            return
        try:
            report: MobilityLiveStatusReport = await self._live_mobility_service.get_live_status(
                provider_id=transition.provider_id,
                origin=origin,
                destination=destination,
            )
        except Exception as e:
            logger.error(
                "Live mobility status lookup for %s failed: %s",
                transition.provider_id,
                e,
                exc_info=True,
            )
            return
        transition.apply_live_status(report)

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

        for item_a, item_b in zip(items, items[1:], strict=False):
            loc_a = item_a.location.strip()  # type: ignore[union-attr]
            loc_b = item_b.location.strip()  # type: ignore[union-attr]

            transition = await self._build_transition(
                origin=loc_a,
                destination=loc_b,
                from_name=item_a.name,
                to_name=item_b.name,
                departure_time=item_a.end_time or item_a.start_time,
                arrival_time=item_b.start_time or item_b.end_time,
                party_size=party_size,
                preferred_modes=preferred_modes or [],
                window_start=item_a.end_time,
                window_end=item_b.start_time,
            )
            if transition is None:
                continue

            # Re-attach the persisted item ids the leg was derived from.
            transition.from_item_id = item_a.id
            transition.to_item_id = item_b.id
            await self._apply_live_status(transition, loc_a, loc_b)
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
    ) -> tuple[MobilityOption, str | None]:
        """Select the option to anchor the transition, plus any substitution reason.

        Returns the chosen option and, when an explicitly requested mode could not
        be honoured, a sentence explaining what was used instead. Returning the
        reason rather than applying the change quietly is the whole point: an
        unrequested ride-hail substitution is indistinguishable from the planner
        having ignored the user.
        """
        if not options:
            raise ValueError("Cannot select from empty options list.")

        # If user explicitly preferred a mode, pick the top option matching it
        if preferred_modes:
            for mode in preferred_modes:
                for opt in options:
                    if opt.mode == mode:
                        return opt, None

        reason = self._unmet_preference_reason(options, preferred_modes)

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
            return walk_opt, reason

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
            return bus_opt, reason

        # Fallback to the first option, but never let provider registration order
        # decide. When the user asked for something specific and only ride-hail is
        # left, the cheapest available option is the honest pick — and the reason
        # it was substituted is carried through to the plan.
        fallback = min(
            options,
            key=lambda opt: (
                opt.duration_minutes if opt.duration_minutes is not None else 9999,
                opt.cost if opt.cost is not None else 9999,
            ),
        )
        return fallback, reason

    def _unmet_preference_reason(
        self,
        options: list[MobilityOption],
        preferred_modes: list[TransportMode] | None,
    ) -> str | None:
        """Explain a substitution, or None when nothing was requested."""
        if not preferred_modes:
            return None
        requested = ", ".join(sorted({m.value.replace("_", " ") for m in preferred_modes}))
        available = ", ".join(
            sorted({f"{o.provider_name} ({o.mode.value.replace('_', ' ')})" for o in options})
        )
        return (
            f"No {requested} service is available for this leg, so "
            f"{'it was' if len(preferred_modes) == 1 else 'they were'} substituted "
            f"with: {available}."
        )
