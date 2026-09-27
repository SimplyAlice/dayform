from __future__ import annotations

from datetime import date as dt_date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_live_mobility_service, get_mobility_service
from app.application.mobility.dtos import MobilityRequirementDTO
from app.application.mobility.live_service import LiveMobilityService
from app.application.mobility.service import MobilityService
from app.domain.entities.mobility.enums import (
    BookingCapability,
    MobilityLiveAvailability,
    MobilityLiveStatus,
    MobilitySourceType,
    TransportMode,
)

router = APIRouter(prefix="/mobility", tags=["mobility"])


class CoordinatesModel(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class MobilityRequirementRequest(BaseModel):
    origin: str = Field(..., min_length=1, max_length=255, description="Journey start location or landmark")
    destination: str = Field(..., min_length=1, max_length=255, description="Journey end location or landmark")
    departure_time: datetime | None = Field(default=None, description="Requested departure time in ISO-8601")
    arrival_time: datetime | None = Field(default=None, description="Requested arrival deadline in ISO-8601")
    date: dt_date | None = Field(default=None, description="Date of travel if time not specified")
    party_size: int = Field(default=1, ge=1, le=50, description="Number of travelers")
    preferred_modes: list[TransportMode] = Field(default_factory=list, description="Transport modes to prioritize")
    excluded_modes: list[TransportMode] = Field(default_factory=list, description="Transport modes to exclude")
    max_walking_minutes: int | None = Field(default=None, ge=0, le=300, description="Max acceptable walking time")
    origin_coordinates: CoordinatesModel | None = None
    destination_coordinates: CoordinatesModel | None = None


class MobilityEvidenceResponse(BaseModel):
    claim: str
    source: str
    source_type: MobilitySourceType
    observed_at: datetime
    retrieved_at: datetime
    expires_at: datetime | None
    confidence: float
    relevant_provider: str
    relevant_route_or_stop: str | None


class MobilityOptionResponse(BaseModel):
    id: str
    provider_id: str
    provider_name: str
    mode: TransportMode
    origin: str
    destination: str
    departure_time: datetime | None
    arrival_time: datetime | None
    duration_minutes: int | None
    cost: Decimal | None = None
    cost_is_unknown: bool
    currency: str
    walking_duration_minutes: int | None
    transfers: int
    availability: str
    live_status: MobilityLiveStatus
    booking_capability: BookingCapability
    booking_url: str | None
    source: str
    source_type: MobilitySourceType
    retrieved_at: datetime
    confidence: float
    summary: str
    evidence: list[MobilityEvidenceResponse] = Field(default_factory=list)


class MobilityOptionsResponse(BaseModel):
    options: list[MobilityOptionResponse]
    retrieved_at: datetime
    total_options: int
    query_summary: str


class ProviderCapabilityResponse(BaseModel):
    provider_id: str
    name: str
    supported_modes: list[TransportMode]
    has_route_data: bool
    has_timetable: bool
    has_realtime: bool
    has_service_alerts: bool
    has_fare_estimates: bool
    booking_capability: BookingCapability
    api_available: bool
    auth_required: bool
    official_source_url: str | None
    is_enabled: bool
    notes: str


@router.post(
    "/options",
    response_model=MobilityOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Discover transport options between two locations",
)
async def get_mobility_options(
    request: MobilityRequirementRequest,
    service: Annotated[MobilityService, Depends(get_mobility_service)],
) -> MobilityOptionsResponse:
    """Evaluate transport possibilities across all active providers for a journey."""
    try:
        dto = MobilityRequirementDTO(
            origin=request.origin,
            destination=request.destination,
            departure_time=request.departure_time,
            arrival_time=request.arrival_time,
            date=request.date,
            party_size=request.party_size,
            preferred_modes=request.preferred_modes,
            excluded_modes=request.excluded_modes,
            max_walking_minutes=request.max_walking_minutes,
            origin_coordinates=(
                (request.origin_coordinates.latitude, request.origin_coordinates.longitude)
                if request.origin_coordinates
                else None
            ),
            destination_coordinates=(
                (request.destination_coordinates.latitude, request.destination_coordinates.longitude)
                if request.destination_coordinates
                else None
            ),
        )
        domain_response = await service.get_options(dto)
        return MobilityOptionsResponse(
            options=[
                MobilityOptionResponse(
                    id=opt.id,
                    provider_id=opt.provider_id,
                    provider_name=opt.provider_name,
                    mode=opt.mode,
                    origin=opt.origin,
                    destination=opt.destination,
                    departure_time=opt.departure_time,
                    arrival_time=opt.arrival_time,
                    duration_minutes=opt.duration_minutes,
                    cost=opt.cost,
                    cost_is_unknown=opt.cost_is_unknown,
                    currency=opt.currency,
                    walking_duration_minutes=opt.walking_duration_minutes,
                    transfers=opt.transfers,
                    availability=opt.availability,
                    live_status=opt.live_status,
                    booking_capability=opt.booking_capability,
                    booking_url=opt.booking_url,
                    source=opt.source,
                    source_type=opt.source_type,
                    retrieved_at=opt.retrieved_at,
                    confidence=opt.confidence,
                    summary=opt.summary,
                    evidence=[
                        MobilityEvidenceResponse(
                            claim=e.claim,
                            source=e.source,
                            source_type=e.source_type,
                            observed_at=e.observed_at,
                            retrieved_at=e.retrieved_at,
                            expires_at=e.expires_at,
                            confidence=e.confidence,
                            relevant_provider=e.relevant_provider,
                            relevant_route_or_stop=e.relevant_route_or_stop,
                        )
                        for e in opt.evidence
                    ],
                )
                for opt in domain_response.options
            ],
            retrieved_at=domain_response.retrieved_at,
            total_options=domain_response.total_options,
            query_summary=domain_response.query_summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get(
    "/providers",
    response_model=list[ProviderCapabilityResponse],
    status_code=status.HTTP_200_OK,
    summary="List registered mobility providers and their declared capabilities",
)
def get_mobility_providers(
    service: Annotated[MobilityService, Depends(get_mobility_service)],
) -> list[ProviderCapabilityResponse]:
    """Inspect active transport integrations and their truth-backed capability declarations."""
    caps = service.get_capabilities()
    return [
        ProviderCapabilityResponse(
            provider_id=c.provider_id,
            name=c.name,
            supported_modes=c.supported_modes,
            has_route_data=c.has_route_data,
            has_timetable=c.has_timetable,
            has_realtime=c.has_realtime,
            has_service_alerts=c.has_service_alerts,
            has_fare_estimates=c.has_fare_estimates,
            booking_capability=c.booking_capability,
            api_available=c.api_available,
            auth_required=c.auth_required,
            official_source_url=c.official_source_url,
            is_enabled=c.is_enabled,
            notes=c.notes,
        )
        for c in caps
    ]


class MobilityLiveStatusResponse(BaseModel):
    provider_id: str
    provider_name: str
    status: MobilityLiveStatus
    availability: MobilityLiveAvailability
    explanation: str
    source: str
    source_type: MobilitySourceType
    observed_at: datetime | None
    retrieved_at: datetime
    confidence: float
    delay_minutes: int | None
    expected_departure: datetime | None
    expected_arrival: datetime | None
    is_stale: bool
    is_blocking: bool
    freshness_minutes: int | None


@router.get(
    "/live-status",
    response_model=MobilityLiveStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Current live service status for a mobility provider",
)
async def get_mobility_live_status(
    provider_id: str,
    live_service: Annotated[LiveMobilityService, Depends(get_live_mobility_service)],
    origin: str | None = None,
    destination: str | None = None,
) -> MobilityLiveStatusResponse:
    """Report what is genuinely known about a provider's live service state.

    Providers without a reachable public feed return availability=unavailable with
    status=unknown. This endpoint never fabricates a status, delay or ETA.
    """
    report = await live_service.get_live_status(
        provider_id=provider_id, origin=origin, destination=destination
    )
    return MobilityLiveStatusResponse(
        provider_id=report.provider_id,
        provider_name=report.provider_name,
        status=report.effective_status(),
        availability=report.availability,
        explanation=report.explanation,
        source=report.source,
        source_type=report.source_type,
        observed_at=report.observed_at,
        retrieved_at=report.retrieved_at,
        confidence=report.confidence,
        delay_minutes=report.delay_minutes,
        expected_departure=report.expected_departure,
        expected_arrival=report.expected_arrival,
        is_stale=report.is_stale,
        is_blocking=report.is_blocking,
        freshness_minutes=report.freshness_minutes,
    )
