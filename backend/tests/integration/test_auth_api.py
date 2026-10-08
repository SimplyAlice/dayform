"""API-level integration tests for the auth endpoints.

Real app, real routing, real database, real bcrypt/JWT — no fakes are
needed here since none of auth's dependencies are external services (no
network calls, unlike Adzuna/Anthropic in earlier milestones).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import get_settings
from app.main import create_app


def _prefix(resource: str) -> str:
    return f"{get_settings().api_v1_prefix}/{resource}"


@pytest.fixture
async def auth_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    app = create_app()

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_register_creates_a_user(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert "password" not in body
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_register_rejects_a_weak_password(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "weak"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(auth_client: AsyncClient) -> None:
    payload = {"email": "ada@example.com", "password": "Sup3rSecret"}
    first = await auth_client.post(_prefix("auth/register"), json=payload)
    assert first.status_code == 201

    second = await auth_client.post(_prefix("auth/register"), json=payload)

    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_credentials(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )

    response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )

    response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "WrongPassword1"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_unknown_email(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        _prefix("auth/login"), json={"email": "nobody@example.com", "password": "Sup3rSecret"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_the_authenticated_user(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    login_response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    access_token = login_response.json()["access_token"]

    response = await auth_client.get(_prefix("auth/me"), headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


@pytest.mark.asyncio
async def test_me_rejects_a_missing_token(auth_client: AsyncClient) -> None:
    response = await auth_client.get(_prefix("auth/me"))

    assert response.status_code in (401, 403)  # HTTPBearer returns 403 when the header is absent entirely


@pytest.mark.asyncio
async def test_me_rejects_an_invalid_token(auth_client: AsyncClient) -> None:
    response = await auth_client.get(_prefix("auth/me"), headers={"Authorization": "Bearer garbage-token"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_issues_a_new_token_pair(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    login_response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await auth_client.post(_prefix("auth/refresh"), json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert response.json()["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_rejects_a_reused_token(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    login_response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    refresh_token = login_response.json()["refresh_token"]
    await auth_client.post(_prefix("auth/refresh"), json={"refresh_token": refresh_token})

    second_attempt = await auth_client.post(_prefix("auth/refresh"), json={"refresh_token": refresh_token})

    assert second_attempt.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token(auth_client: AsyncClient) -> None:
    await auth_client.post(
        _prefix("auth/register"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    login_response = await auth_client.post(
        _prefix("auth/login"), json={"email": "ada@example.com", "password": "Sup3rSecret"}
    )
    refresh_token = login_response.json()["refresh_token"]

    logout_response = await auth_client.post(_prefix("auth/logout"), json={"refresh_token": refresh_token})
    assert logout_response.status_code == 204

    refresh_attempt = await auth_client.post(_prefix("auth/refresh"), json={"refresh_token": refresh_token})
    assert refresh_attempt.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_session_creates_unique_users_with_sub(auth_client: AsyncClient) -> None:
    res_a = await auth_client.post(_prefix("auth/anonymous-session"))
    assert res_a.status_code == 201
    body_a = res_a.json()

    res_b = await auth_client.post(_prefix("auth/anonymous-session"))
    assert res_b.status_code == 201
    body_b = res_b.json()

    assert body_a["access_token"] != body_b["access_token"]
    assert body_a["refresh_token"] != body_b["refresh_token"]

    me_a = await auth_client.get(
        _prefix("auth/me"), headers={"Authorization": f"Bearer {body_a['access_token']}"}
    )
    assert me_a.status_code == 200
    user_a = me_a.json()

    me_b = await auth_client.get(
        _prefix("auth/me"), headers={"Authorization": f"Bearer {body_b['access_token']}"}
    )
    assert me_b.status_code == 200
    user_b = me_b.json()

    assert user_a["id"] != user_b["id"]
    assert user_a["email"].startswith("anon_")
    assert user_b["email"].startswith("anon_")
    assert user_a["email"] != user_b["email"]


@pytest.mark.asyncio
async def test_anonymous_session_refresh_preserves_identity(auth_client: AsyncClient) -> None:
    res = await auth_client.post(_prefix("auth/anonymous-session"))
    assert res.status_code == 201
    tokens = res.json()

    me_initial = await auth_client.get(
        _prefix("auth/me"), headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    initial_user = me_initial.json()

    refresh_res = await auth_client.post(
        _prefix("auth/refresh"), json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_res.status_code == 200
    refreshed_tokens = refresh_res.json()

    me_refreshed = await auth_client.get(
        _prefix("auth/me"), headers={"Authorization": f"Bearer {refreshed_tokens['access_token']}"}
    )
    refreshed_user = me_refreshed.json()

    assert refreshed_user["id"] == initial_user["id"]
    assert refreshed_tokens["access_token"] != tokens["access_token"]
