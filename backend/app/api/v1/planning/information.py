from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_planning_decision_service, get_planning_information_service
from app.api.v1.auth import get_current_user
from app.application.planning.decision_service import PlanningDecisionService
from app.application.planning.information import OptionSearchCriteria, PlanningInformationService
from app.domain.entities.planning.decision import (
    CandidateType,
    DecisionCandidate,
    DecisionCriteria,
    DecisionReason,
    ReasonOutcome,
    ReasonType,
)
from app.domain.entities.planning.information import Activity, InformationCategory, InformationSource, Place
from app.infrastructure.db.models import User

router = APIRouter(prefix="/options", tags=["planning information"])


class PlaceRead(BaseModel):
    id: UUID
    name: str
    location: str
    category: InformationCategory
    description: str
    price_from: Decimal | None
    opening_hours: str | None
    minimum_group_size: int
    maximum_group_size: int | None
    source: str
    address: str | None = None
    operating_status: str | None = None
    freshness: str = "fixture"
    verified_at: str | None = None
    source_url: str | None = None

    @classmethod
    def from_entity(cls, place: Place) -> PlaceRead:
        return cls(**place.__dict__)


class ActivityRead(BaseModel):
    id: UUID
    place_id: UUID | None
    name: str
    location: str | None
    category: InformationCategory
    description: str
    cost: Decimal | None = None
    duration_minutes: int
    minimum_group_size: int
    maximum_group_size: int | None
    metadata: dict[str, str]
    source: str
    address: str | None = None
    freshness: str = "fixture"
    verified_at: str | None = None
    source_url: str | None = None

    @classmethod
    def from_entity(cls, activity: Activity) -> ActivityRead:
        return cls(**activity.__dict__)


class SearchResponse(BaseModel):
    """Provider-neutral envelope carrying data-source provenance and attribution."""

    data_source: str
    is_live: bool
    attribution: str | None = None
    freshness: str = "fixture"


class PlaceSearchResponse(SearchResponse):
    items: list[PlaceRead]


class ActivitySearchResponse(SearchResponse):
    items: list[ActivityRead]


class DecisionReasonRead(BaseModel):
    type: ReasonType
    outcome: ReasonOutcome
    message: str

    @classmethod
    def from_reason(cls, reason: DecisionReason) -> DecisionReasonRead:
        return cls(type=reason.type, outcome=reason.outcome, message=reason.message)


class DecisionCandidateRead(BaseModel):
    option_id: UUID
    option_type: CandidateType
    name: str
    is_eligible: bool
    score: int
    reasons: list[DecisionReasonRead]
    category: InformationCategory
    cost: Decimal | None
    duration_minutes: int | None
    location: str | None
    source: str
    address: str | None = None
    opening_hours: str | None = None
    phone: str | None = None
    source_url: str | None = None
    reservation_url: str | None = None
    freshness: str | None = None
    verified_at: str | None = None
    attribution: str | None = None
    # The provider's own description, so the UI and coverage can show *why* a
    # venue was matched to what the user asked for.
    description: str | None = None

    @classmethod
    def from_candidate(cls, candidate: DecisionCandidate) -> DecisionCandidateRead:
        return cls(
            option_id=candidate.option_id,
            option_type=candidate.option_type,
            name=candidate.name,
            is_eligible=candidate.is_eligible,
            score=candidate.score,
            reasons=[DecisionReasonRead.from_reason(reason) for reason in candidate.reasons],
            category=candidate.category,
            cost=candidate.cost,
            duration_minutes=candidate.duration_minutes,
            location=candidate.location,
            source=candidate.source,
            address=candidate.address,
            opening_hours=candidate.opening_hours,
            phone=candidate.phone,
            source_url=candidate.source_url,
            reservation_url=candidate.reservation_url,
      freshness=candidate.freshness,
        verified_at=candidate.verified_at,
        attribution=candidate.attribution,
        description=candidate.description,
      )


class RecommendationResponse(SearchResponse):
    candidates: list[DecisionCandidateRead]
    trade_off_summary: str | None = None


def _envelope(source: InformationSource) -> dict[str, object]:
    return {
        "data_source": source.data_source,
        "is_live": source.is_live,
        "attribution": source.attribution,
        "freshness": source.freshness,
    }


def _criteria(
    location: str | None,
    category: InformationCategory | None,
    maximum_cost: Decimal | None,
    group_size: int | None,
    maximum_duration_minutes: int | None,
) -> OptionSearchCriteria:
    return OptionSearchCriteria(location=location, category=category, maximum_cost=maximum_cost,
                                group_size=group_size, maximum_duration_minutes=maximum_duration_minutes)


@router.get("/places", response_model=PlaceSearchResponse)
async def search_places(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
    location: Annotated[str | None, Query(max_length=255)] = None,
    category: InformationCategory | None = None,
    maximum_cost: Annotated[Decimal | None, Query(ge=0)] = None,
    group_size: Annotated[int | None, Query(ge=1)] = None,
) -> PlaceSearchResponse:
    del current_user
    results = await service.search_places(_criteria(location, category, maximum_cost, group_size, None))
    return PlaceSearchResponse(
        **_envelope(service.source), items=[PlaceRead.from_entity(item) for item in results]
    )


@router.get("/activities", response_model=ActivitySearchResponse)
async def search_activities(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
    location: Annotated[str | None, Query(max_length=255)] = None,
    category: InformationCategory | None = None,
    maximum_cost: Annotated[Decimal | None, Query(ge=0)] = None,
    group_size: Annotated[int | None, Query(ge=1)] = None,
    maximum_duration_minutes: Annotated[int | None, Query(ge=1)] = None,
) -> ActivitySearchResponse:
    del current_user
    results = await service.search_activities(
        _criteria(location, category, maximum_cost, group_size, maximum_duration_minutes)
    )
    return ActivitySearchResponse(
        **_envelope(service.source), items=[ActivityRead.from_entity(item) for item in results]
    )


@router.get("/recommendations", response_model=RecommendationResponse)
async def recommend_options(
    current_user: Annotated[User, Depends(get_current_user)],
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
    decision: Annotated[PlanningDecisionService, Depends(get_planning_decision_service)],
    location: Annotated[str | None, Query(max_length=255)] = None,
    category: InformationCategory | None = None,
    maximum_cost: Annotated[Decimal | None, Query(ge=0)] = None,
    group_size: Annotated[int | None, Query(ge=1)] = None,
    maximum_duration_minutes: Annotated[int | None, Query(ge=1)] = None,
) -> RecommendationResponse:
    del current_user
    criteria = DecisionCriteria(location=location, category=category, maximum_cost=maximum_cost,
                                group_size=group_size, maximum_duration_minutes=maximum_duration_minutes)
    result = await decision.recommend(criteria)
    return RecommendationResponse(
        data_source=result.source,
        is_live=result.is_live,
        attribution=result.attribution,
        freshness=result.freshness,
        trade_off_summary=result.trade_off_summary,
        candidates=[DecisionCandidateRead.from_candidate(candidate) for candidate in result.candidates],
    )
