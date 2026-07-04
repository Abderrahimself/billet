"""FastAPI application factory (D8, §3.1 auth on :8001)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .config import get_settings
from .db import make_engine, make_sessionmaker
from .logging import RequestIDMiddleware, configure_logging
from .routers import auth, health, jwks
from .security import TokenSigner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.signer = TokenSigner(
        Path(settings.jwt_private_key_path).read_bytes(),
        kid=settings.jwt_kid,
        issuer=settings.jwt_issuer,
        access_ttl=settings.access_token_ttl_seconds,
    )
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="billet auth", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(jwks.router)
    app.include_router(auth.router)
    return app


app = create_app()
