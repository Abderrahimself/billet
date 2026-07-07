"""Liveness/readiness (Phase 1 observability L1)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


async def test_healthz_is_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_ok_when_db_reachable(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_503_when_db_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    # point at a dead port so the readiness query fails fast (ECONNREFUSED)
    monkeypatch.setenv("CATALOG_DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1:1/none")

    from catalog.config import get_settings
    from catalog.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/readyz")
    get_settings.cache_clear()

    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
