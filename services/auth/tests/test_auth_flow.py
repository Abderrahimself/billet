"""signup · login · refresh rotation · /me authorization (§6, §9)."""
from __future__ import annotations

import asyncio

from httpx import AsyncClient

PASSWORD = "correct horse battery"


async def _signup(client: AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "display_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_signup_returns_a_token_pair(client: AsyncClient, unique_email: str) -> None:
    body = await _signup(client, unique_email)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_signup_duplicate_email_conflicts(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email)
    resp = await client.post(
        "/api/auth/signup",
        json={"email": unique_email, "password": PASSWORD, "display_name": "Dup"},
    )
    assert resp.status_code == 409


async def test_signup_rejects_short_password(client: AsyncClient, unique_email: str) -> None:
    resp = await client.post(
        "/api/auth/signup",
        json={"email": unique_email, "password": "short", "display_name": "X"},
    )
    assert resp.status_code == 422  # Pydantic min_length (§9 validation)


async def test_login_success_and_failures(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email)

    ok = await client.post("/api/auth/login", json={"email": unique_email, "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong = await client.post(
        "/api/auth/login", json={"email": unique_email, "password": "nope-nope-nope"}
    )
    assert wrong.status_code == 401

    unknown = await client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert unknown.status_code == 401


async def test_refresh_rotates_and_rejects_reuse(client: AsyncClient, unique_email: str) -> None:
    tokens = await _signup(client, unique_email)
    first_refresh = tokens["refresh_token"]

    rotated = await client.post("/api/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    new_tokens = rotated.json()
    assert new_tokens["refresh_token"] != first_refresh

    # the consumed refresh token is single-use — replay must fail (rotation)
    replay = await client.post("/api/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401

    # the freshly issued one still works
    again = await client.post(
        "/api/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert again.status_code == 200


async def test_refresh_rejects_garbage(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


async def test_concurrent_refresh_redeems_token_once(
    client: AsyncClient, unique_email: str
) -> None:
    # M1: two simultaneous refreshes of one single-use token — exactly one wins,
    # the other is rejected. The atomic conditional UPDATE guarantees this.
    tokens = await _signup(client, unique_email)
    refresh_token = tokens["refresh_token"]

    r1, r2 = await asyncio.gather(
        client.post("/api/auth/refresh", json={"refresh_token": refresh_token}),
        client.post("/api/auth/refresh", json={"refresh_token": refresh_token}),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 401]


async def test_me_requires_and_honors_bearer(client: AsyncClient, unique_email: str) -> None:
    tokens = await _signup(client, unique_email)
    access = tokens["access_token"]

    assert (await client.get("/api/auth/me")).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    profile = me.json()
    assert profile["email"] == unique_email
    assert profile["display_name"] == "Test User"
    assert "password_hash" not in profile  # never leak the hash


async def test_patch_me_updates_profile_and_password(
    client: AsyncClient, unique_email: str
) -> None:
    tokens = await _signup(client, unique_email)
    auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}

    patched = await client.patch(
        "/api/auth/me",
        headers=auth_header,
        json={"display_name": "Renamed", "password": "a whole new password"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Renamed"

    # old password no longer works; new one does
    assert (
        await client.post("/api/auth/login", json={"email": unique_email, "password": PASSWORD})
    ).status_code == 401
    assert (
        await client.post(
            "/api/auth/login",
            json={"email": unique_email, "password": "a whole new password"},
        )
    ).status_code == 200


async def test_password_change_revokes_refresh_tokens(
    client: AsyncClient, unique_email: str
) -> None:
    # M2: a credential change must invalidate outstanding sessions — a refresh
    # token minted before the change can no longer be redeemed.
    tokens = await _signup(client, unique_email)
    old_refresh = tokens["refresh_token"]

    patched = await client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"password": "a whole new password"},
    )
    assert patched.status_code == 200

    replay = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401


async def test_patch_me_email_conflict(client: AsyncClient, unique_email: str) -> None:
    taken = f"taken-{unique_email}"
    await _signup(client, taken)
    tokens = await _signup(client, unique_email)

    resp = await client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"email": taken},
    )
    assert resp.status_code == 409
