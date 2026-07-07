"""Shared FastAPI dependencies: settings, token verifier, Bearer authn (§9).

Ownership authorization (`organizer_id == sub`) lives in the service layer; here
we only resolve the authenticated subject from a verified access token.
"""
from __future__ import annotations

import uuid

import jwt
from anyio import to_thread
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request

from .config import Settings
from .security import TokenVerifier

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}  # RFC 6750


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_verifier(request: Request) -> TokenVerifier:
    return request.app.state.verifier


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    verifier: TokenVerifier = Depends(get_verifier),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers=_UNAUTHORIZED
        )
    try:
        # verification does a (cached) JWKS fetch on the first/rotated key — run
        # it off the event loop so a burst of requests never blocks the loop.
        payload = await to_thread.run_sync(verifier.verify_access, credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid token", headers=_UNAUTHORIZED
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid token subject", headers=_UNAUTHORIZED
        )
    return subject


async def get_current_organizer_id(user_id: str = Depends(get_current_user_id)) -> uuid.UUID:
    """The subject is an auth user id (UUIDv7). Ownership rows store it as a UUID."""
    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid token subject", headers=_UNAUTHORIZED
        ) from exc
