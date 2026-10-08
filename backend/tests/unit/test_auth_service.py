"""Unit tests for `AuthService`. Fakes only — matching the pattern
established for every other application service in this codebase.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.application.auth.auth_service import AuthService
from app.application.auth.dtos import RegisterUserData
from app.application.auth.errors import InvalidCredentialsError, InvalidTokenError, UserAlreadyExistsError
from app.domain.value_objects.password_policy import WeakPasswordError


class FakeUser:
    def __init__(
        self, *, id_: uuid.UUID, email: str, password_hash: str, is_anonymous: bool = False
    ) -> None:
        self.id = id_
        self.email = email
        self.password_hash = password_hash
        self.is_anonymous = is_anonymous


class FakeUserRepository:
    def __init__(self) -> None:
        self._users_by_email: dict[str, FakeUser] = {}
        self._users_by_id: dict[uuid.UUID, FakeUser] = {}

    async def get_by_email(self, *, email: str) -> FakeUser | None:
        return self._users_by_email.get(email)

    async def get_by_id(self, *, user_id: uuid.UUID) -> FakeUser | None:
        return self._users_by_id.get(user_id)

    async def create(
        self, *, email: str, password_hash: str, is_anonymous: bool = False
    ) -> FakeUser:
        user = FakeUser(
            id_=uuid.uuid4(), email=email, password_hash=password_hash, is_anonymous=is_anonymous
        )
        self._users_by_email[email] = user
        self._users_by_id[user.id] = user
        return user


class FakeRefreshTokenRecord:
    def __init__(self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
        self.user_id = user_id
        self.token_hash = token_hash
        self.expires_at = expires_at
        self.revoked_at: datetime | None = None


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self._records: dict[str, FakeRefreshTokenRecord] = {}

    async def create(
        self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> FakeRefreshTokenRecord:
        record = FakeRefreshTokenRecord(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._records[token_hash] = record
        return record

    async def get_active(self, *, token_hash: str) -> FakeRefreshTokenRecord | None:
        record = self._records.get(token_hash)
        if record is None or record.revoked_at is not None or record.expires_at <= datetime.now(UTC):
            return None
        return record

    async def revoke(self, *, token_hash: str) -> None:
        record = self._records.get(token_hash)
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)


class FakePasswordHasher:
    """A fast, insecure stand-in — real hashing is exercised in
    `test_security_adapters.py`; this fake just proves `AuthService`
    calls the port correctly.
    """

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, *, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{password}"


class FakeTokenService:
    def __init__(self) -> None:
        self.issued_for: list[uuid.UUID] = []

    def create_access_token(self, *, user_id: uuid.UUID) -> str:
        self.issued_for.append(user_id)
        return f"access-token-for-{user_id}"

    def decode_access_token(self, token: str) -> uuid.UUID:
        prefix = "access-token-for-"
        if not token.startswith(prefix):
            raise InvalidTokenError("bad token")
        return uuid.UUID(token[len(prefix) :])


def _make_service(
    *,
    user_repository: FakeUserRepository | None = None,
    refresh_token_repository: FakeRefreshTokenRepository | None = None,
) -> tuple[AuthService, FakeUserRepository, FakeRefreshTokenRepository, FakeTokenService]:
    user_repository = user_repository or FakeUserRepository()
    refresh_token_repository = refresh_token_repository or FakeRefreshTokenRepository()
    token_service = FakeTokenService()
    service = AuthService(
        user_repository=user_repository,
        refresh_token_repository=refresh_token_repository,
        password_hasher=FakePasswordHasher(),
        token_service=token_service,
        refresh_token_ttl=timedelta(days=30),
    )
    return service, user_repository, refresh_token_repository, token_service


@pytest.mark.asyncio
async def test_register_creates_a_user() -> None:
    service, *_ = _make_service()

    user = await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))

    assert user.email == "ada@example.com"
    assert user.password_hash == "hashed:Sup3rSecret"


@pytest.mark.asyncio
async def test_register_rejects_a_weak_password() -> None:
    service, *_ = _make_service()

    with pytest.raises(WeakPasswordError):
        await service.register(RegisterUserData(email="ada@example.com", password="weak"))


@pytest.mark.asyncio
async def test_register_rejects_a_duplicate_email() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))

    with pytest.raises(UserAlreadyExistsError):
        await service.register(RegisterUserData(email="ada@example.com", password="AnotherPass1"))


@pytest.mark.asyncio
async def test_authenticate_succeeds_with_correct_credentials() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))

    tokens = await service.authenticate(email="ada@example.com", password="Sup3rSecret")

    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.token_type == "bearer"


@pytest.mark.asyncio
async def test_authenticate_rejects_wrong_password() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))

    with pytest.raises(InvalidCredentialsError):
        await service.authenticate(email="ada@example.com", password="WrongPassword1")


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_email() -> None:
    service, *_ = _make_service()

    with pytest.raises(InvalidCredentialsError):
        await service.authenticate(email="nobody@example.com", password="Sup3rSecret")


@pytest.mark.asyncio
async def test_refresh_issues_a_new_token_pair() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))
    tokens = await service.authenticate(email="ada@example.com", password="Sup3rSecret")

    new_tokens = await service.refresh(refresh_token=tokens.refresh_token)

    assert new_tokens.access_token
    assert new_tokens.refresh_token != tokens.refresh_token


@pytest.mark.asyncio
async def test_refresh_token_is_single_use() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))
    tokens = await service.authenticate(email="ada@example.com", password="Sup3rSecret")

    await service.refresh(refresh_token=tokens.refresh_token)

    with pytest.raises(InvalidTokenError):
        await service.refresh(refresh_token=tokens.refresh_token)


@pytest.mark.asyncio
async def test_refresh_rejects_an_unknown_token() -> None:
    service, *_ = _make_service()

    with pytest.raises(InvalidTokenError):
        await service.refresh(refresh_token="not-a-real-refresh-token")


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token() -> None:
    service, *_ = _make_service()
    await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))
    tokens = await service.authenticate(email="ada@example.com", password="Sup3rSecret")

    await service.logout(refresh_token=tokens.refresh_token)

    with pytest.raises(InvalidTokenError):
        await service.refresh(refresh_token=tokens.refresh_token)


@pytest.mark.asyncio
async def test_logout_is_idempotent_for_an_unknown_token() -> None:
    service, *_ = _make_service()

    await service.logout(refresh_token="never-issued-token")  # should not raise


@pytest.mark.asyncio
async def test_get_current_user_resolves_from_a_valid_access_token() -> None:
    service, *_ = _make_service()
    registered = await service.register(RegisterUserData(email="ada@example.com", password="Sup3rSecret"))
    tokens = await service.authenticate(email="ada@example.com", password="Sup3rSecret")

    resolved = await service.get_current_user(access_token=tokens.access_token)

    assert resolved.id == registered.id


@pytest.mark.asyncio
async def test_get_current_user_rejects_an_invalid_token() -> None:
    service, *_ = _make_service()

    with pytest.raises(InvalidTokenError):
        await service.get_current_user(access_token="garbage")


@pytest.mark.asyncio
async def test_create_anonymous_session_creates_unique_users() -> None:
    service, user_repo, _ = _make_service()

    tokens_a = await service.create_anonymous_session()
    tokens_b = await service.create_anonymous_session()

    assert tokens_a.access_token != tokens_b.access_token
    assert tokens_a.refresh_token != tokens_b.refresh_token

    user_a = await service.get_current_user(access_token=tokens_a.access_token)
    user_b = await service.get_current_user(access_token=tokens_b.access_token)

    assert user_a.id != user_b.id
    assert user_a.is_anonymous is True
    assert user_b.is_anonymous is True
    assert user_a.email.startswith("anon_")
    assert user_b.email.startswith("anon_")
    assert user_a.email != user_b.email


@pytest.mark.asyncio
async def test_create_anonymous_session_refresh_preserves_user() -> None:
    service, _, _ = _make_service()

    tokens = await service.create_anonymous_session()
    initial_user = await service.get_current_user(access_token=tokens.access_token)

    refreshed_tokens = await service.refresh(refresh_token=tokens.refresh_token)
    refreshed_user = await service.get_current_user(access_token=refreshed_tokens.access_token)

    assert refreshed_user.id == initial_user.id
    assert refreshed_tokens.access_token != tokens.access_token
