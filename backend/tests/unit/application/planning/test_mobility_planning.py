from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.mobility.registry import MobilityProviderRegistry
from app.application.mobility.service import MobilityService
from app.application.planning.adaptation_service import PlanAdaptationService
from app.application.planning.decision_service import PlanningDecisionService
from app.application.planning.information import PlanningInformationService
from app.application.planning.mobility_planning_service import (
    MobilityPlanningService,
    StopSequencePoint,
)
from app.application.planning.planning_service import PlanningService
from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveStatus,
    TransportMode,
)
from app.domain.entities.mobility.models import (
    MobilityEvidence,
    MobilityOption,
    MobilityRequirement,
    ProviderCapability,
)
from app.domain.entities.planning.adaptation import ChangeType
from app.domain.entities.planning.constraint import Constraint, ConstraintType
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.decision import (
    CandidateType,
    DecisionCandidate,
    DecisionReason,
    DecisionResult,
    ReasonOutcome,
    ReasonType,
)
from app.domain.entities.planning.information import InformationCategory, InformationSource
from app.domain.entities.planning.plan import Plan, PlanStatus
from app.domain.entities.planning.plan_item import PlanItem, PlanItemType
from app.domain.ports.mobility.ports import MobilityProviderPort


@pytest.fixture
def mock_planning_service() -> MagicMock:
    service = MagicMock(spec=PlanningService)
    service.get_plan = AsyncMock()
    service._repository = MagicMock()
    service._repository.update = AsyncMock()
    return service


@pytest.fixture
def mock_decision_service() -> MagicMock:
    service = MagicMock(spec=PlanningDecisionService)
    service.recommend = AsyncMock()
    return service


@pytest.fixture
def mock_info_service() -> MagicMock:
    service = MagicMock(spec=PlanningInformationService)
    service.source = InformationSource(
        data_source="fixture",
        is_live=False,
        attribution=None,
        freshness="fixture",
    )
    return service


class MockWalkingProvider(MobilityProviderPort):
    """Mock walking provider that returns walking options for nearby locations."""
    
    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="walking",
            name="Walking",
            supported_modes=[TransportMode.WALK],
            has_route_data=True,
            has_timetable=False,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=True,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            is_enabled=True,
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        # Return walking option for nearby locations (same area)
        origin_lower = requirement.origin.lower()
        dest_lower = requirement.destination.lower()
        
        # If same area, walking is available
        if "buitenkant" in origin_lower and "buitenkant" in dest_lower:
            return [MobilityOption(
                id="walk-1",
                provider_id="walking",
                provider_name="Walking",
                mode=TransportMode.WALK,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=5,
                cost=Decimal("0"),
                cost_is_unknown=False,
                currency="ZAR",
                confidence=0.95,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.NO_BOOKING,
                summary="5 min walk",
            )]
        
        # For CBD to nearby area, walking ~15 min
        if ("bree" in origin_lower and "greenmarket" in dest_lower) or \
           ("greenmarket" in origin_lower and "bree" in dest_lower):
            return [MobilityOption(
                id="walk-1",
                provider_id="walking",
                provider_name="Walking",
                mode=TransportMode.WALK,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=12,
                cost=Decimal("0"),
                cost_is_unknown=False,
                currency="ZAR",
                confidence=0.9,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.NO_BOOKING,
                summary="12 min walk",
            )]
        
        # For longer distances, no walking
        return []

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None


class MockMyCiTiProvider(MobilityProviderPort):
    """Mock MyCiTi bus provider."""
    
    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="myciti",
            name="MyCiTi",
            supported_modes=[TransportMode.BUS],
            has_route_data=True,
            has_timetable=True,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=True,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            is_enabled=True,
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        origin_lower = requirement.origin.lower()
        dest_lower = requirement.destination.lower()
        
        # CBD to Camps Bay
        if "cbd" in origin_lower and "camps bay" in dest_lower:
            return [MobilityOption(
                id="myciti-1",
                provider_id="myciti",
                provider_name="MyCiTi",
                mode=TransportMode.BUS,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=35,
                cost=Decimal("22.00"),
                cost_is_unknown=False,
                currency="ZAR",
                transfers=0,
                confidence=0.85,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.NO_BOOKING,
                summary="MyCiTi 101 to Camps Bay (35 min, R22)",
            )]
        
        # Generic bus option for other routes
        if requirement.preferred_modes and TransportMode.BUS in requirement.preferred_modes:
            return [MobilityOption(
                id="myciti-1",
                provider_id="myciti",
                provider_name="MyCiTi",
                mode=TransportMode.BUS,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=30,
                cost=Decimal("20.00"),
                cost_is_unknown=False,
                currency="ZAR",
                transfers=0,
                confidence=0.8,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.NO_BOOKING,
                summary="MyCiTi bus (30 min, R20)",
            )]
        
        return []

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None


class MockRideHailProvider(MobilityProviderPort):
    """Mock ride-hail provider (Uber/Bolt) with unknown fares."""
    
    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="uber",
            name="Uber",
            supported_modes=[TransportMode.RIDE_HAIL],
            has_route_data=True,
            has_timetable=False,
            has_realtime=True,
            has_service_alerts=False,
            has_fare_estimates=False,  # Dynamic pricing
            booking_capability=BookingCapability.DEEPLINK,
            api_available=True,
            auth_required=True,
            is_enabled=True,
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        origin_lower = requirement.origin.lower()
        dest_lower = requirement.destination.lower()
        
        # Gardens to Observatory
        if "garden" in origin_lower and "observatory" in dest_lower:
            return [MobilityOption(
                id="uber-1",
                provider_id="uber",
                provider_name="Uber",
                mode=TransportMode.RIDE_HAIL,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=18,
                cost=None,  # Unknown fare - dynamic pricing
                cost_is_unknown=True,
                currency="ZAR",
                transfers=0,
                confidence=0.75,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.DEEPLINK,
                booking_url="https://m.uber.com/ul/?pickup=Gardens&dropoff=Observatory",
                summary="UberX to Observatory (~18 min, fare confirmed in app)",
            )]
        
        # Generic ride-hail for other routes
        if requirement.preferred_modes and TransportMode.RIDE_HAIL in requirement.preferred_modes:
            return [MobilityOption(
                id="uber-1",
                provider_id="uber",
                provider_name="Uber",
                mode=TransportMode.RIDE_HAIL,
                origin=requirement.origin,
                destination=requirement.destination,
                duration_minutes=20,
                cost=None,  # Always unknown for ride-hail
                cost_is_unknown=True,
                currency="ZAR",
                transfers=0,
                confidence=0.7,
                live_status=MobilityLiveStatus.UNKNOWN,
                booking_capability=BookingCapability.DEEPLINK,
                booking_url="https://m.uber.com/ul/",
                summary="UberX (~20 min, fare confirmed in app)",
            )]
        
        return []

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None


class MockGenericProvider(MobilityProviderPort):
    """Generic provider for fallback options."""
    
    def __init__(self, mode: TransportMode, duration: int, cost: Decimal | None = None):
        self._mode = mode
        self._duration = duration
        self._cost = cost
        self._provider_id = mode.value
        self._name = mode.value.title()

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self._provider_id,
            name=self._name,
            supported_modes=[self._mode],
            has_route_data=True,
            has_timetable=True,
            has_realtime=False,
            has_service_alerts=False,
            has_fare_estimates=self._cost is not None,
            booking_capability=BookingCapability.NO_BOOKING,
            api_available=False,
            auth_required=False,
            is_enabled=True,
        )

    async def get_options(self, requirement: MobilityRequirement) -> list[MobilityOption]:
        return [MobilityOption(
            id=f"{self._provider_id}-1",
            provider_id=self._provider_id,
            provider_name=self._name,
            mode=self._mode,
            origin=requirement.origin,
            destination=requirement.destination,
            duration_minutes=self._duration,
            cost=self._cost,
            cost_is_unknown=self._cost is None,
            currency="ZAR",
            transfers=0,
            confidence=0.6,
            live_status=MobilityLiveStatus.UNKNOWN,
            booking_capability=BookingCapability.NO_BOOKING,
            summary=f"{self._name} ({self._duration} min)" + (f", R{self._cost}" if self._cost else ", fare unknown"),
        )]

    async def get_live_status(self, option_id: str) -> MobilityEvidence | None:
        return None


@pytest.fixture
def mobility_planning_service() -> MobilityPlanningService:
    registry = MobilityProviderRegistry()
    registry.register(MockWalkingProvider())
    registry.register(MockMyCiTiProvider())
    registry.register(MockRideHailProvider())
    registry.register(MockGenericProvider(TransportMode.TRAIN, 25, Decimal("18")))
    mob_service = MobilityService(registry)
    return MobilityPlanningService(mobility_service=mob_service)


@pytest.mark.asyncio
async def test_walking_transition_between_nearby_stops(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    item1 = PlanItem(
        plan_id=uuid4(),
        name="Truth Coffee",
        item_type=PlanItemType.FOOD,
        location="Buitenkant St, Cape Town CBD",
        start_time=now,
        end_time=now + timedelta(hours=1),
        position=0,
    )
    item2 = PlanItem(
        plan_id=uuid4(),
        name="District Six Museum",
        item_type=PlanItemType.ACTIVITY,
        location="Buitenkant St & Albertus St, Cape Town CBD",
        start_time=now + timedelta(hours=1, minutes=30),
        end_time=now + timedelta(hours=2, minutes=30),
        position=1,
    )
    plan = Plan(
        user_id=uuid4(),
        intention="Coffee and museum in Cape Town CBD",
        status=PlanStatus.DRAFT,
        items=[item1, item2],
    )

    transitions = await mobility_planning_service.evaluate_transitions(plan)
    assert len(transitions) == 1
    t = transitions[0]
    assert t.mode == TransportMode.WALK
    assert t.duration_minutes is not None
    assert t.duration_minutes <= 15
    assert t.cost == Decimal("0")
    assert t.cost_known is True
    assert t.is_feasible is True


@pytest.mark.asyncio
async def test_transit_transition_myciti(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    item1 = PlanItem(
        plan_id=uuid4(),
        name="Civic Centre",
        item_type=PlanItemType.ACTIVITY,
        location="Cape Town CBD",
        start_time=now,
        end_time=now + timedelta(hours=1),
        position=0,
    )
    item2 = PlanItem(
        plan_id=uuid4(),
        name="Camps Bay Beach",
        item_type=PlanItemType.ACTIVITY,
        location="Camps Bay",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=4),
        position=1,
    )
    plan = Plan(
        user_id=uuid4(),
        intention="City center to Camps Bay",
        status=PlanStatus.DRAFT,
        items=[item1, item2],
    )

    transitions = await mobility_planning_service.evaluate_transitions(
        plan, preferred_modes=[TransportMode.BUS]
    )
    assert len(transitions) == 1
    t = transitions[0]
    assert t.mode == TransportMode.BUS
    assert "MyCiTi" in t.provider_name
    assert t.cost is not None
    assert t.cost > Decimal("0")
    assert t.cost_known is True
    assert len(t.available_options) > 0


@pytest.mark.asyncio
async def test_unknown_fare_preservation_for_ride_hail(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
    item1 = PlanItem(
        plan_id=uuid4(),
        name="Kloof Street House",
        item_type=PlanItemType.FOOD,
        location="Gardens, Cape Town",
        start_time=now,
        end_time=now + timedelta(hours=1, minutes=30),
        position=0,
    )
    item2 = PlanItem(
        plan_id=uuid4(),
        name="Observatory Cafe",
        item_type=PlanItemType.ACTIVITY,
        location="Observatory, Cape Town",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3, minutes=30),
        position=1,
    )
    plan = Plan(
        user_id=uuid4(),
        intention="Dinner in Gardens then drinks in Obs",
        status=PlanStatus.DRAFT,
        items=[item1, item2],
    )

    transitions = await mobility_planning_service.evaluate_transitions(
        plan, preferred_modes=[TransportMode.RIDE_HAIL]
    )
    assert len(transitions) == 1
    t = transitions[0]
    # Ride-hail must never invent fares
    assert t.mode == TransportMode.RIDE_HAIL
    assert t.cost is None
    assert t.cost_known is False
    assert t.booking_url is not None


def test_budget_feasibility_violation(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    item1 = PlanItem(
        plan_id=uuid4(),
        name="High-end Lunch",
        item_type=PlanItemType.FOOD,
        location="Camps Bay",
        start_time=now,
        end_time=now + timedelta(hours=1),
        estimated_cost=Decimal("450"),
        position=0,
    )
    item2 = PlanItem(
        plan_id=uuid4(),
        name="Spa Treatment",
        item_type=PlanItemType.ACTIVITY,
        location="Camps Bay",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=4),
        estimated_cost=Decimal("200"),
        position=1,
    )
    # Total items = 650. Transit = 20. Total = 670. Budget max = 600.
    budget_constraint = Constraint(
        plan_id=uuid4(),
        type=ConstraintType.BUDGET_MAX,
        value="600",
        numeric_value=Decimal("600"),
    )
    plan = Plan(
        user_id=uuid4(),
        intention="Luxury afternoon",
        status=PlanStatus.DRAFT,
        constraints=[budget_constraint],
        items=[item1, item2],
    )

    from app.domain.entities.planning.transition import PlanTransition

    transit = PlanTransition(
        from_location="Cape Town CBD",
        to_location="Camps Bay",
        cost=Decimal("20"),
        cost_known=True,
        mode=TransportMode.BUS,
        duration_minutes=25,
    )

    feasibility = mobility_planning_service.check_plan_feasibility(plan, [transit])
    assert feasibility.budget_respected is False
    assert feasibility.is_feasible is False
    assert any("exceeds maximum budget" in issue for issue in feasibility.issues)


def test_deadline_feasibility_violation(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    start = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
    deadline = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
    item1 = PlanItem(
        plan_id=uuid4(),
        name="Art Gallery",
        item_type=PlanItemType.ACTIVITY,
        location="CBD",
        start_time=start,
        end_time=start + timedelta(hours=2),
        position=0,
    )
    item2 = PlanItem(
        plan_id=uuid4(),
        name="Dinner",
        item_type=PlanItemType.FOOD,
        location="Kloof Street",
        start_time=start + timedelta(hours=3),
        end_time=start + timedelta(hours=5),  # Ends at 19:00, past 18:00
        position=1,
    )
    context = PlanningContext(
        plan_id=uuid4(),
        start_time=start,
        end_time=deadline,
        location="Cape Town",
    )
    plan = Plan(
        user_id=uuid4(),
        intention="Afternoon culture, home by 6",
        status=PlanStatus.DRAFT,
        context=context,
        items=[item1, item2],
    )

    feasibility = mobility_planning_service.check_plan_feasibility(plan, [])
    assert feasibility.deadline_respected is False
    assert feasibility.is_feasible is False
    assert any("exceeds the time limit" in issue for issue in feasibility.issues)


@pytest.mark.asyncio
async def test_tight_transition_window_detection(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    # Stop 1 ends at 11:00
    item1 = PlanItem(
        plan_id=uuid4(),
        name="CBD Meeting",
        item_type=PlanItemType.ACTIVITY,
        location="Cape Town CBD",
        start_time=now,
        end_time=now + timedelta(hours=1),
        position=0,
    )
    # Stop 2 starts at 11:05 (only 5 min gap) in Camps Bay (~30 min travel)
    item2 = PlanItem(
        plan_id=uuid4(),
        name="Camps Bay Lunch",
        item_type=PlanItemType.FOOD,
        location="Camps Bay",
        start_time=now + timedelta(hours=1, minutes=5),
        end_time=now + timedelta(hours=2, minutes=30),
        position=1,
    )
    plan = Plan(
        user_id=uuid4(),
        intention="Impossible tight transfer",
        status=PlanStatus.DRAFT,
        items=[item1, item2],
    )

    transitions = await mobility_planning_service.evaluate_transitions(plan)
    assert len(transitions) == 1
    t = transitions[0]
    assert t.is_feasible is False
    assert "exceeds available window" in (t.feasibility_issue or "")

    feasibility = mobility_planning_service.check_plan_feasibility(plan, transitions)
    assert feasibility.transitions_feasible is False
    assert feasibility.is_feasible is False


@pytest.mark.asyncio
async def test_evaluate_stop_sequence_for_unsaved_proposal(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    """A proposal has no persisted PlanItems, so mobility must work from stops alone."""
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    stops = [
        StopSequencePoint(
            location="Buitenkant St, Cape Town CBD",
            name="Coffee",
            start_time=now,
            end_time=now + timedelta(hours=1),
        ),
        StopSequencePoint(
            location="Buitenkant St & Albertus St, Cape Town CBD",
            name="Museum",
            start_time=now + timedelta(hours=1, minutes=30),
            end_time=now + timedelta(hours=2, minutes=30),
        ),
    ]

    transitions = await mobility_planning_service.evaluate_stop_sequence(stops)

    assert len(transitions) == 1
    t = transitions[0]
    assert t.from_location == "Buitenkant St, Cape Town CBD"
    assert t.to_location == "Buitenkant St & Albertus St, Cape Town CBD"
    assert t.mode == TransportMode.WALK
    assert t.duration_minutes == 5
    assert t.cost == Decimal("0")
    assert t.cost_known is True
    # Stop-sequence transitions are not tied to persisted items.
    assert t.from_item_id is None
    assert t.to_item_id is None


@pytest.mark.asyncio
async def test_evaluate_stop_sequence_needs_two_stops(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    assert await mobility_planning_service.evaluate_stop_sequence([]) == []
    assert (
        await mobility_planning_service.evaluate_stop_sequence(
            [StopSequencePoint(location="Gardens, Cape Town", name="Only")]
        )
        == []
    )


@pytest.mark.asyncio
async def test_evaluate_stop_sequence_skips_same_location_legs(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    stops = [
        StopSequencePoint(location="Civic Centre, Cape Town", name="A", end_time=now),
        StopSequencePoint(
            location="civic centre, cape town", name="B", start_time=now + timedelta(hours=1)
        ),
    ]

    # Same venue means no travel leg, so no transition is invented.
    assert await mobility_planning_service.evaluate_stop_sequence(stops) == []


@pytest.mark.asyncio
async def test_evaluate_stop_sequence_respects_tight_window(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    stops = [
        StopSequencePoint(
            location="Cape Town CBD",
            name="Brunch",
            start_time=now,
            end_time=now + timedelta(hours=1),
        ),
        StopSequencePoint(
            location="Camps Bay",
            name="Lunch",
            start_time=now + timedelta(hours=1, minutes=5),
            end_time=now + timedelta(hours=2),
        ),
    ]

    transitions = await mobility_planning_service.evaluate_stop_sequence(stops)

    assert len(transitions) == 1
    assert transitions[0].is_feasible is False
    assert "exceeds available window" in (transitions[0].feasibility_issue or "")


@pytest.mark.asyncio
async def test_evaluate_stop_sequence_keeps_unknown_cost_unknown(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    stops = [
        StopSequencePoint(location="Gardens, Cape Town", name="A", end_time=now),
        StopSequencePoint(location="Observatory, Cape Town", name="B", start_time=now + timedelta(hours=1)),
    ]

    transitions = await mobility_planning_service.evaluate_stop_sequence(
        stops, preferred_modes=[TransportMode.RIDE_HAIL]
    )

    assert len(transitions) == 1
    t = transitions[0]
    # Uber's fare is dynamic, so an unknown cost must not be fabricated.
    assert t.cost_known is False
    assert t.cost is None


def test_candidate_mobility_scoring(
    mobility_planning_service: MobilityPlanningService,
) -> None:
    # 1. Nearby candidate (<1.5km walking)
    score_walk, reason_walk = mobility_planning_service.evaluate_candidate_mobility_score(
        origin_location="Cape Town CBD",
        candidate_location="Bree Street, Cape Town CBD",
        available_time_minutes=30,
    )
    assert score_walk > 0
    assert reason_walk.type == ReasonType.MOBILITY
    assert reason_walk.outcome == ReasonOutcome.SUPPORTED
    assert "walking distance" in reason_walk.message.lower()

    # 2. Distant candidate violating tight time window
    score_far, reason_far = mobility_planning_service.evaluate_candidate_mobility_score(
        origin_location="Cape Town CBD",
        candidate_location="Simon's Town",
        available_time_minutes=15,
    )
    assert score_far < 0
    assert reason_far.outcome == ReasonOutcome.VIOLATED


@pytest.mark.asyncio
async def test_adaptation_service_mobility_disruptions(
    mock_planning_service, mock_decision_service, mock_info_service
) -> None:
    service = PlanAdaptationService(mock_planning_service, mock_decision_service, mock_info_service)
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    plan_id = uuid4()
    user_id = uuid4()
    item = PlanItem(
        plan_id=plan_id,
        name="Lunch",
        item_type=PlanItemType.FOOD,
        location="Camps Bay",
        start_time=now,
        end_time=now + timedelta(hours=1),
        position=0,
    )
    plan = Plan(
        id=plan_id,
        user_id=user_id,
        intention="Day out",
        status=PlanStatus.DRAFT,
        items=[item],
        context=PlanningContext(plan_id=plan_id, start_time=now),
    )
    mock_planning_service.get_plan.return_value = plan
    mock_decision_service.recommend.return_value = DecisionResult(
        candidates=(), source="fixture", is_live=False, attribution=None, freshness="fixture"
    )

    # Detect mobility disruption
    adaptation = await service.propose_adaptation(
        plan.user_id, plan.id, "Uber is too expensive and traffic is gridlocked"
    )
    assert ChangeType.MOBILITY_DISRUPTION.value in adaptation.changes_detected
    assert "disruption" in adaptation.narrative_summary.lower()

    # Detect mobility preference change
    adaptation_pref = await service.propose_adaptation(
        plan.user_id, plan.id, "I want to walk instead, no car today"
    )
    assert ChangeType.MOBILITY_PREFERENCE_CHANGED.value in adaptation_pref.changes_detected
    assert "transport preference" in adaptation_pref.narrative_summary.lower()
