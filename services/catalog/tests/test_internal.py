"""GET /internal/tiers/{id} — booking's read path (§6, D3). No auth: the network
boundary is the control, and the gateway never routes /internal (§3.2 r2)."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from httpx import AsyncClient

from conftest import api_add_tier, api_create_event, api_publish, bearer


async def test_internal_tier_returns_the_definition(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    tier = await api_add_tier(
        client, headers, ev["id"], price_cent=25000, quantity=200, max_per_order=3
    )

    resp = await client.get(f"/internal/tiers/{tier['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event_id"] == ev["id"]
    assert data["price_cent"] == 25000
    assert data["quantity"] == 200
    assert data["max_per_order"] == 3
    assert data["currency"] == "MAD"
    assert data["event_status"] == "draft"


async def test_internal_tier_reflects_publish(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    tier = await api_add_tier(client, headers, ev["id"])
    await api_publish(client, headers, ev["id"])

    data = (await client.get(f"/internal/tiers/{tier['id']}")).json()
    assert data["event_status"] == "published"


async def test_internal_tier_unknown_id_is_404(client: AsyncClient) -> None:
    resp = await client.get(f"/internal/tiers/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_internal_tier_needs_no_auth(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    tier = await api_add_tier(client, headers, ev["id"])

    resp = await client.get(f"/internal/tiers/{tier['id']}")  # deliberately no bearer
    assert resp.status_code == 200
