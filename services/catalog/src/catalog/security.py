"""RS256 access-token verification against auth's JWKS (D8).

Catalog is the first service to *verify* an auth-minted token rather than issue
one. It holds no signing key: it fetches auth's public keys from the internal
JWKS endpoint and verifies locally, never calling auth back on the request path.

``PyJWKClient`` fetches the JWK set lazily on first use, caches it, and refetches
when it encounters an unknown ``kid`` — so auth's key rotation is handled without
a restart. The ``verify_access`` options mirror auth's issuer exactly.
"""
from __future__ import annotations

import uuid

import jwt
import uuid_utils
from jwt import PyJWKClient


def new_id() -> uuid.UUID:
    """UUIDv7 (time-ordered) as a stdlib UUID (§5 — all IDs are UUIDv7)."""
    return uuid.UUID(str(uuid_utils.uuid7()))


class TokenVerifier:
    """Verifies access tokens using auth's published JWKS (D8)."""

    def __init__(self, jwks_url: str, issuer: str, *, timeout: int = 5) -> None:
        # timeout bounds a request-path stall if auth is briefly unreachable.
        self._jwks = PyJWKClient(jwks_url, timeout=timeout)
        self.issuer = issuer

    def verify_access(self, token: str) -> dict[str, object]:
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
