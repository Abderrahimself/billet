"""Liveness and readiness (Phase 1 observability L1).

``/healthz`` is a pure liveness signal; ``/readyz`` proves this instance can
reach its own database. Reachability of auth's JWKS is deliberately *not* part of
readiness — it is an upstream dependency, not catalog's own datastore (§9).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — any DB error means not ready
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}
