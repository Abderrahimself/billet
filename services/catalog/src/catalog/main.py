"""FastAPI application factory (D1, §3.1 catalog on :8002)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import make_engine, make_sessionmaker
from .logging import RequestIDMiddleware, configure_logging
from .routers import events, health, internal, tiers
from .security import TokenVerifier


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    # verifies auth-minted access tokens against auth's JWKS (D8); lazy fetch.
    app.state.verifier = TokenVerifier(settings.auth_jwks_url, settings.auth_issuer)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="billet catalog", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(internal.router)
    app.include_router(events.router)
    app.include_router(tiers.router)
    return app


app = create_app()
