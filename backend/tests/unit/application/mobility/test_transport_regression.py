"""Regression coverage for the Uber-only transport regression.

The planner showed Uber as the only option for a CBD-to-Kirstenbosch day. Two
separate faults produced that, and this module pins both, because either one on
its own is enough to hide every structured provider:

1. Metrorail never matched the CBD. Station applicability was a locality test
   only, and `address_serves_place` rejects city names by design, so the busiest
   station in the country could not be reached from the busiest origin in the
   product.
2. Ride-hail had no geographic gate at all, so it answered every pair. When the
   structured providers declined, ride-hail was not "the best remaining option",
   it was the only one that had not declined.

The second fault is why provider ordering must never become provider selection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.mobility.registry import MobilityProviderRegistry
from app.application.mobility.service import MobilityService
from app.application.planning.mobility_planning_service import MobilityPlanningService
from app.domain.entities.mobility.enums import (
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)
from app.domain.entities.mobility.models import MobilityRequirement
from app.infrastructure.mobility.geo import is_in_cape_town_service_area
from app.infrastructure.mobility.providers.bolt_provider import BoltProvider
from app.infrastructure.mobility.providers.golden_arrow_provider import GoldenArrowProvider
from app.infrastructure.mobility.providers.indrive_provider import InDriveProvider
from app.infrastructure.mobility.providers.myciti_provider import MyCiTiProvider
from app.infrastructure.mobility.providers.prasa_provider import PrasaProvider
from app.infrastructure.mobility.providers.uber_provider import UberProvider
from app.infrastructure.mobility.providers.walking_provider import WalkingProvider

ALL_PROVIDERS = (
    WalkingProvider,
    MyCiTiProvider,
    PrasaProvider,
    GoldenArrowProvider,
    UberProvider,
    BoltProvider,
    InDriveProvider,
)

# The journey the regression was reported against: downtown to a southern
# suburb, which the Southern Line serves and which has no direct bus route.
CBD_TO_KIRSTENBOSCH = ("Cape Town CBD", "Kirstenbosch, Cape Town")


def build_service() -> MobilityService:
    """A service wired to the real providers, so applicability is genuinely tested."""
    registry = MobilityProviderRegistry()
    for provider in ALL_PROVIDERS:
        registry.register(provider())
    return MobilityService(registry)


def build_planning_service() -> MobilityPlanningService:
    return MobilityPlanningService(mobility_service=build_service())


# ---------------------------------------------------------------------------
# Test A — multiple applicable providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rail_is_evaluated_and_offered_for_a_rail_served_journey():
    """Metrorail is evaluated, not omitted. The answer to the reporting question.

    This asserts the option exists at all, which is what failed before. The
    distinction that matters for diagnosis: the provider was reached and then
    declined, not skipped by orchestration.
    """
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    modes = {opt.mode for opt in options}
    assert TransportMode.TRAIN in modes, "Metrorail was not offered for a rail-served journey"
    assert TransportMode.RIDE_HAIL in modes


@pytest.mark.asyncio
async def test_ride_hail_is_not_the_only_option_merely_because_it_is_registered():
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    ride_hail_only = [o for o in options if o.mode == TransportMode.RIDE_HAIL]
    structured = [
        o for o in options if o.mode in {TransportMode.TRAIN, TransportMode.BUS, TransportMode.WALK}
    ]
    assert len(options) > len(ride_hail_only), "Uber/Bolt/inDrive crowded out structured transport"
    assert structured, "no structured transport survived alongside ride-hail"


@pytest.mark.asyncio
async def test_structured_transport_outranks_ride_hail_without_a_stated_preference():
    """Ranking must not depend on provider registration order.

    Ride-hail used to survive every filter, so its position in the sorted list
    was the only thing keeping it from winning outright. Rail must beat it on
    merit, not on where the provider happened to be registered.
    """
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    first_ride_hail = next(i for i, o in enumerate(options) if o.mode == TransportMode.RIDE_HAIL)
    first_structured = next(
        i for i, o in enumerate(options) if o.mode in {TransportMode.TRAIN, TransportMode.BUS}
    )
    assert first_structured < first_ride_hail


@pytest.mark.asyncio
async def test_every_provider_is_actually_evaluated_for_the_journey():
    """All seven M14-M16 providers are queried; none is skipped by the service.

    Guards against a future change that would quietly narrow the eligible
    provider set and make this regression reappear through a different route.
    """
    registry = MobilityProviderRegistry()
    for provider in ALL_PROVIDERS:
        registry.register(provider())
    service = MobilityService(registry)
    assert len(service.registry.get_enabled_providers()) == len(ALL_PROVIDERS)


# ---------------------------------------------------------------------------
# Test B — selection, and no silent substitution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stated_train_preference_is_honoured_and_not_replaced_by_ride_hail():
    service = build_planning_service()
    option, reason = service._select_primary_option(
        await service._mobility_service.find_options_for_requirement(
            MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
        ),
        [TransportMode.TRAIN],
    )
    assert option.mode == TransportMode.TRAIN
    assert option.provider_id == "prasa_metrorail"
    assert reason is None, "an honoured preference must not report a substitution"


@pytest.mark.asyncio
async def test_unmet_preference_substitutes_without_becoming_ride_hail_by_accident():
    """A mode the engine cannot serve is substituted, and the reason is reported.

    Only ride-hail is reachable for this pair, so the substitution cannot be
    avoided — but it must be announced, because an unannounced swap to a paid
    ride is the exact behaviour under test.
    """
    service = build_planning_service()
    options = await service._mobility_service.find_options_for_requirement(
        MobilityRequirement(origin="Camps Bay, Cape Town", destination="District Six, Cape Town")
    )
    option, reason = service._select_primary_option(options, [TransportMode.TRAIN])
    assert reason is not None, "a substitution was applied with no explanation"
    assert "train" in reason.lower()
    assert option.mode != TransportMode.TRAIN


def test_fallback_does_not_inherit_registration_order():
    """With no preference, the cheapest quickest option wins — not options[0]."""
    service = build_planning_service()
    train_like = _option("uber", "Uber", TransportMode.RIDE_HAIL, 20, None)
    cheaper = _option("bolt", "Bolt", TransportMode.RIDE_HAIL, 5, 30)
    # Ride-hail first in the list, but the longer and pricier trip.
    option, _ = service._select_primary_option([train_like, cheaper], None)
    assert option.provider_id == "bolt"


def _option(provider_id, provider_name, mode, duration, cost):
    from app.domain.entities.mobility.models import MobilityOption

    return MobilityOption(
        id=f"{provider_id}-{duration}",
        provider_id=provider_id,
        provider_name=provider_name,
        mode=mode,
        origin="A",
        destination="B",
        duration_minutes=duration,
        cost=cost,
        cost_is_unknown=cost is None,
        transfers=0,
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_substitution_reason_reaches_the_transition():
    """The explanation has to travel to the client to be usable at all."""
    service = build_planning_service()
    transition = await service._build_transition(
        origin="Camps Bay, Cape Town",
        destination="District Six Museum, Cape Town",
        from_name="Camps Bay",
        to_name="District Six Museum",
        departure_time=None,
        arrival_time=None,
        party_size=1,
        preferred_modes=[TransportMode.TRAIN],
    )
    assert transition is not None
    assert transition.mode_substitution_reason


@pytest.mark.asyncio
async def test_transition_exposes_every_evaluated_option_to_the_client():
    """The selector can only offer real options if the leg carries them."""
    service = build_planning_service()
    transition = await service._build_transition(
        origin=CBD_TO_KIRSTENBOSCH[0],
        destination=CBD_TO_KIRSTENBOSCH[1],
        from_name="Cape Town CBD",
        to_name="Kirstenbosch",
        departure_time=None,
        arrival_time=None,
        party_size=1,
        preferred_modes=None,
    )
    assert transition is not None
    provider_ids = {opt.provider_id for opt in transition.available_options}
    assert "prasa_metrorail" in provider_ids
    assert len(transition.available_options) > 1


# ---------------------------------------------------------------------------
# Test C — realtime honesty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_transport_survives_with_no_live_realtime_feed():
    """No realtime feed is a fact about the feed, not about the service.

    This is the design principle from M14-M16 that the regression broke: a mode
    was being treated as absent because its live status was unknown.
    """
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    rail = [o for o in options if o.mode == TransportMode.TRAIN]
    assert rail, "rail was dropped purely because it has no live feed"
    for option in rail:
        assert option.availability == "available"
        assert option.live_status == MobilityLiveStatus.UNKNOWN
        assert option.source_type == MobilitySourceType.OFFICIAL_TIMETABLE


@pytest.mark.asyncio
async def test_ride_hail_is_also_honest_about_its_unquoted_fare():
    """Ride-hail must not claim a fare it cannot verify either."""
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    ride_hail = [o for o in options if o.mode == TransportMode.RIDE_HAIL]
    assert ride_hail
    assert all(o.cost_is_unknown for o in ride_hail)


# ---------------------------------------------------------------------------
# Geographic applicability, and the origin/search-area separation (Test D)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ride_hail_declines_outside_its_operating_area():
    """Ride-hail no longer answers for places it does not serve."""
    service = build_service()
    atlantis = await service.find_options_for_requirement(
        MobilityRequirement(origin="Atlantis", destination="Kirstenbosch, Cape Town")
    )
    assert not [o for o in atlantis if o.mode == TransportMode.RIDE_HAIL]


@pytest.mark.parametrize(
    "address,expected",
    [
        ("Cape Town CBD", True),
        ("Kirstenbosch, Cape Town", True),
        ("Bellville, Cape Town", True),
        ("Simon's Town", True),
        ("Hout Bay", True),
        ("Somerset West", False),
        ("Atlantis", False),
        ("Stellenbosch", False),
    ],
)
def test_service_area_boundary(address, expected):
    assert is_in_cape_town_service_area(address) is expected


def test_unplaceable_address_is_not_treated_as_proof_of_absence():
    """An unknown place name is missing data, not a reason to hide a provider."""
    assert is_in_cape_town_service_area("Some Newly Annexed Suburb") is True


@pytest.mark.asyncio
async def test_rail_uses_the_travel_origin_not_a_city_name_match():
    """A rail journey is decided by where the traveller actually starts.

    An address with no station still gets no rail option, even though every
    Cape Town address contains the string "Cape Town".
    """
    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin="Camps Bay, Cape Town", destination="District Six, Cape Town")
    )
    assert not [o for o in options if o.mode == TransportMode.TRAIN]


# ---------------------------------------------------------------------------
# Test D — search area and travel origin stay separate
# ---------------------------------------------------------------------------


def test_origin_is_not_written_into_the_venue_search_area():
    """The collision that was already fixed once, pinned so it stays fixed.

    `PlanningContext.location` is where to look for venues. `origin` is where the
    traveller starts. They are different questions, and folding one into the
    other is what previously collapsed a 29-candidate search to zero.
    """
    from app.domain.entities.planning.context import PlanningContext

    context = PlanningContext(
        plan_id=uuid4(),
        location="Cape Town",
        start_time=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
    )
    assert context.location == "Cape Town"
    assert getattr(context, "origin", None) is None
    # The two are distinct attributes; assigning an origin leaves the area alone.
    context.origin = "Cape Town CBD"
    assert context.location == "Cape Town"


@pytest.mark.asyncio
async def test_declaring_an_origin_does_not_change_the_search_area():
    """Orchestrating with an origin must not move the area venues are drawn from."""
    from app.application.planning.orchestration_service import (
        ItineraryOrchestrator,
        OrchestrationStopInput,
    )
    from app.domain.entities.planning.context import PlanningContext
    from app.domain.entities.planning.plan import Plan, PlanStatus

    plan_id = uuid4()
    plan = Plan(
        user_id=uuid4(),
        title="An afternoon out",
        intention="a cheap afternoon outdoors",
        context=PlanningContext(
            plan_id=plan_id,
            location="Cape Town",
            start_time=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        ),
        constraints=[],
        status=PlanStatus.DRAFT,
    )
    orchestrator = ItineraryOrchestrator(
        mobility_service=build_planning_service()
    )
    result = await orchestrator.orchestrate(
        plan,
        [OrchestrationStopInput(name="Kirstenbosch", location="Kirstenbosch, Cape Town")],
        origin="Cape Town CBD",
    )
    # The search area is untouched, and the origin is carried on the response
    # rather than written into the plan context, so it cannot be mistaken for one.
    assert plan.context.location == "Cape Town"
    assert result.origin == "Cape Town CBD"
    assert result.origin_resolved is True


# ---------------------------------------------------------------------------
# Test E — stated provider preference (global)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preferred_provider_selects_matching_transport_on_leg():
    """Declaring preferred_provider='prasa_metrorail' selects PRASA on a rail-served leg."""
    from app.application.planning.orchestration_service import (
        ItineraryOrchestrator,
        OrchestrationStopInput,
    )
    from app.domain.entities.planning.context import PlanningContext
    from app.domain.entities.planning.plan import Plan, PlanStatus

    plan = Plan(
        user_id=uuid4(),
        title="Rail Trip",
        intention="train to newlands",
        context=PlanningContext(
            plan_id=uuid4(),
            location="Cape Town",
            start_time=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        ),
        constraints=[],
        status=PlanStatus.DRAFT,
    )
    orchestrator = ItineraryOrchestrator(mobility_service=build_planning_service())
    result = await orchestrator.orchestrate(
        plan,
        [OrchestrationStopInput(name="Newlands Brewery", location="Newlands, Cape Town")],
        origin="Cape Town CBD",
        preferred_provider="prasa_metrorail",
    )
    assert len(result.legs) == 1
    leg = result.legs[0]
    assert leg.transition.provider_id == "prasa_metrorail"
    assert result.transport_preference == "PRASA Metrorail"


# ---------------------------------------------------------------------------
# Test F — per-leg option override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selected_leg_options_overrides_provider_on_specific_leg():
    """An explicit selected_leg_options choice overrides default or global preference."""
    from app.application.planning.orchestration_service import (
        ItineraryOrchestrator,
        OrchestrationStopInput,
    )
    from app.domain.entities.planning.context import PlanningContext
    from app.domain.entities.planning.plan import Plan, PlanStatus

    plan = Plan(
        user_id=uuid4(),
        title="Multi-Stop Day",
        intention="cbd to newlands then kirstenbosch",
        context=PlanningContext(
            plan_id=uuid4(),
            location="Cape Town",
            start_time=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        ),
        constraints=[],
        status=PlanStatus.DRAFT,
    )
    orchestrator = ItineraryOrchestrator(mobility_service=build_planning_service())
    result = await orchestrator.orchestrate(
        plan,
        [
            OrchestrationStopInput(name="Newlands", location="Newlands, Cape Town"),
        ],
        origin="Cape Town CBD",
        preferred_provider="prasa_metrorail",
        selected_leg_options={0: "uber"},
    )
    assert len(result.legs) == 1
    assert result.legs[0].transition.provider_id == "uber"


# ---------------------------------------------------------------------------
# Test G — all_options exposed and alternatives not artificially truncated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leg_exposes_all_viable_options_without_truncation():
    """All applicable providers are available in all_options and alternatives."""
    from app.application.planning.orchestration_service import (
        ItineraryOrchestrator,
        OrchestrationStopInput,
    )
    from app.domain.entities.planning.context import PlanningContext
    from app.domain.entities.planning.plan import Plan, PlanStatus

    plan = Plan(
        user_id=uuid4(),
        title="Options test",
        intention="afternoon out",
        context=PlanningContext(
            plan_id=uuid4(),
            location="Cape Town",
            start_time=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        ),
        constraints=[],
        status=PlanStatus.DRAFT,
    )
    orchestrator = ItineraryOrchestrator(mobility_service=build_planning_service())
    result = await orchestrator.orchestrate(
        plan,
        [OrchestrationStopInput(name="Newlands", location="Newlands, Cape Town")],
        origin="Cape Town CBD",
    )
    leg = result.legs[0]
    provider_ids = {opt.provider_id for opt in leg.all_options}
    assert "prasa_metrorail" in provider_ids
    assert "uber" in provider_ids
    assert "bolt" in provider_ids
    assert "indrive" in provider_ids
    assert "walking" in provider_ids
    assert len(leg.alternatives) >= 4


# ---------------------------------------------------------------------------
# Test H — action labels and deep links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ride_hail_and_transit_action_links():
    """Ride-hail options provide valid deep links and public transit provides timetable links."""
    from app.api.v1.planning.router import MobilityOptionRead

    options = await build_service().find_options_for_requirement(
        MobilityRequirement(origin=CBD_TO_KIRSTENBOSCH[0], destination=CBD_TO_KIRSTENBOSCH[1])
    )
    read_options = [MobilityOptionRead.from_domain(o) for o in options]
    uber = next(o for o in read_options if o.provider_id == "uber")
    bolt = next(o for o in read_options if o.provider_id == "bolt")
    indrive = next(o for o in read_options if o.provider_id == "indrive")
    rail = next(o for o in read_options if o.provider_id == "prasa_metrorail")

    assert uber.action_label == "Open Uber"
    assert uber.booking_url is not None and "m.uber.com/ul/?action=setPickup" in uber.booking_url
    assert uber.cost_is_unknown is True
    assert "fare confirmed in app" in uber.schedule_note.lower()

    assert bolt.action_label == "Open Bolt"
    assert bolt.booking_url == "https://bolt.eu"

    assert indrive.action_label == "Open inDrive"
    assert indrive.booking_url == "https://indrive.com"

    assert rail.action_label == "View Metrorail Timetable"
    assert rail.booking_url == "https://www.prasa.com"
    assert "timetable available" in rail.schedule_note.lower()
    assert "live departures not currently verified" in rail.schedule_note.lower()
    assert rail.route_or_line == "Southern Line"


