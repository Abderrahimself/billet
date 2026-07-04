"""Test harness: a real Postgres via testcontainers (O6), an ephemeral RS256
key, migrations applied through Alembic, and an httpx client that runs the app's
real lifespan (engine + signer wiring)."""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg2
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

SERVICE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # Provision a NON-superuser role that owns its own database, mirroring
    # deploy/compose/postgres/init/00-init-databases.sh. This is what makes the
    # migration's `CREATE EXTENSION citext` a real test of the least-privilege
    # owner path (a trusted extension installed by a non-superuser DB owner) —
    # the container's default role is a superuser and would prove nothing (m2, D5).
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
                "CREATE ROLE auth LOGIN PASSWORD 'authpw' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
            cur.execute("CREATE DATABASE auth_db OWNER auth")
            cur.execute("REVOKE ALL ON DATABASE auth_db FROM PUBLIC")
            cur.execute("GRANT CONNECT ON DATABASE auth_db TO auth")
        admin.close()

        owner = psycopg2.connect(
            host=host, port=port, user="super", password="superpw", dbname="auth_db"
        )
        owner.autocommit = True
        with owner.cursor() as cur:
            cur.execute("ALTER SCHEMA public OWNER TO auth")
        owner.close()

        yield f"postgresql+asyncpg://auth:authpw@{host}:{port}/auth_db"


@pytest.fixture(scope="session")
def signing_key_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path_factory.mktemp("keys") / "jwt_test.pem"
    path.write_bytes(pem)
    return path


@pytest.fixture(scope="session", autouse=True)
def _environment(postgres_url: str, signing_key_path: Path) -> None:
    os.environ["AUTH_DATABASE_URL"] = postgres_url
    os.environ["AUTH_JWT_PRIVATE_KEY_PATH"] = str(signing_key_path)
    os.environ["AUTH_JWT_KID"] = "test-1"
    os.environ["AUTH_JWT_ISSUER"] = "billet-auth"
    os.environ["AUTH_ACCESS_TOKEN_TTL_SECONDS"] = "900"
    os.environ["AUTH_REFRESH_TOKEN_TTL_SECONDS"] = "3600"

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def make_client(app: object) -> AsyncIterator[AsyncClient]:
    # run the real lifespan so app.state.{engine,sessionmaker,signer} are set
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from auth.config import get_settings
    from auth.main import create_app

    get_settings.cache_clear()
    async with make_client(create_app()) as c:
        yield c


@pytest.fixture
def unique_email() -> str:
    # example.com is accepted by EmailStr; reserved TLDs (.test/.local) are not
    return f"user-{uuid.uuid4().hex[:12]}@example.com"
