"""Application configuration.

Centralizes all environment-driven configuration behind a single, typed
`Settings` object, loaded once via `get_settings()` (cached with
`lru_cache` so it's cheap to depend on from anywhere, including FastAPI's
dependency-injection system).

Design notes
------------
- Values are read from environment variables (and a local `.env` file in
  development) via `pydantic-settings`. Nothing here should ever contain a
  real secret — see `.env.example` at the repo root for the documented set
  of variables, all with placeholder values.
- `Environment` distinguishes development / testing / production so that
  behavior that must differ (e.g. whether interactive API docs are
  exposed) is driven by one explicit field, not scattered `if DEBUG`
  checks.
- This module has no FastAPI or SQLAlchemy imports — it is pure
  configuration and safe to import from any layer.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """The environment the application is running in.

    Deliberately a closed set of three values (not an arbitrary string) so
    environment-dependent branches in the codebase (e.g. `if settings.environment
    is Environment.PRODUCTION`) are checked by the type system, not by string
    comparison typos.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed application settings, sourced from environment variables / `.env`.

    Every field has either a sensible development default or is required
    (no default) when it must be explicitly provided in every environment
    (e.g. `secret_key`).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application identity -------------------------------------------------
    project_name: str = "Dayform"
    api_v1_prefix: str = "/api/v1"
    version: str = "0.1.0"

    # --- Environment / debug ---------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # --- Security ----------------------------------------------------------
    # Required so the settings object fails fast in any environment that
    # forgets to set it, rather than silently running with an insecure
    # default. Used for JWT signing (Milestone 7,
    # `app/infrastructure/security/jwt_token_service.py`) — this field
    # existed as a placeholder since Milestone 1 for exactly this purpose.
    secret_key: str = Field(..., description="Used for JWT signing.")
    # Short-lived by design (ADR-0008, Milestone 0): limits the exposure
    # window if an access token is intercepted.
    access_token_expire_minutes: int = 15
    # The refresh token is the only long-lived credential, and it's
    # revocable (see `docs/adr/0015-authentication.md`) — a longer TTL is
    # acceptable because a compromised one can be invalidated without a
    # password reset.
    refresh_token_expire_days: int = 30

    # --- Database ------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://dayform:dayform@postgres:5432/dayform",
        description="Async SQLAlchemy connection string.",
    )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://") and not value.startswith("postgresql+asyncpg://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    # --- Redis ---------------------------------------------------------------
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- CORS ------------------------------------------------------------------
    backend_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "https://dayform-live.vercel.app"])

    # --- Planning information provider (Milestone 3) ---------------------------
    # Configures the active real-world planning information provider.
    # Defaults to "openstreetmap" for live product operation.
    # Set to "fixture" for deterministic test and demo catalogs.
    planning_provider: str = Field(default="openstreetmap", description="Active planning information provider ('openstreetmap' or 'fixture').")
    openstreetmap_timeout_seconds: float = Field(default=3.0, description="HTTP timeout for live OSM geocoder queries.")

    # M16 live mobility feeds. Maps a mobility provider id (e.g. "myciti") to the
    # URL of a public JSON service-status feed. Empty by default: a provider with
    # no entry here is reported as having no live source at all, which is the
    # truthful state for every current Cape Town transit operator.
    mobility_live_feed_urls: dict[str, str] = Field(
        default_factory=dict,
        description="Provider id -> public JSON live service-status feed URL.",
    )

    # --- Job sources (Milestone 3) --------------------------------------------
    # Optional (default None) so an environment without real Adzuna
    # credentials still starts up normally — the ingestion endpoint returns
    # a clear 503 rather than the app failing at startup. Get free
    # credentials at https://developer.adzuna.com.
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    adzuna_country: str = "us"

    # --- AI provider (Milestone 5) ----------------------------------------------
    # Optional (default None), same reasoning as Adzuna above — the
    # scoring endpoint returns a clear 503 rather than the app failing to
    # start. Verify the current model identifier against
    # https://docs.anthropic.com/en/docs/about-claude/models before
    # deploying — model strings are versioned and change over time.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # --- Document storage (Milestone 6) -----------------------------------------
    # Local disk directory for generated resume/cover-letter PDFs — an
    # interim adapter ahead of Azure Blob Storage (see
    # `docs/architecture/cloud-architecture.md`). Relative paths are
    # resolved against the process's working directory (the container's
    # `/app` in Docker); mount this as a volume in docker-compose.yml if
    # generated documents need to survive a container restart.
    generated_documents_dir: str = "generated_documents"

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}, got {value!r}"
            raise ValueError(msg)
        return normalized

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are enabled everywhere except production.

        Matches the API strategy documented in
        `docs/architecture/api-design.md`: OpenAPI docs are a development
        convenience, not something exposed unauthenticated in production.
        """
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings` instance.

    Cached so repeated calls (e.g. from many FastAPI `Depends(get_settings)`
    usages) don't re-parse the environment on every request — the
    environment doesn't change during a process's lifetime.
    """
    return Settings()
