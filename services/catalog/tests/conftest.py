"""Test harness: a real Postgres via testcontainers (O6), migrations applied
through Alembic, and an httpx client running the app's real lifespan.

JWT verification is exercised hermetically: an ephemeral RS256 keypair mints
tokens the way auth would, and the app's verifier dependency is overridden with
one that validates against that key's public half — so the real ``jwt.decode``
path runs without needing an auth container.
"""
from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import jwt
import psycopg2
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

SERVICE_ROOT = Path(__file__).resolve().parents[1]
ISSUER = "billet-auth"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # Provision a NON-superuser role that owns its own database, mirroring
    # deploy/compose/postgres/init/00-init-databases.sh — so the migration's
    # CREATE TYPE / CREATE TABLE run under least privilege, as they do in
    # compose (D5). The container's default role is a superuser and would
    # prove nothing.
    with PostgresContainer(
        "postgres:16.9-alpine", username="super", password="superpw", dbname="postgres"
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)

        admin = psycopg2.connect(
            host=host, port=port, user="super", password="superpw", dbname="postgres"
        )
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(
                "CREATE ROLE catalog LOGIN PASSWORD 'catalogpw' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
            cur.execute("CREATE DATABASE catalog_db OWNER catalog")
            cur.execute("REVOKE ALL ON DATABASE catalog_db FROM PUBLIC")
            cur.execute("GRANT CONNECT ON DATABASE catalog_db TO catalog")
        admin.close()

        owner = psycopg2.connect(
            host=host, port=port, user="super", password="superpw", dbname="catalog_db"
        )
        owner.autocommit = True
        with owner.cursor() as cur:
            cur.execute("ALTER SCHEMA public OWNER TO catalog")
        owner.close()

        yield f"postgresql+asyncpg://catalog:catalogpw@{host}:{port}/catalog_db"


@pytest.fixture(scope="session")
def signing_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session", autouse=True)
def _environment(postgres_url: str) -> None:
    import os

    os.environ["CATALOG_DATABASE_URL"] = postgres_url
    os.environ["CATALOG_AUTH_ISSUER"] = ISSUER

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    command.upgrade(cfg, "head")


class _StubVerifier:
    """Same verification as catalog.security.TokenVerifier, minus the JWKS fetch."""

    def __init__(self, public_key: Any, issuer: str) -> None:
        self._public_key = public_key
        self.issuer = issuer

    def verify_access(self, token: str) -> dict[str, object]:
        return jwt.decode(
            token,
            self._public_key,
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )


@pytest_asyncio.fixture
async def client(signing_key: RSAPrivateKey) -> AsyncIterator[AsyncClient]:
    from catalog.config import get_settings
    from catalog.deps import get_verifier
    from catalog.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_verifier] = lambda: _StubVerifier(
        signing_key.public_key(), ISSUER
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def token(signing_key: RSAPrivateKey) -> Callable[..., str]:
    """Mint an access token the way auth would (RS256, iss=billet-auth)."""

    def _make(
        sub: str, *, issuer: str = ISSUER, ttl: int = 900, kid: str = "test-1"
    ) -> str:
        now = int(time.time())
        payload = {"sub": sub, "iat": now, "exp": now + ttl, "iss": issuer}
        return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": kid})

    return _make


@pytest.fixture
def organizer_id() -> str:
    return str(uuid.uuid4())


def future(days: int) -> str:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=days)).isoformat()


def event_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Jazz au Studio des Arts",
        "description": "Une soirée jazz au cœur de Casablanca.",
        "venue_name": "Studio des Arts",
        "venue_city": "Casablanca",
        "starts_at": future(30),
    }
    base.update(overrides)
    return base


def tier_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Standard",
        "price_cent": 15000,  # 150.00 MAD (centimes, D9)
        "quantity": 100,
        "max_per_order": 4,
        "sale_starts_at": future(1),
        "sale_ends_at": future(29),
    }
    base.update(overrides)
    return base


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def api_create_event(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    resp = await client.post(
        "/api/catalog/events", headers=headers, json=event_payload(**overrides)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def api_add_tier(
    client: AsyncClient, headers: dict[str, str], event_id: str, **overrides: Any
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/catalog/events/{event_id}/tiers", headers=headers, json=tier_payload(**overrides)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def api_publish(client: AsyncClient, headers: dict[str, str], event_id: str) -> Any:
    return await client.post(f"/api/catalog/events/{event_id}/publish", headers=headers)
