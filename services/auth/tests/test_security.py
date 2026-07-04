"""Unit-level checks on the security primitives (argon2id, ids, refresh hashing)."""
from __future__ import annotations

from auth.security import (
    hash_password,
    hash_refresh_token,
    new_id,
    verify_password,
)


async def test_argon2_hash_roundtrip() -> None:
    hashed = await hash_password("a strong secret")
    assert hashed.startswith("$argon2id$")  # argon2id variant (§9)
    assert await verify_password(hashed, "a strong secret") is True
    assert await verify_password(hashed, "wrong secret") is False


async def test_verify_password_tolerates_bad_hash() -> None:
    assert await verify_password("not-a-hash", "whatever") is False


def test_new_id_is_uuid_v7() -> None:
    ident = new_id()
    assert ident.version == 7
    # time-ordered: a later id sorts after an earlier one
    assert new_id() > ident


def test_refresh_hash_is_deterministic_and_hex() -> None:
    digest = hash_refresh_token("token-value")
    assert digest == hash_refresh_token("token-value")
    assert len(digest) == 64
    int(digest, 16)  # valid hex
