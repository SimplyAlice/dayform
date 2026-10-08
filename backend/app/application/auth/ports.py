"""Ports for authentication.

`AuthService` depends on these `Protocol`s, not on bcrypt, PyJWT, or
SQLAlchemy directly — the same Strategy-pattern separation used
throughout this codebase (job sources, AI providers, PDF rendering, file
storage).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app.infrastructure.db.models import RefreshToken, User


class PasswordHasher(Protocol):
    """Hashes and verifies user passwords.

    Deliberately separate from token hashing (see
    `RefreshTokenRepository`'s docstring for why) — a `PasswordHasher`
    uses a deliberately slow algorithm (bcrypt) suited to low-entropy
    human-chosen passwords, which would be the wrong tool for hashing a
    high-entropy random refresh token.
    """

    def hash(self, password: str) -> str:
        """Return a salted hash of `password`, safe to store."""
        ...

    def verify(self, *, password: str, password_hash: str) -> bool:
        """Return whether `password` matches a previously-hashed value."""
        ...


class TokenService(Protocol):
    """Issues and validates short-lived JWT access tokens."""

    def create_access_token(self, *, user_id: UUID) -> str:
        """Return a signed, short-lived JWT encoding `user_id`."""
        ...

    def decode_access_token(self, token: str) -> UUID:
        """Return the `user_id` encoded in a valid, unexpired access token.

        Raises `app.application.auth.errors.InvalidTokenError` for
        anything malformed, unsigned, or expired.
        """
        ...


class UserRepository(Protocol):
    """Persistence operations for user accounts."""

    async def get_by_email(self, *, email: str) -> User | None: ...

    async def get_by_id(self, *, user_id: UUID) -> User | None: ...

    async def create(
        self, *, email: str, password_hash: str, is_anonymous: bool = False
    ) -> User:
        """Persist a new user. Callers must catch the database-level
        uniqueness violation themselves (see `SqlAlchemyUserRepository`) —
        this port doesn't hide that as its own exception type since
        `AuthService` needs to distinguish it from other failure modes
        precisely (`UserAlreadyExistsError`).
        """
        ...


class RefreshTokenRepository(Protocol):
    """Persistence operations for revocable refresh tokens.

    Refresh tokens are opaque random strings (not JWTs) — the whole point
    of storing a hash of one server-side is to make it revocable via a
    database lookup, which a stateless JWT gains nothing from being used
    for here (see `docs/adr/0015-authentication.md`).
    """

    async def create(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> RefreshToken:
        """Persist a new refresh token record."""
        ...

    async def get_active(self, *, token_hash: str) -> RefreshToken | None:
        """Return the matching refresh token record if it exists, is not
        expired, and has not been revoked — `None` otherwise.
        """
        ...

    async def revoke(self, *, token_hash: str) -> None:
        """Mark a refresh token as revoked. A no-op if it doesn't exist
        (logout is idempotent from the client's point of view).
        """
        ...
