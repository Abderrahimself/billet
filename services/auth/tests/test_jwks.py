"""JWKS lets a verifier validate an access token with no call back to auth (D8)."""
from __future__ import annotations

import json

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from httpx import AsyncClient
from jwt.algorithms import RSAAlgorithm

PASSWORD = "correct horse battery"


async def test_jwks_public_key_verifies_access_token(
    client: AsyncClient, unique_email: str
) -> None:
    signup = await client.post(
        "/api/auth/signup",
        json={"email": unique_email, "password": PASSWORD, "display_name": "JWKS"},
    )
    access_token = signup.json()["access_token"]

    jwks = (await client.get("/.well-known/jwks.json")).json()
    assert jwks["keys"], "JWKS must publish at least one key"
    key = jwks["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert key["kid"] == "test-1"

    # header kid must point at the published key
    header = jwt.get_unverified_header(access_token)
    assert header["kid"] == key["kid"]

    public_key = RSAAlgorithm.from_jwk(json.dumps(key))
    assert isinstance(public_key, RSAPublicKey)
    claims = jwt.decode(access_token, public_key, algorithms=["RS256"], issuer="billet-auth")
    assert claims["sub"]
    assert claims["iss"] == "billet-auth"
    assert claims["exp"] > claims["iat"]


async def test_jwks_does_not_expose_private_material(client: AsyncClient) -> None:
    key = (await client.get("/.well-known/jwks.json")).json()["keys"][0]
    # private RSA JWK fields must never be present
    for private_field in ("d", "p", "q", "dp", "dq", "qi"):
        assert private_field not in key
