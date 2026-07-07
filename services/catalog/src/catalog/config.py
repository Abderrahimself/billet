"""Runtime configuration (pydantic-settings, Phase 1 config item).

Every value is env-driven with the ``CATALOG_`` prefix; compose supplies them.
The DB password lives only inside the DSN (assembled in compose from
``CATALOG_DB_PASSWORD``), never in code (O5). Catalog holds no signing key of its
own — it verifies auth-minted tokens against auth's JWKS (D8).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CATALOG_", extra="ignore")

    # postgresql+asyncpg://catalog:<pw>@postgres:5432/catalog_db  (D5 — catalog_db only)
    database_url: str

    # auth's public keys, fetched over the internal network and cached (D8, §3.2 r2).
    auth_jwks_url: str = "http://auth:8001/.well-known/jwks.json"
    auth_issuer: str = "billet-auth"

    # NB: the service always binds container port 8002 (see docker-entrypoint.sh);
    # CATALOG_PORT in compose varies only the host-published port, not this bind.
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment (CATALOG_* / .env)
