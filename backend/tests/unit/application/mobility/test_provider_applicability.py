"""Geographic applicability of network-bound mobility providers.

A provider must not claim a route merely because it is registered. These tests
pin the case that motivated the fix: every Cape Town address contains the string
"Cape Town", so matching the "Cape Town" station against a raw address made rail
look available from places with no station at all.
"""

import pytest

from app.domain.entities.mobility.enums import (
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)
from app.domain.entities.mobility.models import MobilityRequirement
from app.infrastructure.mobility.geo import address_serves_place, resolve_locality
from app.infrastructure.mobility.providers.myciti_provider import MyCiTiProvider
from app.infrastructure.mobility.providers.prasa_provider import PrasaProvider


@pytest.mark.asyncio
async def test_prasa_is_not_offered_where_there_is_no_rail_access():
    provider = PrasaProvider()

    camps_bay = await provider.get_options(
        MobilityRequirement(
            origin="Camps Bay, Cape Town", destination="District Six Museum, Cape Town"
        )
    )
    assert camps_bay == []

    named_venue = await provider.get_options(
        MobilityRequirement(
            origin="Grand Pavilion, Camps Bay, Cape Town",
            destination="District Six Museum, Cape Town",
        )
    )
    assert named_venue == []


@pytest.mark.asyncio
async def test_prasa_needs_both_ends_on_the_network():
    provider = PrasaProvider()

    one_end_off_network = await provider.get_options(
        MobilityRequirement(origin="Observatory, Cape Town", destination="Camps Bay, Cape Town")
    )
    assert one_end_off_network == []


@pytest.mark.asyncio
async def test_prasa_is_offered_when_both_ends_are_rail_served():
    provider = PrasaProvider()
    options = await provider.get_options(
        MobilityRequirement(
            origin="Observatory, Cape Town", destination="Cape Town Station, Cape Town"
        )
    )
    assert options
    assert {o.provider_id for o in options} == {"prasa_metrorail"}
    assert all(o.mode == TransportMode.TRAIN for o in options)
    # The fare is a published zonal rate, not a live quote.
    assert all(o.cost_is_estimated is True for o in options)


@pytest.mark.asyncio
async def test_prasa_cbd_hub_is_reachable_geographically_not_just_by_name():
    """The CBD hub is reachable now that matching can use position.

    "Cape Town" is a city name, so the locality test can never match it by
    design — it is there to stop rail claiming a route for every address in the
    country. That left the busiest origin in the product unable to reach the
    busiest station, and rail silently dropped out of planning for anyone
    starting downtown. The proximity test is what restores it.
    """
    provider = PrasaProvider()
    options = await provider.get_options(
        MobilityRequirement(
            origin="Cape Town CBD", destination="Kirstenbosch, Cape Town"
        )
    )
    assert [o.provider_id for o in options] == ["prasa_metrorail"]
    assert options[0].mode == TransportMode.TRAIN


@pytest.mark.asyncio
async def test_prasa_route_survives_when_only_live_status_is_unknown():
    """Absence of realtime data must not remove a scheduled mode.

    Metrorail publishes no public live-status feed. That is a fact about the
    feed, not about whether the train runs, so the option stays available on the
    strength of the official timetable while its live status stays unknown.
    """
    provider = PrasaProvider()
    options = await provider.get_options(
        MobilityRequirement(
            origin="Cape Town CBD", destination="Kirstenbosch, Cape Town"
        )
    )
    assert len(options) == 1
    option = options[0]
    assert option.availability == "available"
    assert option.live_status == MobilityLiveStatus.UNKNOWN
    assert option.source_type == MobilitySourceType.OFFICIAL_TIMETABLE
    assert provider.capability.has_realtime is False


@pytest.mark.asyncio
async def test_myciti_is_not_offered_where_no_stop_serves_either_end():
    provider = MyCiTiProvider()
    options = await provider.get_options(
        MobilityRequirement(
            origin="Observatory, Cape Town", destination="Kirstenbosch, Cape Town"
        )
    )
    assert options == []


@pytest.mark.asyncio
async def test_myciti_is_offered_for_a_route_that_serves_both_ends():
    provider = MyCiTiProvider()
    options = await provider.get_options(
        MobilityRequirement(origin="Camps Bay, Cape Town", destination="Sea Point, Cape Town")
    )
    assert options
    assert {o.provider_id for o in options} == {"myciti"}
    assert all(o.mode == TransportMode.BUS for o in options)


def test_address_serves_place_uses_the_specific_locality():
    # The city suffix must not satisfy a city-level station or hub name.
    assert address_serves_place("Observatory, Cape Town", "observatory") is True
    assert address_serves_place("Observatory, Cape Town", "cape town") is False
    assert address_serves_place("Camps Bay, Cape Town", "sea point") is False
    # A leading venue name is not the locality either.
    assert address_serves_place("Cape Town Jazz Club, 1 Loop St, Foreshore", "civic centre") is False
    assert address_serves_place("Sea Point Promenade, Beach Road, Sea Point", "sea point") is True


def test_resolve_locality_drops_city_and_venue_components():
    assert resolve_locality("270 Victoria Rd, Camps Bay, Cape Town") == "camps bay"
    assert resolve_locality("Observatory, Cape Town") == "observatory"
    assert resolve_locality("Cape Town Jazz Club, 1 Loop St, Foreshore, Cape Town") == "foreshore"
