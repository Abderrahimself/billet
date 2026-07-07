"""Ownership + token verification (§9, D8). Catalog verifies auth-minted JWTs."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from httpx import AsyncClient

from conftest import api_create_event, bearer, event_payload, tier_payload


async def test_owner_only_mutations(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    owner = bearer(token(organizer_id))
    ev = await api_create_event(client, owner)

    intruder = bearer(token(str(uuid.uuid4())))  # a different, valid subject
    assert (
        await client.patch(
            f"/api/catalog/events/{ev['id']}", headers=intruder, json={"venue_city": "X"}
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/catalog/events/{ev['id']}/publish", headers=intruder)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/catalog/events/{ev['id']}/tiers", headers=intruder, json=tier_payload()
        )
    ).status_code == 403


async def test_missing_bearer_is_401(client: AsyncClient) -> None:
    resp = await client.post("/api/catalog/events", json=event_payload())
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/catalog/events",
        headers={"Authorization": "Bearer not-a-jwt"},
        json=event_payload(),
    )
    assert resp.status_code == 401


async def test_expired_token_is_401(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    resp = await client.post(
        "/api/catalog/events", headers=bearer(token(organizer_id, ttl=-10)), json=event_payload()
    )
    assert resp.status_code == 401


async def test_wrong_issuer_is_401(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    resp = await client.post(
        "/api/catalog/events",
        headers=bearer(token(organizer_id, issuer="evil-issuer")),
        json=event_payload(),
    )
    assert resp.status_code == 401
