"""Password hashing (argon2id) and RS256 JWT issuance/verification + JWKS (D8, §9).

Argon2 is CPU-bound; hashing/verification run in a worker thread so a burst of
logins can never block the event loop.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

import jwt
import uuid_utils
from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from jwt.algorithms import RSAAlgorithm

_ph = PasswordHasher()

# A fixed argon2id hash to verify against when an email is unknown, so a failed
# login spends the same CPU whether or not the account exists — closes the
# timing side-channel that would otherwise enumerate registered emails (m1, §9).
DUMMY_PASSWORD_HASH = _ph.hash("timing-equalizer-not-a-real-secret")


def new_id() -> uuid.UUID:
    """UUIDv7 (time-ordered) as a stdlib UUID (§5 — all IDs are UUIDv7)."""
    return uuid.UUID(str(uuid_utils.uuid7()))


def _hash(password: str) -> str:
    return _ph.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    return await to_thread.run_sync(_verify, password_hash, password)


def hash_refresh_token(raw: str) -> str:
    """Refresh tokens are high-entropy random; a fast digest is sufficient."""
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenSigner:
    """Signs access tokens with the private key; publishes the public JWK."""

    def __init__(self, private_pem: bytes, *, kid: str, issuer: str, access_ttl: int) -> None:
        key = serialization.load_pem_private_key(private_pem, password=None)
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("signing key must be RSA (RS256)")
        self._private_key: RSAPrivateKey = key
        self._public_key: RSAPublicKey = key.public_key()
        self.kid = kid
        self.issuer = issuer
        self.access_ttl = access_ttl

    def issue_access(self, subject: str) -> str:
        now = int(time.time())
        payload = {"sub": subject, "iat": now, "exp": now + self.access_ttl, "iss": self.issuer}
        return jwt.encode(payload, self._private_key, algorithm="RS256", headers={"kid": self.kid})

    def verify_access(self, token: str) -> dict[str, object]:
        return jwt.decode(
            token,
            self._public_key,
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )

    def public_jwk(self) -> dict[str, Any]:
        # to_jwk emits kty/n/e (and key_ops as a list); we tag it for discovery.
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self._public_key))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return jwk
