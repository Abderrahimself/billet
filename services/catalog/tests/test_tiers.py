"""Tier CRUD while draft; frozen after publish; validation (§6, §9, D15)."""
from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from conftest import api_add_tier, api_create_event, api_publish, bearer, future, tier_payload


async def test_tier_crud_while_draft(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)

    tier = await api_add_tier(client, headers, ev["id"], name="VIP", price_cent=50000)
    assert tier["name"] == "VIP"

    patched = await client.patch(
        f"/api/catalog/events/{ev['id']}/tiers/{tier['id']}",
        headers=headers,
        json={"price_cent": 60000, "quantity": 50},
    )
    assert patched.status_code == 200
    assert patched.json()["price_cent"] == 60000
    assert patched.json()["quantity"] == 50

    deleted = await client.delete(
        f"/api/catalog/events/{ev['id']}/tiers/{tier['id']}", headers=headers
    )
    assert deleted.status_code == 204


async def test_tiers_are_frozen_after_publish(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    tier = await api_add_tier(client, headers, ev["id"])
    assert (await api_publish(client, headers, ev["id"])).status_code == 200

    add = await client.post(
        f"/api/catalog/events/{ev['id']}/tiers", headers=headers, json=tier_payload(name="Late")
    )
    assert add.status_code == 409

    patch = await client.patch(
        f"/api/catalog/events/{ev['id']}/tiers/{tier['id']}",
        headers=headers,
        json={"price_cent": 1},
    )
    assert patch.status_code == 409

    delete = await client.delete(
        f"/api/catalog/events/{ev['id']}/tiers/{tier['id']}", headers=headers
    )
    assert delete.status_code == 409


async def test_tier_field_validation(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    url = f"/api/catalog/events/{ev['id']}/tiers"

    async def post(**overrides: object) -> int:
        resp = await client.post(url, headers=headers, json=tier_payload(**overrides))
        return resp.status_code

    assert await post(price_cent=-1) == 422
    assert await post(quantity=0) == 422
    assert await post(max_per_order=5) == 422  # D15
    assert await post(sale_starts_at=future(29), sale_ends_at=future(1)) == 422
    # values past the int4 column ceiling must be rejected as 422, not blow up to 500
    assert await post(quantity=10**12) == 422
    assert await post(price_cent=10**12) == 422


async def test_patch_tier_rejects_inverted_window(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    tier = await api_add_tier(client, headers, ev["id"])

    resp = await client.patch(
        f"/api/catalog/events/{ev['id']}/tiers/{tier['id']}",
        headers=headers,
        json={"sale_ends_at": future(-1)},  # before sale_starts_at
    )
    assert resp.status_code == 422


async def test_tier_must_belong_to_the_event_in_the_path(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev1 = await api_create_event(client, headers, title="Event One")
    ev2 = await api_create_event(client, headers, title="Event Two")
    tier = await api_add_tier(client, headers, ev1["id"])

    resp = await client.patch(
        f"/api/catalog/events/{ev2['id']}/tiers/{tier['id']}",
        headers=headers,
        json={"price_cent": 1},
    )
    assert resp.status_code == 404
