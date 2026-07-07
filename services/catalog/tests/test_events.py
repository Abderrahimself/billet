"""Event lifecycle + public reads (§6, §2.3)."""
from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from conftest import api_add_tier, api_create_event, api_publish, bearer, event_payload, future


async def test_create_returns_a_draft(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    body = await api_create_event(client, bearer(token(organizer_id)))
    assert body["status"] == "draft"
    assert body["organizer_id"] == organizer_id
    assert body["slug"]
    assert body["title"] == "Jazz au Studio des Arts"


async def test_create_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/catalog/events", json=event_payload())
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_slug_is_unique_for_same_title(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    a = await api_create_event(client, headers, title="Same Title Show")
    b = await api_create_event(client, headers, title="Same Title Show")
    assert a["slug"] != b["slug"]


async def test_listing_shows_only_published(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    draft = await api_create_event(client, headers, title="Hidden Until Published")

    listed = (await client.get("/api/catalog/events")).json()
    assert draft["slug"] not in {e["slug"] for e in listed}

    await api_add_tier(client, headers, draft["id"])
    assert (await api_publish(client, headers, draft["id"])).status_code == 200

    listed = (await client.get("/api/catalog/events")).json()
    assert draft["slug"] in {e["slug"] for e in listed}


async def test_public_reads_do_not_leak_organizer_id(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)
    await api_add_tier(client, headers, ev["id"])
    await api_publish(client, headers, ev["id"])

    listed = (await client.get("/api/catalog/events")).json()
    assert all("organizer_id" not in e for e in listed)

    detail = (await client.get(f"/api/catalog/events/{ev['slug']}")).json()
    assert "organizer_id" not in detail


async def test_detail_by_slug_includes_tiers(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)

    # a draft is not publicly visible
    assert (await client.get(f"/api/catalog/events/{ev['slug']}")).status_code == 404

    await api_add_tier(client, headers, ev["id"])
    await api_publish(client, headers, ev["id"])

    detail = await client.get(f"/api/catalog/events/{ev['slug']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["slug"] == ev["slug"]
    assert len(data["tiers"]) == 1
    assert data["tiers"][0]["price_cent"] == 15000  # centimes (D9)
    assert data["tiers"][0]["currency"] == "MAD"


async def test_publish_requires_a_tier_and_is_once(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)

    assert (await api_publish(client, headers, ev["id"])).status_code == 409  # no tiers

    await api_add_tier(client, headers, ev["id"])
    assert (await api_publish(client, headers, ev["id"])).status_code == 200
    assert (await api_publish(client, headers, ev["id"])).status_code == 409  # already published


async def test_patch_event_edits_fields_but_not_slug(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers)

    resp = await client.patch(
        f"/api/catalog/events/{ev['id']}",
        headers=headers,
        json={"venue_city": "Rabat", "description": "Nouvelle description."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["venue_city"] == "Rabat"
    assert body["description"] == "Nouvelle description."
    assert body["slug"] == ev["slug"]  # slug is immutable


async def test_listing_city_filter_is_case_insensitive(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers, venue_city="Marrakech", title="Marrakech Nights")
    await api_add_tier(client, headers, ev["id"])
    await api_publish(client, headers, ev["id"])

    matched = (await client.get("/api/catalog/events", params={"city": "marrakech"})).json()
    assert any(e["slug"] == ev["slug"] for e in matched)

    other = (await client.get("/api/catalog/events", params={"city": "Tanger"})).json()
    assert all(e["slug"] != ev["slug"] for e in other)


async def test_listing_from_filter_excludes_earlier_events(
    client: AsyncClient, token: Callable[..., str], organizer_id: str
) -> None:
    headers = bearer(token(organizer_id))
    ev = await api_create_event(client, headers, starts_at=future(10), title="Ten Days Out")
    await api_add_tier(client, headers, ev["id"])
    await api_publish(client, headers, ev["id"])

    later = (await client.get("/api/catalog/events", params={"from": future(20)})).json()
    assert all(e["slug"] != ev["slug"] for e in later)
