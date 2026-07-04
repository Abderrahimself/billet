"""JWKS endpoint (D8). Internal network only — the gateway never routes
``/.well-known/*`` (§3.2 rule 2), so this is not under the ``/api`` prefix.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_signer
from ..security import TokenSigner

router = APIRouter(tags=["internal"])


@router.get("/.well-known/jwks.json")
async def jwks(signer: TokenSigner = Depends(get_signer)) -> dict[str, list[dict[str, Any]]]:
    return {"keys": [signer.public_jwk()]}
