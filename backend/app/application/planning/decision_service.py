from __future__ import annotations

from app.application.planning.information import OptionSearchCriteria, PlanningInformationService
from app.domain.entities.planning.decision import DecisionCandidate, DecisionCriteria, DecisionResult
from app.domain.entities.planning.decision_engine import decide


class PlanningDecisionService:
    """Produces deterministic, explainable candidate decisions.

    Depends only on the application-level `PlanningInformationService`
    (itself backed by the `PlanningInformationProvider` port), never on a
    concrete provider. Nothing is persisted: the engine only evaluates and
    ranks options for the caller to choose from.
    """

    def __init__(self, information: PlanningInformationService) -> None:
        self._information = information

    async def recommend(self, criteria: DecisionCriteria) -> DecisionResult:
        search = _search_criteria(criteria)
        places = await self._information.search_places(search)
        activities = await self._information.search_activities(search)
        result = decide(criteria, places, activities)
        attr = self._information.source.attribution
        candidates = [
            DecisionCandidate(
                option_id=c.option_id,
                option_type=c.option_type,
                name=c.name,
                is_eligible=c.is_eligible,
                score=c.score,
                reasons=c.reasons,
                category=c.category,
                cost=c.cost,
                duration_minutes=c.duration_minutes,
                location=c.location,
                source=c.source,
                address=c.address,
                opening_hours=c.opening_hours,
                freshness=c.freshness,
                verified_at=c.verified_at,
                # Business contact and booking data must survive this rebuild,
                # otherwise a proposed stop cannot offer real actions.
                source_url=c.source_url,
                phone=c.phone,
                reservation_url=c.reservation_url,
                # Provider evidence must survive too, or intent coverage has
                # nothing real to check a requirement against.
                description=c.description,
                metadata=dict(c.metadata),
                # Coordinates must survive the rebuild so the area a candidate was
                # judged against can be shown and re-checked further downstream.
                latitude=c.latitude,
                longitude=c.longitude,
                attribution=c.attribution or attr,
            )
            for c in result.candidates
        ]
        return DecisionResult(
            candidates=tuple(candidates),
            source=self._information.source.data_source,
            is_live=self._information.source.is_live,
            attribution=attr,
            freshness=self._information.source.freshness,
            trade_off_summary=result.trade_off_summary,
        )


def _search_criteria(criteria: DecisionCriteria) -> OptionSearchCriteria:
    """Reuse the existing option-search concept for the provider query.

    Only location and category are pushed down to the provider as a narrow
    pre-filter. Budget, group size, and duration are deliberately *not*
    pushed down: if the provider removed those options the engine could
    never explain why they were excluded, which is the core purpose of the
    decision layer. The engine therefore evaluates the hard constraints
    itself and produces eligible and ineligible candidates with reasons.
    """
    return OptionSearchCriteria(
        location=criteria.location,
        category=criteria.category,
        geographic_anchor="Cape Town",
        query_terms=criteria.semantic_descriptors,
    )
