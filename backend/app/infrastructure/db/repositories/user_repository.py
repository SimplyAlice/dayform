"""User repository.

Implements `UserRepository` (`app/application/auth/ports.py`) against
SQLAlchemy. Uses the same SAVEPOINT-scoped duplicate-handling pattern
proven in `SqlAlchemyJobRepository`/`SqlAlchemyProfileRepository`
(explicit `begin_nested()`/`commit()`/`rollback()`, not `async with` —
found in Milestones 3 and 4 to be the pattern that reliably restores
session state after a caught `IntegrityError`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth.errors import UserAlreadyExistsError
from app.infrastructure.db.models import User


class SqlAlchemyUserRepository:
    """SQLAlchemy-backed implementation of the `UserRepository` port."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, *, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, *, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self, *, email: str, password_hash: str, is_anonymous: bool = False
    ) -> User:
        nested = await self._session.begin_nested()
        user = User(email=email, password_hash=password_hash, is_anonymous=is_anonymous)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await nested.rollback()
            msg = f"A user with email {email!r} already exists."
            raise UserAlreadyExistsError(msg) from exc
        else:
            await nested.commit()
        return user
