"""Shared FastAPI dependencies: settings, signer, and Bearer authn (§9 authz)."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request

from .config import Settings
from .security import TokenSigner

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_signer(request: Request) -> TokenSigner:
    return request.app.state.signer


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    signer: TokenSigner = Depends(get_signer),
) -> str:
    unauthorized = {"WWW-Authenticate": "Bearer"}  # RFC 6750
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers=unauthorized
        )
    try:
        payload = signer.verify_access(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid token", headers=unauthorized
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid token subject", headers=unauthorized
        )
    return subject
