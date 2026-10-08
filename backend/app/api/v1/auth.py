"""Auth API — register, login, refresh, logout, and the current user.

Unlike every other router in this codebase, `GET /me` is the first
genuinely *protected* endpoint — it demonstrates the `get_current_user`
dependency that future milestones will use to scope profile/jobs/matches/
documents per-user (see `docs/adr/0015-authentication.md` for why that
reconciliation isn't done in this milestone).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_auth_service
from app.application.auth.auth_service import AuthService
from app.application.auth.dtos import RegisterUserData, TokenPair
from app.application.auth.errors import InvalidCredentialsError, InvalidTokenError, UserAlreadyExistsError
from app.domain.value_objects.password_policy import WeakPasswordError
from app.infrastructure.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer_scheme = HTTPBearer(description="Access token issued by POST /auth/login or /auth/refresh.")


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

    @classmethod
    def from_token_pair(cls, tokens: TokenPair) -> TokenResponse:
        return cls(
            access_token=tokens.access_token, refresh_token=tokens.refresh_token, token_type=tokens.token_type
        )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Resolve the authenticated user from the `Authorization: Bearer <token>` header.

    Exported for reuse: any future protected route depends on this the
    same way `GET /auth/me` below does.
    """
    try:
        return await auth_service.get_current_user(access_token=credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post(
    "/register", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Register a new user"
)
async def register(
    body: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserRead:
    """Create a new account. Does not log the user in — call `/auth/login` next."""
    try:
        user = await auth_service.register(RegisterUserData(email=body.email, password=body.password))
    except WeakPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return UserRead.model_validate(user)


@router.post(
    "/login", response_model=TokenResponse, summary="Log in and receive an access/refresh token pair"
)
async def login(
    body: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        tokens = await auth_service.authenticate(email=body.email, password=body.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse.from_token_pair(tokens)


@router.post(
    "/anonymous-session",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a unique anonymous guest user and receive an access/refresh token pair",
)
async def anonymous_session(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    tokens = await auth_service.create_anonymous_session()
    return TokenResponse.from_token_pair(tokens)


@router.post(
    "/refresh", response_model=TokenResponse, summary="Exchange a refresh token for a new token pair"
)
async def refresh(
    body: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """The presented refresh token is revoked as part of this call (rotation) — reuse the new one, not the old."""
    try:
        tokens = await auth_service.refresh(refresh_token=body.refresh_token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse.from_token_pair(tokens)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Revoke a refresh token"
)
async def logout(
    body: LogoutRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    """Idempotent — logging out with an already-revoked or unknown token still returns 204."""
    await auth_service.logout(refresh_token=body.refresh_token)


@router.get("/me", response_model=UserRead, summary="The currently authenticated user")
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(current_user)
