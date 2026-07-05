"""Tests for auth endpoints: register, login, refresh, logout, protected routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


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
        "/users/me", headers={"Authorization": "Bearer notavalidtoken"}
    )
    assert resp.status_code == 401


async def test_me_returns_profile(test_client: AsyncClient) -> None:
    reg = await test_client.post(
        "/auth/register",
        json={"email": "profile@example.com", "password": "securepass1"},
    )
    token = reg.json()["access_token"]

    resp = await test_client.get(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
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
    headers = {"Authorization": f"Bearer {token}"}

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
