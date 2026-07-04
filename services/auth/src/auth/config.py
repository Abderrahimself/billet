"""Runtime configuration (pydantic-settings, Phase 1 config item).

Every value is env-driven with the ``AUTH_`` prefix; compose supplies them.
Secrets (DB password inside the DSN, the signing key) never live in code (O5).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", extra="ignore")

    # postgresql+asyncpg://auth:<pw>@postgres:5432/auth_db  (D5 — auth_db only)
    database_url: str

    # RS256 signing (D8). The private key is a mounted PEM, never baked in (O5).
    jwt_private_key_path: str = "/run/secrets/jwt_dev.pem"
    jwt_kid: str = "dev-1"
    jwt_issuer: str = "billet-auth"
    access_token_ttl_seconds: int = 900        # 15 min (§4)
    refresh_token_ttl_seconds: int = 2_592_000  # 30 d (§4)

    # NB: the service always binds container port 8001 (see docker-entrypoint.sh);
    # AUTH_PORT in compose varies only the host-published port, not this bind.
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment (AUTH_* / .env)
