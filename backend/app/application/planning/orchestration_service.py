"""Itinerary orchestration: transport resolved *before* the schedule is fixed.

The previous flow assembled an itinerary first and asked M15 about transport
afterwards. That inverted the real dependency: a leg could be scheduled with a
zero-minute window and only then be reported as infeasible, leaving the user to
discover that their own plan did not fit.

This service inverts it. For an ordered set of candidate stops it:

1. Establishes origin context, prepending the user's starting point as a real
   first leg when one is known (and never inventing one when it is not).
2. Asks M14/M15 for every transport option across every leg, concurrently.
3. Selects one option per leg that satisfies the actual plan constraints.
4. Only then assigns time windows, derived from the selected travel times.

Because the windows are derived from the selected legs rather than assumed, a
leg's available window is by construction at least as long as its travel time,
and the "Travel time exceeds available window (0 min)" failure mode cannot occur
for a stop sequence this service produces.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Sequence
from zoneinfo import ZoneInfo

from app.application.planning.mobility_planning_service import (
    MobilityPlanningService,
    StopSequencePoint,
)
from app.application.planning.venue_actions import (
    VenueActionSpec,
    contact_fallback_label,
    derive_venue_action_specs,
)
from app.domain.entities.mobility.enums import TransportMode
from app.domain.entities.mobility.models import MobilityOption
from app.domain.entities.planning.areas import (
    AreaScope,
    AreaStatus,
    AreaVerdict,
    classify_in_area,
    resolve_area_scope,
)
from app.domain.entities.planning.constraint import ConstraintType
from app.domain.entities.planning.plan import Plan
from app.domain.entities.planning.requirements import (
    CandidateEvidence,
    CoverageStatus,
    IntentCoverage,
    IntentRequirement,
    RequirementKind,
    evaluate_coverage,
    requirements_from_slugs,
)
from app.domain.entities.planning.temporal import parse_opening_hours
from app.domain.entities.planning.transition import ItineraryFeasibility, PlanTransition

logger = logging.getLogger(__name__)

DEFAULT_STOP_MINUTES = 90
DEFAULT_PLACE_MINUTES = 90


@dataclass(frozen=True)
class OrchestrationStopInput:
    """One requested stop, before any timing has been decided."""

    name: str
    location: str
    option_id: str = ""
    duration_minutes: int | None = None
    estimated_cost: Decimal | None = None
    address: str | None = None
    opening_hours: str | None = None
    phone: str | None = None
    source_url: str | None = None
    reservation_url: str | None = None
    category: str | None = None
    # The venue's own description, carried through so coverage is checked
    # against evidence rather than inferred from the category.
    description: str = ""


@dataclass(frozen=True)
class OrchestratedStop:
    """A stop with a schedule that already accounts for its travel legs."""

    name: str
    location: str
    address: str | None
    opening_hours: str | None
    phone: str | None
    source_url: str | None
    reservation_url: str | None
    category: str | None
    estimated_cost: Decimal | None
    duration_minutes: int
    start_time: datetime
    end_time: datetime
    actions: tuple[VenueActionSpec, ...] = ()
    contact_hint: str | None = None
    description: str = ""

    @property
    def is_approximate_duration(self) -> bool:
        """Durations default to a planning allowance when the venue gives none."""
        return False


@dataclass(frozen=True)
class OrchestratedLeg:
    """A transport leg between two points, with the alternatives preserved."""

    transition: PlanTransition
    from_label: str
    to_label: str
    selected_option_id: str | None
    alternatives: tuple[MobilityOption, ...] = ()
    all_options: tuple[MobilityOption, ...] = ()
    reason: str | None = None
    preference_honoured: bool | None = None
    preference_note: str | None = None


@dataclass
class OrchestratedPlan:
    """A fully scheduled, mobility-aware proposal ready to present."""

    origin: str | None
    origin_resolved: bool
    stops: list[OrchestratedStop] = field(default_factory=list)
    legs: list[OrchestratedLeg] = field(default_factory=list)
    feasibility: ItineraryFeasibility | None = None
    day_start: datetime | None = None
    transport_preference: str | None = None
    transport_preference_honoured: bool | None = None
    transport_preference_note: str | None = None
    coverage: IntentCoverage | None = None
    # True only when the plan may be presented as the user's plan.
    is_valid: bool = True
    conflicts: tuple[PlanningConflict, ...] = ()
    removed_stops: tuple[RemovedStop, ...] = ()


@dataclass(frozen=True)
class PlanningConflict:
    """A stated requirement that cannot be met as things stand."""

    kind: str
    message: str
    requirement_slug: str | None = None
    requirement_label: str | None = None


@dataclass(frozen=True)
class RemovedStop:
    """A stop dropped to satisfy a hard constraint, kept visible rather than hidden."""

    name: str
    reason: str


@dataclass(frozen=True)
class _Attempt:
    """One full pass of transport resolution plus scheduling for a stop set."""

    day_start: datetime
    stops: list[OrchestratedStop]
    legs: list[OrchestratedLeg]
    feasibility: ItineraryFeasibility


class ItineraryOrchestrator:
    """Builds a schedule in which transport has already been accounted for."""

    def __init__(self, mobility_service: MobilityPlanningService) -> None:
        self._mobility = mobility_service

    async def orchestrate(
        self,
        plan: Plan,
        stops: Sequence[OrchestrationStopInput],
        origin: str | None = None,
        preferred_modes: list[TransportMode] | None = None,
        party_size: int = 1,
        preferred_provider: str | None = None,
        selected_leg_options: dict[int, str] | None = None,
    ) -> OrchestratedPlan:
        origin_clean = origin.strip() if origin and origin.strip() else None
        requirements = _requirements_from_plan(plan)
        area = _plan_area(plan)

        usable = [s for s in stops if s.location and s.location.strip()]
        if not usable:
            # Nothing was proposed at all. When the user named an area, that is
            # the reason worth stating plainly rather than showing an empty day.
            if area is not None:
                return OrchestratedPlan(
                    origin=origin_clean,
                    origin_resolved=origin_clean is not None,
                    coverage=_coverage_for(requirements, ()),
                    is_valid=False,
                    conflicts=(_area_conflict(area),),
                )
            return OrchestratedPlan(origin=origin, origin_resolved=False)

        context = plan.context
        party = party_size or (context.group_size if context else 1) or 1
        modes = preferred_modes or _modes_from_context(context.transport_mode if context else None)

        requested = list(usable)
        removed: list[RemovedStop] = []
        conflicts: list[PlanningConflict] = []

        # A stop the user placed outside their stated area is removed before any
        # transport is priced or time is scheduled. Broadening the day to
        # wherever the venues happen to be is not a re-plan, it is a different
        # day from the one that was asked for.
        if area is not None:
            in_area: list[OrchestrationStopInput] = []
            for stop in requested:
                verdict = _stop_area_verdict(area, stop)
                if verdict.status is AreaStatus.MATCH:
                    in_area.append(stop)
                else:
                    removed.append(RemovedStop(name=stop.name, reason=verdict.reason))
            if not in_area:
                # Nothing survives the area the user asked for. Say so plainly
                # instead of returning the day we would have built anyway.
                return OrchestratedPlan(
                    origin=origin_clean,
                    origin_resolved=origin_clean is not None,
                    coverage=_coverage_for(requirements, ()),
                    is_valid=False,
                    conflicts=(_area_conflict(area),),
                    removed_stops=tuple(removed),
                )
            requested = in_area

        # Transport is resolved, then the schedule is fixed, then the result is
        # checked against the user's hard constraints. A constraint violation
        # triggers a re-plan over fewer stops rather than a warning on a plan
        # the user would have to notice and fix themselves.
        attempt: _Attempt | None = None

        while requested:
            attempt = await self._attempt(
                plan,
                requested,
                origin_clean,
                modes,
                party,
                preferred_provider=preferred_provider,
                selected_leg_options=selected_leg_options,
            )
            blocker = _hard_blocker(attempt, plan, area)
            if blocker is None:
                break
            violation, reason, offender = blocker
            if len(requested) == 1:
                # One stop is the floor: dropping more would be an empty day, so the
                # limit cannot be met and that is reported as an unmet constraint.
                conflicts.append(_conflict_from_violation(violation, area))
                break
            # When the reason names a stop, that is the stop to drop. Dropping an
            # arbitrary one instead discloses "X was removed because Y is closed"
            # and sends the user looking for the wrong venue. A violation that
            # belongs to the day as a whole names no single stop, so the last one
            # goes, as before.
            index = len(requested) - 1 if offender is None else min(offender, len(requested) - 1)
            dropped = requested.pop(max(index, 0))
            removed.append(RemovedStop(name=dropped.name, reason=reason))

        if attempt is None:
            return OrchestratedPlan(origin=origin_clean, origin_resolved=origin_clean is not None)

        coverage = _coverage_for(requirements, attempt.stops)

        pref_label = _preference_label(modes)
        if preferred_provider:
            provider_labels = {
                "myciti": "MyCiTi",
                "prasa_metrorail": "PRASA Metrorail",
                "prasa": "PRASA Metrorail",
                "golden_arrow": "Golden Arrow",
                "uber": "Uber",
                "bolt": "Bolt",
                "indrive": "inDrive",
                "walking": "Walking",
            }
            pref_label = provider_labels.get(preferred_provider.lower(), preferred_provider.replace("_", " ").title())

        # `is_valid` is about hard constraints only. A successful re-plan has
        # already honoured the user's limits, so it is valid — the removals are
        # disclosed rather than blocking. An uncovered requirement is likewise
        # reported in the coverage, not treated as a violated constraint.
        return OrchestratedPlan(
            origin=origin_clean,
            origin_resolved=origin_clean is not None,
            stops=attempt.stops,
            legs=attempt.legs,
            feasibility=attempt.feasibility,
            day_start=attempt.day_start,
            transport_preference=pref_label,
            transport_preference_honoured=_plan_preference_honoured(attempt.legs),
            transport_preference_note=_plan_preference_note(attempt.legs),
            coverage=coverage,
            is_valid=not conflicts,
            conflicts=tuple(conflicts),
            removed_stops=tuple(removed),
        )

    async def _attempt(
        self,
        plan: Plan,
        usable: Sequence[OrchestrationStopInput],
        origin_clean: str | None,
        modes: list[TransportMode],
        party: int,
        preferred_provider: str | None = None,
        selected_leg_options: dict[int, str] | None = None,
    ) -> _Attempt:
        """Resolve transport for `usable`, then schedule from the chosen travel."""
        points = self._sequence_points(usable, origin_clean)
        # Every leg is evaluated up front, including origin -> first stop. The
        # result is index-aligned with consecutive point pairs, so a leg that
        # needs no travel (same location) is a real `None` rather than a shift.
        legs = await self._mobility.evaluate_aligned_legs(
            points, party_size=party, preferred_modes=modes
        )

        leg_offset = 1 if origin_clean else 0
        venue_cost = sum((s.estimated_cost or Decimal("0")) for s in usable)
        budget_max = _budget_max(plan)
        remaining = (budget_max - venue_cost) if budget_max is not None else None

        # Constraint-aware selection, leg by leg, spending the remaining budget
        # as it is committed rather than evaluating each leg in isolation.
        selections: list[MobilityOption | None] = []
        for index, transition in enumerate(legs):
            if transition is None:
                selections.append(None)
                continue
            leg_selected_id = None
            if selected_leg_options:
                leg_selected_id = selected_leg_options.get(index)
                if leg_selected_id is None:
                    leg_selected_id = selected_leg_options.get(str(index))
            selected = _select_option(
                transition.available_options,
                preferred_modes=modes,
                budget_remaining=remaining,
                preferred_provider=preferred_provider,
                selected_option_id=leg_selected_id,
            )
            if selected is not None:
                # The transition must describe the option the schedule uses.
                transition.apply_selected_option(selected)
            selections.append(selected)
            if selected is not None and selected.cost is not None and remaining is not None:
                remaining -= selected.cost

        start, orchestrated, orchestrated_legs = self._schedule(
            plan, usable, origin_clean, points, legs, selections, leg_offset, modes
        )
        feasibility = self._feasibility(plan, orchestrated, orchestrated_legs)
        return _Attempt(
            day_start=start,
            stops=orchestrated,
            legs=orchestrated_legs,
            feasibility=feasibility,
        )

    def _sequence_points(
        self, stops: Sequence[OrchestrationStopInput], origin: str | None
    ) -> list[StopSequencePoint]:
        """The ordered points mobility is evaluated between.

        The venue address is preferred over `location` because a candidate's location is
        often only its area ("Cape Town"). Routing on the area alone would make distinct
        venues look like the same place and drop the travel between them.
        """
        points: list[StopSequencePoint] = []
        if origin:
            # The origin is named on the first leg so the route is stated, not implied.
            points.append(StopSequencePoint(location=origin, name=_origin_label(origin)))
        for stop in stops:
            route_key = (stop.address or "").strip() or stop.location.strip()
            points.append(StopSequencePoint(location=route_key, name=stop.name))
        return points

    def _schedule(
        self,
        plan: Plan,
        stops: Sequence[OrchestrationStopInput],
        origin: str | None,
        points: Sequence[StopSequencePoint],
        legs: Sequence[PlanTransition | None],
        selections: Sequence[MobilityOption | None],
        leg_offset: int,
        preferred_modes: Sequence[TransportMode] | None = None,
    ) -> tuple[datetime, list[OrchestratedStop], list[OrchestratedLeg]]:
        """Assign windows from the selected travel times.

        The cursor only advances by real, selected travel time. A leg whose
        duration is unknown advances by nothing and is reported as unknown,
        rather than padding the schedule with a guessed buffer.
        """
        # `date + timedelta` is day-granular in Python and would silently drop the
        # clock time, so the day's start is combined into a real instant.
        day_start = _day_start(plan)
        cursor = day_start

        # Travel needed to reach the very first stop.
        if origin and legs:
            first = selections[0] if selections else None
            if first is not None and first.duration_minutes:
                cursor += timedelta(minutes=first.duration_minutes)

        orchestrated: list[OrchestratedStop] = []
        for index, stop in enumerate(stops):
            duration = stop.duration_minutes or DEFAULT_STOP_MINUTES
            start_time = cursor
            end_time = cursor + timedelta(minutes=duration)

            specs = tuple(
                derive_venue_action_specs(
                    name=stop.name,
                    location=stop.address or stop.location,
                    source_url=stop.source_url,
                    phone=stop.phone,
                    reservation_url=stop.reservation_url,
                )
            )
            orchestrated.append(
                OrchestratedStop(
                    name=stop.name,
                    location=stop.location,
                    address=stop.address or stop.location,
                    opening_hours=stop.opening_hours,
                    phone=stop.phone,
                    source_url=stop.source_url,
                    reservation_url=stop.reservation_url,
                    category=stop.category,
                    estimated_cost=stop.estimated_cost,
                    duration_minutes=duration,
                    start_time=start_time,
                    end_time=end_time,
                    actions=specs,
                    contact_hint=contact_fallback_label(list(specs)),
                    description=stop.description,
                )
            )
            cursor = end_time

            # Advance by the selected travel time into the *next* stop.
            next_index = index + 1
            if next_index < len(stops):
                leg = legs[leg_offset + index]
                selected = selections[leg_offset + index] if (leg_offset + index) < len(selections) else None
                if selected is not None and selected.duration_minutes:
                    cursor += timedelta(minutes=selected.duration_minutes)

        orchestrated_legs = self._build_legs(
            points, legs, selections, leg_offset, stops, preferred_modes
        )
        return day_start, orchestrated, orchestrated_legs

    def _build_legs(
        self,
        points: Sequence[StopSequencePoint],
        legs: Sequence[PlanTransition | None],
        selections: Sequence[MobilityOption | None],
        leg_offset: int,
        stops: Sequence[OrchestrationStopInput],
        preferred_modes: Sequence[TransportMode] | None = None,
    ) -> list[OrchestratedLeg]:
        labels = [p.name or p.location for p in points]
        built: list[OrchestratedLeg] = []
        for index, transition in enumerate(legs):
            if transition is None:
                continue
            selected = selections[index] if index < len(selections) else None
            options = list(transition.available_options)
            # Alternatives are other *ways* to make this leg, so the chosen
            # provider is excluded entirely rather than repeated as a rival.
            alternatives = tuple(
                option
                for option in options
                if selected is None or option.provider_id != selected.provider_id
            )
            sorted_alternatives = tuple(
                sorted(alternatives, key=lambda o: (o.duration_minutes is None, o.duration_minutes or 0))
            )
            all_sorted_options = tuple(
                sorted(options, key=lambda o: (o.duration_minutes is None, o.duration_minutes or 0))
            )
            preference_honoured, preference_note = _preference_status(
                selected, options, preferred_modes
            )
            reason = _selection_reason(selected, sorted_alternatives, transition, preference_note)
            built.append(
                OrchestratedLeg(
                    transition=transition,
                    from_label=labels[index] if index < len(labels) else "",
                    to_label=labels[index + 1] if index + 1 < len(labels) else "",
                    selected_option_id=selected.id if selected else None,
                    alternatives=sorted_alternatives,
                    all_options=all_sorted_options,
                    reason=reason,
                    preference_honoured=preference_honoured,
                    preference_note=preference_note,
                )
            )
        return built

    def _feasibility(
        self,
        plan: Plan,
        stops: Sequence[OrchestratedStop],
        legs: Sequence[OrchestratedLeg],
    ) -> ItineraryFeasibility:
        """Assess the orchestrated day against the plan's real constraints.

        Because windows are derived from selected travel, the only way a leg is
        infeasible here is a genuinely blocking live report or a deadline that the
        real travel times overrun.
        """
        issues: list[str] = []
        warnings: list[str] = []

        for leg in legs:
            if not leg.transition.is_feasible and leg.transition.feasibility_issue:
                issues.append(leg.transition.feasibility_issue)

        total_travel = sum(
            leg.transition.duration_minutes or 0 for leg in legs
        )
        known_cost = Decimal("0")
        unknown_cost = False
        for leg in legs:
            if leg.transition.cost is not None and leg.transition.cost_known:
                known_cost += leg.transition.cost
            else:
                unknown_cost = True
        if unknown_cost:
            warnings.append(
                "At least one transport leg has no verified fare, so the transport "
                "portion of the budget is a lower bound."
            )

        context = plan.context
        deadline = _plan_deadline(plan)

        deadline_respected = True
        if deadline and stops:
            finish = stops[-1].end_time
            if finish > deadline:
                deadline_respected = False
                issues.append(
                    f"The day now ends at {finish:%H:%M}, after your {deadline:%H:%M} limit."
                )

        budget_max = _budget_max(plan)
        venue_cost = sum((s.estimated_cost or Decimal("0")) for s in stops)
        budget_respected = True
        if budget_max is not None:
            total = venue_cost + known_cost
            if total > budget_max:
                budget_respected = False
                issues.append(
                    f"Venue and verified transport costs total R{total:.2f}, over your "
                    f"R{budget_max:.2f} budget."
                )

        return ItineraryFeasibility(
            is_feasible=not issues,
            deadline_respected=deadline_respected,
            budget_respected=budget_respected,
            transitions_feasible=all(leg.transition.is_feasible for leg in legs),
            issues=issues,
            warnings=warnings,
            total_transition_duration_minutes=total_travel,
            total_known_transition_cost=known_cost,
            has_unknown_transition_costs=unknown_cost,
        )


def _select_option(
    options: Sequence[MobilityOption],
    preferred_modes: Sequence[TransportMode] | None = None,
    budget_remaining: Decimal | None = None,
    preferred_provider: str | None = None,
    selected_option_id: str | None = None,
) -> MobilityOption | None:
    """Choose the leg option that satisfies the plan's actual constraints.

    This is a constraint filter followed by a stable preference order, not a
    user-facing score: an option is chosen because it fits the budget, matches a
    stated preference, avoids transfers and is quick, in that order of authority.
    """
    if not options:
        return None

    # Explicit user leg selection wins unconditionally if available on this leg
    if selected_option_id:
        clean_sel = selected_option_id.strip().lower().replace("_", "-")
        for opt in options:
            if opt.id.strip().lower().replace("_", "-") == clean_sel:
                return opt
        for opt in options:
            pid = opt.provider_id.strip().lower().replace("_", "-")
            if (
                pid == clean_sel
                or clean_sel.startswith(pid)
                or pid.startswith(clean_sel)
                or pid in clean_sel
                or (pid.startswith("prasa") and clean_sel.startswith("prasa"))
                or (pid.startswith("myciti") and clean_sel.startswith("myciti"))
                or (pid.startswith("uber") and clean_sel.startswith("uber"))
                or (pid.startswith("bolt") and clean_sel.startswith("bolt"))
                or (pid.startswith("indrive") and clean_sel.startswith("indrive"))
                or (pid.startswith("walk") and clean_sel.startswith("walk"))
            ):
                return opt

    candidates = list(options)

    # A stated provider preference outranks general mode preference
    if preferred_provider:
        prov_clean = preferred_provider.strip().lower()
        matching_provider = [
            o
            for o in candidates
            if o.provider_id.lower() == prov_clean
            or prov_clean in o.provider_id.lower()
            or prov_clean in o.provider_name.lower()
        ]
        if matching_provider:
            candidates = matching_provider

    # A stated transport preference outranks convenience.
    if preferred_modes:
        preferred = [o for o in candidates if o.mode in preferred_modes]
        if preferred:
            candidates = preferred

    # Budget: an option with a verified cost that overruns what is left is not
    # viable. Options with an unknown cost cannot be ruled out, so they survive.
    if budget_remaining is not None:
        affordable = [
            o
            for o in candidates
            if o.cost is None or o.cost <= budget_remaining
        ]
        if affordable:
            candidates = affordable

    if not candidates:
        return None

    def rank(option: MobilityOption) -> tuple:
        return (
            option.transfers,
            option.duration_minutes is None,
            option.duration_minutes if option.duration_minutes is not None else 10**6,
            # Prefer a verified cost over an unknown one at equal travel time.
            option.cost is None,
            option.cost if option.cost is not None else Decimal("0"),
            option.provider_name,
        )

    return sorted(candidates, key=rank)[0]


def _plan_deadline(plan: Plan) -> datetime | None:
    """The latest the day may finish — only when the user actually stated it.

    A default window (an inferred "afternoon" end, or a standard duration limit) is
    guidance, not a limit. Treating it as hard would silently drop stops from a day
    the user never bounded, so only an explicit deadline is enforced.
    """
    for constraint in plan.constraints:
        if constraint.type is not ConstraintType.REQUIREMENT:
            continue
        if not constraint.value.startswith("deadline:"):
            continue
        raw = constraint.value.split(":", 1)[1].strip()
        parts = raw.split(":")
        if len(parts) < 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        context = plan.context
        start = context.start_time if context else None
        day = start.date() if start is not None else datetime.now().date()
        if start is not None and start.tzinfo is not None:
            # The user stated a wall-clock time ("finished by 15:30") while stored
            # instants are UTC. Convert the stated time into the same frame as the
            # plan's own start, or the comparison silently grants extra hours.
            try:
                local_tz = ZoneInfo("Africa/Johannesburg")
            except Exception:
                local_tz = datetime.now().astimezone().tzinfo
            deadline = datetime.combine(day, time(hour=hour, minute=minute), tzinfo=local_tz)
            deadline = deadline.astimezone(start.tzinfo)
        else:
            deadline = datetime.combine(day, time(hour=hour, minute=minute))
        if start is not None and deadline < start:
            # An evening deadline means the next morning's end, not a time already past.
            deadline += timedelta(days=1)
        return deadline
    return None


def _requirements_from_plan(plan: Plan) -> tuple[IntentRequirement, ...]:
    """The distinct things the user asked for, read back off the plan."""
    slugs: list[str] = []
    for constraint in plan.constraints:
        if (
            constraint.type is ConstraintType.REQUIREMENT
            and constraint.value.startswith("requirement:")
        ):
            slugs.append(constraint.value.split(":", 1)[1])
    return requirements_from_slugs(tuple(slugs))


def _coverage_for(
    requirements: tuple[IntentRequirement, ...], stops: Sequence[OrchestratedStop]
) -> IntentCoverage:
    """Coverage of the user's requirements over the stops actually in the plan."""
    if not requirements:
        return IntentCoverage(items=())
    evidence = tuple(
        (stop.name, CandidateEvidence(name=stop.name, description=stop.description, address=stop.address or "", location=stop.location))
        for stop in stops
    )
    return evaluate_coverage(requirements, evidence)


def _plan_area(plan: Plan) -> AreaScope | None:
    """The geographic constraint the plan carries, if the user stated one.

    Read from the persisted `area:` requirement so the plan keeps the area as
    structured intent. A plan whose context still names a specific place is also
    honoured, which covers plans created before the requirement was recorded; a
    city-level context resolves to no scope and so constrains nothing.
    """
    for constraint in plan.constraints:
        if (
            constraint.type is ConstraintType.REQUIREMENT
            and constraint.value.startswith("area:")
        ):
            scope = resolve_area_scope(constraint.value.split(":", 1)[1])
            if scope is not None:
                return scope
    context = plan.context
    if context is not None:
        return resolve_area_scope(context.location)
    return None


def _stop_area_verdict(area: AreaScope, stop: OrchestrationStopInput | OrchestratedStop) -> AreaVerdict:
    """Where a stop actually is, judged against the area the user asked for."""
    return classify_in_area(area, address=stop.address, location=stop.location, name=stop.name)


def _area_conflict(area: AreaScope) -> PlanningConflict:
    return PlanningConflict(
        kind="area",
        message=(
            f"I couldn't build the day within {area.label} with the requirements you gave me. "
            f"I haven't widened the search to the rest of the city — tell me a different area, "
            f"or which requirements to relax."
        ),
    )


def _closed_at_scheduled_time(stop: OrchestratedStop) -> str | None:
    """Why this stop cannot be visited at the time it is actually scheduled.

    Venue hours are wall-clock times while the schedule is held in UTC, so a stop
    is checked at its own local start. Checking every stop against the time the
    day begins would wave through a 19:30 dinner at a venue that shut at 16:00,
    because the day happened to start at 11:00.
    """
    if not stop.opening_hours or not stop.opening_hours.strip():
        return None
    local_start = stop.start_time.astimezone()
    schedule = parse_opening_hours(stop.opening_hours)
    open_enough = schedule.can_accommodate(
        local_start.strftime("%A"),
        local_start.time(),
        duration_minutes=stop.duration_minutes,
    )
    if open_enough is False:
        return f"it is closed at {local_start:%H:%M} (hours: {stop.opening_hours})"
    return None


def _hard_blocker(
    attempt: _Attempt,
    plan: Plan,
    area: AreaScope | None = None,
) -> tuple[str, str, int | None] | None:
    """The hard constraint this attempt violates, as (kind, reason, stop index).

    The index is the position of the stop the violation is *about*, so the caller
    drops that stop rather than an arbitrary one. It is None when the violation
    belongs to the day as a whole. `attempt.stops` is index-aligned with the stops
    the caller passed in.

    A hard constraint is one the user stated as a limit. Uncertainty — an
    unknown fare, a stop with no live feed — is a warning, not a blocker, and
    never causes a stop to be dropped.
    """
    if area is not None:
        for index, stop in enumerate(attempt.stops):
            verdict = _stop_area_verdict(area, stop)
            if verdict.status is not AreaStatus.MATCH:
                return (
                    "area",
                    f"it is not in the {area.label} ({verdict.reason})",
                    index,
                )
    for index, stop in enumerate(attempt.stops):
        closed = _closed_at_scheduled_time(stop)
        if closed is not None:
            return "opening_hours", closed, index
    feasibility = attempt.feasibility
    if not feasibility.deadline_respected:
        deadline = _plan_deadline(plan)
        finish = attempt.stops[-1].end_time if attempt.stops else None
        reason = "it would have finished after your limit"
        if deadline is not None:
            reason += f" of {deadline:%H:%M}"
        if finish is not None:
            reason += f" (it ends at {finish:%H:%M})"
        # The final stop is what runs past the limit, so it is the one to drop.
        return "deadline", reason, (len(attempt.stops) - 1 if attempt.stops else None)
    if not feasibility.budget_respected:
        return "budget", "it pushed the day over your budget", None
    return None


def _conflict_from_violation(
    violation: str, area: AreaScope | None = None
) -> PlanningConflict:
    if violation == "area" and area is not None:
        return _area_conflict(area)
    if violation == "opening_hours":
        return PlanningConflict(
            kind="opening_hours",
            message=(
                "Every option I have for this is closed at the time we would reach it, "
                "even with a single stop. Start the day earlier, or tell me which stop to drop."
            ),
        )
    if violation == "deadline":
        return PlanningConflict(
            kind="deadline",
            message=(
                "This cannot be finished inside the time you gave, even with a single stop. "
                "Extend the time, or tell me which of the stops to drop."
            ),
        )
    return PlanningConflict(
        kind="budget",
        message=(
            "This cannot fit the budget you set, even with a single stop. Raise the budget, "
            "or tell me which of the stops to drop."
        ),
    )


def _origin_label(origin: str) -> str:
    """A readable label for the starting point; raw coordinates are not a place name."""
    if re.fullmatch(r"-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?", origin.strip()):
        return "Your start"
    return origin.strip()


def _preference_label(preferred_modes: Sequence[TransportMode] | None) -> str | None:
    if not preferred_modes:
        return None
    return " or ".join(sorted({m.value.replace("_", " ") for m in preferred_modes}))


def _plan_preference_honoured(legs: Sequence[OrchestratedLeg]) -> bool | None:
    """True when every leg used the preference, false when any leg could not."""
    statuses = [leg.preference_honoured for leg in legs if leg.preference_honoured is not None]
    if not statuses:
        return None
    return all(statuses)


def _plan_preference_note(legs: Sequence[OrchestratedLeg]) -> str | None:
    """One summary sentence, rather than a run-on of every leg's explanation."""
    missed = [leg for leg in legs if leg.preference_honoured is False]
    if not missed:
        return None
    modes = sorted({m for leg in missed for m in _available_modes(leg)})
    available = f" Available on these legs: {', '.join(modes)}." if modes else ""
    return f"Your transport choice could not be used on {len(missed)} of {len(legs)} legs.{available}"


def _available_modes(leg: OrchestratedLeg) -> list[str]:
    return sorted({o.mode.value.replace("_", " ") for o in leg.transition.available_options})


def _preference_status(
    selected: MobilityOption | None,
    options: Sequence[MobilityOption],
    preferred_modes: Sequence[TransportMode] | None,
) -> tuple[bool | None, str | None]:
    """Whether the user's stated transport preference was actually used for this leg.

    Returns (honoured, note). `honoured` is None when no preference was stated, so
    a default-ranked leg is never reported as contradicting the user.
    """
    if not preferred_modes:
        return None, None

    label = " or ".join(sorted({m.value.replace("_", " ") for m in preferred_modes}))
    if selected is not None and selected.mode in preferred_modes:
        return True, None

    if not options:
        return False, (
            f"No verified {label} service connects this leg, so no transport could be planned for it."
        )

    available = sorted({o.mode.value.replace("_", " ") for o in options})
    return False, (
        f"You asked for {label}, but this leg is not served by it. "
        f"Available here: {', '.join(available)}."
    )


def _selection_reason(
    selected: MobilityOption | None,
    alternatives: Sequence[MobilityOption],
    transition: PlanTransition,
    preference_note: str | None = None,
) -> str | None:
    """Explain the choice in planning terms, without exposing a score."""
    if selected is None:
        if not transition.available_options:
            return "No transport provider could verify this leg."
        return preference_note
    if preference_note:
        return preference_note
    if selected.cost is None:
        return f"Chosen for time and simplicity; {selected.provider_name} has no verified fare."
    if not alternatives:
        return f"The only option with verified time and cost for this leg."
    return None


def _modes_from_context(transport_mode: str | None) -> list[TransportMode]:
    if not transport_mode:
        return []
    normalized = transport_mode.strip().lower()
    if normalized in {"public_transport", "transit", "public_transit"}:
        return [TransportMode.BUS, TransportMode.TRAIN, TransportMode.SHUTTLE]
    try:
        return [TransportMode(normalized)]
    except ValueError:
        return []


def _budget_max(plan: Plan) -> Decimal | None:
    for constraint in plan.constraints:
        if constraint.type is ConstraintType.BUDGET_MAX and constraint.numeric_value is not None:
            return Decimal(str(constraint.numeric_value))
    return None


def _day_start(plan: Plan) -> datetime:
    """Pick the day's starting instant from explicit context only.

    With no stated start time this defaults to 11:00, the same allowance the
    adaptation service uses, and says so rather than pretending to know.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    context = plan.context
    if context and context.start_time:
        return context.start_time
    return datetime.combine(_dt.now(UTC).date(), _dt.min.time()) + timedelta(minutes=11 * 60)
