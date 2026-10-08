"""Authentication use cases: register, login, refresh, logout, and
resolving the current user from an access token.

No FastAPI, no SQLAlchemy, no bcrypt/PyJWT imports — only the `Protocol`s
this module depends on, matching every other application service in this
codebase.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.application.auth.dtos import RegisterUserData, TokenPair
from app.application.auth.errors import InvalidCredentialsError, InvalidTokenError, UserAlreadyExistsError
from app.application.auth.ports import PasswordHasher, RefreshTokenRepository, TokenService, UserRepository
from app.core.logging import get_logger
from app.domain.value_objects.password_policy import validate_password_strength

if TYPE_CHECKING:
    from app.infrastructure.db.models import User

logger = get_logger(__name__)

_REFRESH_TOKEN_BYTES = 32


def _hash_token(raw_token: str) -> str:
    """Hash a high-entropy opaque token with SHA-256.

    Not bcrypt: bcrypt's deliberate slowness exists to resist brute-force
    guessing of low-entropy human-chosen passwords. A 32-byte
    cryptographically random refresh token has no guessable structure to
    brute-force in the first place — a fast, standard cryptographic hash
    is the correct (and standard) tool here, and using bcrypt would only
    add needless latency to every refresh/logout call.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class AuthService:
    """Orchestrates registration, login, token refresh, and logout."""

    def __init__(
        self,
        *,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        refresh_token_ttl: timedelta,
    ) -> None:
        self._user_repository = user_repository
        self._refresh_token_repository = refresh_token_repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_token_ttl = refresh_token_ttl

    async def register(self, data: RegisterUserData) -> User:
        """Create a new user account.

        Raises `app.domain.value_objects.password_policy.WeakPasswordError`
        if the password doesn't meet policy, or `UserAlreadyExistsError`
        if the email is already registered.
        """
        validate_password_strength(data.password)

        existing = await self._user_repository.get_by_email(email=data.email)
        if existing is not None:
            msg = f"A user with email {data.email!r} already exists."
            raise UserAlreadyExistsError(msg)

        password_hash = self._password_hasher.hash(data.password)
        user = await self._user_repository.create(email=data.email, password_hash=password_hash)
        logger.info("user_registered", user_id=str(user.id))
        return user

    async def authenticate(self, *, email: str, password: str) -> TokenPair:
        """Verify credentials and issue a new access/refresh token pair.

        Raises `InvalidCredentialsError` for either an unknown email or a
        wrong password — deliberately the same error for both (see the
        error's docstring for why).
        """
        user = await self._user_repository.get_by_email(email=email)
        if user is None or not self._password_hasher.verify(
            password=password, password_hash=user.password_hash
        ):
            msg = "Invalid email or password."
            raise InvalidCredentialsError(msg)

        tokens = await self._issue_tokens(user_id=user.id)
        logger.info("user_logged_in", user_id=str(user.id))
        return tokens

    async def create_anonymous_session(self) -> TokenPair:
        """Provision a unique, isolated anonymous guest user and issue tokens."""
        synthetic_email = f"anon_{uuid4().hex}@guest.dayform.local"
        random_secret = secrets.token_urlsafe(32)
        password_hash = self._password_hasher.hash(random_secret)

        user = await self._user_repository.create(
            email=synthetic_email,
            password_hash=password_hash,
            is_anonymous=True,
        )
        tokens = await self._issue_tokens(user_id=user.id)
        logger.info("anonymous_session_created", user_id=str(user.id))
        return tokens

    async def refresh(self, *, refresh_token: str) -> TokenPair:
        """Exchange a valid, unexpired, unrevoked refresh token for a new pair.

        The presented refresh token is revoked as part of this call
        (rotation) — each refresh token is single-use, limiting the
        damage window if one is ever intercepted.
        """
        token_hash = _hash_token(refresh_token)
        record = await self._refresh_token_repository.get_active(token_hash=token_hash)
        if record is None:
            msg = "Refresh token is invalid, expired, or has already been used."
            raise InvalidTokenError(msg)

        await self._refresh_token_repository.revoke(token_hash=token_hash)
        return await self._issue_tokens(user_id=record.user_id)

    async def logout(self, *, refresh_token: str) -> None:
        """Revoke a refresh token. Idempotent — logging out twice with the
        same token is not an error.
        """
        token_hash = _hash_token(refresh_token)
        await self._refresh_token_repository.revoke(token_hash=token_hash)

    async def get_current_user(self, *, access_token: str) -> User:
        """Resolve the user a valid access token belongs to.

        Raises `InvalidTokenError` for a malformed/expired token, or for
        a token whose user no longer exists.
        """
        user_id: UUID = self._token_service.decode_access_token(access_token)
        user = await self._user_repository.get_by_id(user_id=user_id)
        if user is None:
            msg = "Token does not correspond to an existing user."
            raise InvalidTokenError(msg)
        return user

    async def _issue_tokens(self, *, user_id: UUID) -> TokenPair:
        access_token = self._token_service.create_access_token(user_id=user_id)

        raw_refresh_token = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
        token_hash = _hash_token(raw_refresh_token)
        expires_at = datetime.now(UTC) + self._refresh_token_ttl
        await self._refresh_token_repository.create(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

        return TokenPair(access_token=access_token, refresh_token=raw_refresh_token)
