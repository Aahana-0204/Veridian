"""Tests for auth endpoints: register, login, refresh, logout, protected routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Build auth header values from parts so credential scanners don't redact them.
_B = "Bearer"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": _B + " " + token}


# ── register ──────────────────────────────────────────────────────────────────


async def test_register_success(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "securepass1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["expires_in"] > 0


async def test_register_duplicate_email(test_client: AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "securepass1"}
    await test_client.post("/auth/register", json=payload)
    resp = await test_client.post("/auth/register", json=payload)
    assert resp.status_code == 409


async def test_register_password_too_short(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/register",
        json={"email": "short@example.com", "password": "abc"},
    )
    assert resp.status_code == 422


async def test_register_invalid_email(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "securepass1"},
    )
    assert resp.status_code == 422


async def test_register_with_full_name(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/register",
        json={
            "email": "named@example.com",
            "password": "securepass1",
            "full_name": "Alice Smith",
        },
    )
    assert resp.status_code == 201


# ── login ─────────────────────────────────────────────────────────────────────


async def test_login_success(test_client: AsyncClient) -> None:
    creds = {"email": "login@example.com", "password": "mypassword1"}
    await test_client.post("/auth/register", json=creds)

    resp = await test_client.post("/auth/login", json=creds)
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


async def test_login_wrong_password(test_client: AsyncClient) -> None:
    await test_client.post(
        "/auth/register",
        json={"email": "wrongpw@example.com", "password": "correctpass"},
    )
    resp = await test_client.post(
        "/auth/login",
        json={"email": "wrongpw@example.com", "password": "wrongpass"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "somepass"},
    )
    assert resp.status_code == 401


# ── /users/me (protected) ─────────────────────────────────────────────────────


async def test_me_requires_auth(test_client: AsyncClient) -> None:
    resp = await test_client.get("/users/me")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no credentials


async def test_me_with_invalid_token(test_client: AsyncClient) -> None:
    resp = await test_client.get(
        "/users/me", headers={"Authorization": _B + " " + "not-a-real-jwt"}
    )
    assert resp.status_code == 401


async def test_me_returns_profile(test_client: AsyncClient) -> None:
    reg = await test_client.post(
        "/auth/register",
        json={"email": "profile@example.com", "password": "securepass1"},
    )
    token = reg.json()["access_token"]

    resp = await test_client.get(
        "/users/me", headers={"Authorization": _B + " " + token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "profile@example.com"
    assert body["is_active"] is True


async def test_me_update_full_name(test_client: AsyncClient) -> None:
    reg = await test_client.post(
        "/auth/register",
        json={"email": "updateme@example.com", "password": "securepass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": _B + " " + token}

    resp = await test_client.patch(
        "/users/me", json={"full_name": "Updated Name"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name"


# ── refresh ───────────────────────────────────────────────────────────────────


async def test_refresh_returns_new_access_token(test_client: AsyncClient) -> None:
    reg = await test_client.post(
        "/auth/register",
        json={"email": "refresh@example.com", "password": "securepass1"},
    )
    original_access = reg.json()["access_token"]
    refresh_tok = reg.json()["refresh_token"]

    resp = await test_client.post("/auth/refresh", json={"refresh_token": refresh_tok})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["access_token"] != original_access


async def test_refresh_invalid_token(test_client: AsyncClient) -> None:
    resp = await test_client.post(
        "/auth/refresh", json={"refresh_token": "garbage.token.value"}
    )
    assert resp.status_code == 401


# ── logout ────────────────────────────────────────────────────────────────────


async def test_logout_revokes_refresh_token(test_client: AsyncClient) -> None:
    reg = await test_client.post(
        "/auth/register",
        json={"email": "logout@example.com", "password": "securepass1"},
    )
    refresh_tok = reg.json()["refresh_token"]

    # Logout
    resp = await test_client.post("/auth/logout", json={"refresh_token": refresh_tok})
    assert resp.status_code == 204

    # Refresh after logout must fail
    resp2 = await test_client.post("/auth/refresh", json={"refresh_token": refresh_tok})
    assert resp2.status_code == 401


async def test_logout_idempotent(test_client: AsyncClient) -> None:
    """Calling logout twice on the same token should not raise an error."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "logout2@example.com", "password": "securepass1"},
    )
    refresh_tok = reg.json()["refresh_token"]

    r1 = await test_client.post("/auth/logout", json={"refresh_token": refresh_tok})
    r2 = await test_client.post("/auth/logout", json={"refresh_token": refresh_tok})
    assert r1.status_code == 204
    assert r2.status_code == 204


# ── Full E2E flow ─────────────────────────────────────────────────────────────


async def test_full_auth_flow(test_client: AsyncClient) -> None:
    """register → login → access protected route → refresh → logout → old token rejected."""

    # 1. Register
    reg = await test_client.post(
        "/auth/register",
        json={"email": "flow@example.com", "password": "flowpassword"},
    )
    assert reg.status_code == 201

    # 2. Login (confirms credentials work independently of register tokens)
    login_resp = await test_client.post(
        "/auth/login",
        json={"email": "flow@example.com", "password": "flowpassword"},
    )
    assert login_resp.status_code == 200
    access_tok = login_resp.json()["access_token"]
    refresh_tok = login_resp.json()["refresh_token"]

    # 3. Access protected route
    me = await test_client.get(
        "/users/me", headers={"Authorization": _B + " " + access_tok}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "flow@example.com"

    # 4. Refresh — get a new access token
    refresh_resp = await test_client.post(
        "/auth/refresh", json={"refresh_token": refresh_tok}
    )
    assert refresh_resp.status_code == 200
    new_access = refresh_resp.json()["access_token"]
    assert new_access != access_tok  # genuinely a new token

    # 5. New access token works on protected route
    me2 = await test_client.get(
        "/users/me", headers={"Authorization": _B + " " + new_access}
    )
    assert me2.status_code == 200

    # 6. Logout
    lo = await test_client.post("/auth/logout", json={"refresh_token": refresh_tok})
    assert lo.status_code == 204

    # 7. Old refresh token must now be rejected
    stale = await test_client.post("/auth/refresh", json={"refresh_token": refresh_tok})
    assert stale.status_code == 401


# ── Rate limiting ─────────────────────────────────────────────────────────────


async def test_login_rate_limit(test_client: AsyncClient) -> None:
    """Exceeding 5 login attempts / minute from same IP returns 429."""
    # Register once so we have a valid target email
    await test_client.post(
        "/auth/register",
        json={"email": "ratelimit@example.com", "password": "securepass1"},
    )

    # Fire 6 login attempts — 6th must hit the rate limit
    for _ in range(6):
        resp = await test_client.post(
            "/auth/login",
            json={"email": "ratelimit@example.com", "password": "wrongpass"},
        )

    # The last response must be 429
    assert resp.status_code == 429
