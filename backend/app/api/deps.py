"""Shared FastAPI dependencies.

A single place for cross-cutting dependencies that route handlers will
`Depends()` on. Kept deliberately thin at this milestone — it re-exports
the settings/DB/Redis dependencies already defined in their owning
modules, so route handlers only need one import path
(`app.api.deps`) regardless of which infrastructure module actually
implements a dependency. Authentication dependencies (`get_current_user`,
`require_role`) are added here in the milestone that implements JWT auth.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth.auth_service import AuthService
from app.application.auth.ports import PasswordHasher, RefreshTokenRepository, TokenService, UserRepository
from app.application.documents.cover_letter_generation_service import CoverLetterGenerationService
from app.application.documents.ports import (
    FileStorage,
    GeneratedCoverLetterRepository,
    GeneratedResumeRepository,
    PdfRenderer,
)
from app.application.documents.resume_generation_service import ResumeGenerationService
from app.application.jobs.ingestion_service import JobIngestionService
from app.application.jobs.ports import JobRepository, JobSourceAdapter
from app.application.operations.action_recommendation import ActionRecommendationService
from app.application.operations.incident_investigation import IncidentInvestigationService
from app.application.operations.operations_service import OperationsService
from app.application.mobility.registry import MobilityProviderRegistry
from app.application.mobility.service import MobilityService
from app.application.planning.adaptation_service import PlanAdaptationService
from app.application.planning.decision_service import PlanningDecisionService
from app.application.planning.execution_service import PlanExecutionService
from app.application.planning.information import PlanningInformationService
from app.application.planning.intent_interpreter import IntentInterpreter
from app.application.planning.live_intelligence_service import LiveIntelligenceService
from app.application.planning.planning_service import PlanningService
from app.application.planning.ports import PlanningInformationProvider, PlanningUnderstandingPort, PlanRepository
from app.application.planning.selection_service import PlanSelectionService
from app.application.planning.understanding_service import DeterministicUnderstandingEngine
from app.application.profile.ports import ProfileRepository
from app.application.profile.profile_service import ProfileService
from app.application.scoring.ports import JobMatchRepository, LLMProvider
from app.application.scoring.scoring_service import JobScoringService
from app.application.services.ports import ServiceRepository
from app.application.services.service_service import ServiceService
from app.core.config import Settings, get_settings
from app.infrastructure.ai_providers.anthropic_provider import AnthropicProvider
from app.infrastructure.cache.redis import get_redis_client
from app.infrastructure.db.repositories.generated_cover_letter_repository import (
    SqlAlchemyGeneratedCoverLetterRepository,
)
from app.infrastructure.db.repositories.generated_resume_repository import SqlAlchemyGeneratedResumeRepository
from app.infrastructure.db.repositories.job_match_repository import SqlAlchemyJobMatchRepository
from app.infrastructure.db.repositories.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.repositories.operations_repositories import (
    SqlAlchemyActionRepository,
    SqlAlchemyApprovalRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyIncidentRepository,
)
from app.infrastructure.db.repositories.plan_repository import SqlAlchemyPlanRepository
from app.infrastructure.db.repositories.profile_repository import SqlAlchemyProfileRepository
from app.infrastructure.db.repositories.refresh_token_repository import SqlAlchemyRefreshTokenRepository
from app.infrastructure.db.repositories.service_repository import SqlAlchemyServiceRepository
from app.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.job_sources.adzuna import AdzunaJobSourceAdapter
from app.infrastructure.planning import (
    CapeTownFixtureInformationProvider,
    OpenStreetMapInformationProvider,
)
from app.infrastructure.rendering.pdf_renderer import FpdfPdfRenderer
from app.infrastructure.security.bcrypt_password_hasher import BcryptPasswordHasher
from app.infrastructure.security.jwt_token_service import JwtTokenService
from app.infrastructure.storage.local_storage import LocalFileStorage


def get_job_source_adapter(settings: Annotated[Settings, Depends(get_settings)]) -> JobSourceAdapter:
    """The active job source adapter.

    A single `Depends()` chokepoint — swapping in a Greenhouse/Lever
    adapter later, or making the source configurable, changes this
    function only, not any route handler or the ingestion service.
    """
    return AdzunaJobSourceAdapter(settings)


def get_job_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> JobRepository:
    return SqlAlchemyJobRepository(session)


def get_service_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> ServiceRepository:
    return SqlAlchemyServiceRepository(session)


def get_service_service(
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
) -> ServiceService:
    return ServiceService(repository)


def get_operations_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> OperationsService:
    return OperationsService(
        events=SqlAlchemyEventRepository(session),
        incidents=SqlAlchemyIncidentRepository(session),
        actions=SqlAlchemyActionRepository(session),
        approvals=SqlAlchemyApprovalRepository(session),
        audit_logs=SqlAlchemyAuditLogRepository(session),
    )


def get_incident_investigation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentInvestigationService:
    return IncidentInvestigationService(
        incidents=SqlAlchemyIncidentRepository(session),
        events=SqlAlchemyEventRepository(session),
        services=SqlAlchemyServiceRepository(session),
    )


def get_action_recommendation_service(
    investigation: Annotated[IncidentInvestigationService, Depends(get_incident_investigation_service)],
) -> ActionRecommendationService:
    return ActionRecommendationService(investigation)


def get_job_ingestion_service(
    source_adapter: Annotated[JobSourceAdapter, Depends(get_job_source_adapter)],
    repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> JobIngestionService:
    return JobIngestionService(source_adapter=source_adapter, repository=repository)


def get_profile_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> ProfileRepository:
    return SqlAlchemyProfileRepository(session)


def get_profile_service(
    repository: Annotated[ProfileRepository, Depends(get_profile_repository)],
) -> ProfileService:
    return ProfileService(repository)


def get_llm_provider(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    """The active LLM provider.

    A single `Depends()` chokepoint — the same pattern as
    `get_job_source_adapter` — so adding an OpenAI/Gemini adapter later
    (per `docs/adr/0005-ai-provider-abstraction.md`) changes this function
    only.
    """
    return AnthropicProvider(settings)


def get_job_match_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> JobMatchRepository:
    return SqlAlchemyJobMatchRepository(session)


def get_job_scoring_service(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    profile_repository: Annotated[ProfileRepository, Depends(get_profile_repository)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    job_match_repository: Annotated[JobMatchRepository, Depends(get_job_match_repository)],
) -> JobScoringService:
    return JobScoringService(
        llm_provider=llm_provider,
        profile_repository=profile_repository,
        job_repository=job_repository,
        job_match_repository=job_match_repository,
    )


def get_pdf_renderer() -> PdfRenderer:
    """The active PDF renderer.

    A single `Depends()` chokepoint, the same pattern as
    `get_job_source_adapter`/`get_llm_provider` — swapping rendering
    libraries later changes this function only.
    """
    return FpdfPdfRenderer()


def get_file_storage(settings: Annotated[Settings, Depends(get_settings)]) -> FileStorage:
    """The active file storage backend.

    A single `Depends()` chokepoint — swapping `LocalFileStorage` for an
    Azure Blob Storage adapter later (per
    `docs/architecture/cloud-architecture.md`) changes this function
    only.
    """
    return LocalFileStorage(settings.generated_documents_dir)


def get_resume_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)]
) -> GeneratedResumeRepository:
    return SqlAlchemyGeneratedResumeRepository(session)


def get_cover_letter_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GeneratedCoverLetterRepository:
    return SqlAlchemyGeneratedCoverLetterRepository(session)


def get_resume_generation_service(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    pdf_renderer: Annotated[PdfRenderer, Depends(get_pdf_renderer)],
    file_storage: Annotated[FileStorage, Depends(get_file_storage)],
    profile_repository: Annotated[ProfileRepository, Depends(get_profile_repository)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    resume_repository: Annotated[GeneratedResumeRepository, Depends(get_resume_repository)],
) -> ResumeGenerationService:
    return ResumeGenerationService(
        llm_provider=llm_provider,
        pdf_renderer=pdf_renderer,
        file_storage=file_storage,
        profile_repository=profile_repository,
        job_repository=job_repository,
        resume_repository=resume_repository,
    )


def get_cover_letter_generation_service(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    pdf_renderer: Annotated[PdfRenderer, Depends(get_pdf_renderer)],
    file_storage: Annotated[FileStorage, Depends(get_file_storage)],
    profile_repository: Annotated[ProfileRepository, Depends(get_profile_repository)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    cover_letter_repository: Annotated[GeneratedCoverLetterRepository, Depends(get_cover_letter_repository)],
) -> CoverLetterGenerationService:
    return CoverLetterGenerationService(
        llm_provider=llm_provider,
        pdf_renderer=pdf_renderer,
        file_storage=file_storage,
        profile_repository=profile_repository,
        job_repository=job_repository,
        cover_letter_repository=cover_letter_repository,
    )


def get_user_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserRepository:
    return SqlAlchemyUserRepository(session)


def get_refresh_token_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RefreshTokenRepository:
    return SqlAlchemyRefreshTokenRepository(session)


def get_password_hasher() -> PasswordHasher:
    """The active password hasher.

    A single `Depends()` chokepoint — swapping bcrypt for argon2id later
    (both are named as acceptable choices in
    `docs/architecture/security.md`) changes this function only.
    """
    return BcryptPasswordHasher()


def get_token_service(settings: Annotated[Settings, Depends(get_settings)]) -> TokenService:
    return JwtTokenService(settings)


def get_auth_service(
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    refresh_token_repository: Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(
        user_repository=user_repository,
        refresh_token_repository=refresh_token_repository,
        password_hasher=password_hasher,
        token_service=token_service,
        refresh_token_ttl=timedelta(days=settings.refresh_token_expire_days),
    )


__all__ = [
    "Settings",
    "get_settings",
    "get_db_session",
    "get_redis_client",
    "get_job_source_adapter",
    "get_job_repository",
    "get_service_repository",
    "get_service_service",
    "get_operations_service",
    "get_incident_investigation_service",
    "get_action_recommendation_service",
    "get_job_ingestion_service",
    "get_profile_repository",
    "get_profile_service",
    "get_llm_provider",
    "get_job_match_repository",
    "get_job_scoring_service",
    "get_pdf_renderer",
    "get_file_storage",
    "get_resume_repository",
    "get_cover_letter_repository",
    "get_resume_generation_service",
    "get_cover_letter_generation_service",
    "get_user_repository",
    "get_refresh_token_repository",
    "get_password_hasher",
    "get_token_service",
    "get_auth_service",
    "get_intent_interpreter",
    "get_plan_repository",
    "get_planning_service",
    "get_planning_information_provider",
    "get_planning_information_service",
    "get_planning_decision_service",
    "get_plan_selection_service",
    "get_planning_understanding_service",
    "get_plan_adaptation_service",
    "get_plan_execution_service",
]
def get_planning_understanding_service() -> PlanningUnderstandingPort:
    return DeterministicUnderstandingEngine()


def get_intent_interpreter() -> IntentInterpreter:
    return IntentInterpreter()


def get_plan_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlanRepository:
    return SqlAlchemyPlanRepository(session)


def get_planning_service(
    repository: Annotated[PlanRepository, Depends(get_plan_repository)],
) -> PlanningService:
    return PlanningService(repository)


def get_planning_information_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanningInformationProvider:
    if settings.planning_provider.lower() == "fixture":
        return CapeTownFixtureInformationProvider()
    return OpenStreetMapInformationProvider(
        timeout_seconds=settings.openstreetmap_timeout_seconds,
    )


def get_planning_information_service(
    provider: Annotated[PlanningInformationProvider, Depends(get_planning_information_provider)],
) -> PlanningInformationService:
    return PlanningInformationService(provider)


def get_planning_decision_service(
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
) -> PlanningDecisionService:
    return PlanningDecisionService(information)


def get_plan_selection_service(
    plans: Annotated[PlanningService, Depends(get_planning_service)],
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
) -> PlanSelectionService:
    return PlanSelectionService(plans, information)


def get_plan_adaptation_service(
    plans: Annotated[PlanningService, Depends(get_planning_service)],
    decision: Annotated[PlanningDecisionService, Depends(get_planning_decision_service)],
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
) -> PlanAdaptationService:
    return PlanAdaptationService(plans, decision, information)


def get_plan_execution_service(
    plans: Annotated[PlanningService, Depends(get_planning_service)],
    information: Annotated[PlanningInformationService, Depends(get_planning_information_service)],
) -> PlanExecutionService:
    return PlanExecutionService(plans, information)


def get_live_intelligence_service(
    plans: Annotated[PlanningService, Depends(get_planning_service)],
    adaptation: Annotated[PlanAdaptationService, Depends(get_plan_adaptation_service)],
) -> LiveIntelligenceService:
    return LiveIntelligenceService(plans, adaptation)


_default_mobility_registry: MobilityProviderRegistry | None = None


def get_mobility_registry() -> MobilityProviderRegistry:
    """Singleton mobility provider registry instance."""
    global _default_mobility_registry
    if _default_mobility_registry is None:
        from app.infrastructure.mobility.providers import create_default_mobility_registry

        _default_mobility_registry = create_default_mobility_registry()
    return _default_mobility_registry


def get_mobility_service(
    registry: Annotated[MobilityProviderRegistry, Depends(get_mobility_registry)],
) -> MobilityService:
    return MobilityService(registry)


def get_mobility_planning_service(
    mobility_service: Annotated[MobilityService, Depends(get_mobility_service)],
) -> MobilityPlanningService:
    from app.application.planning.mobility_planning_service import MobilityPlanningService

    return MobilityPlanningService(mobility_service)


