"""auth endpoints (§6): signup · login · refresh (rotating) · GET/PATCH /me.

Money-path rules don't touch auth; the invariants here are credential hygiene
(argon2id), server-verified RS256 tokens, rotating refresh tokens, and
ownership (a token only ever reads/writes its own ``sub``).
"""
from __future__ import annotations

import datetime as dt
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_session
from ..deps import get_current_user_id, get_settings, get_signer
from ..models import RefreshToken, User
from ..schemas import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UpdateMeRequest,
    UserProfile,
)
from ..security import (
    DUMMY_PASSWORD_HASH,
    TokenSigner,
    hash_password,
    hash_refresh_token,
    new_id,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _issue_pair(
    session: AsyncSession, signer: TokenSigner, settings: Settings, user_id: uuid.UUID
) -> TokenPair:
    """Mint an access token and a fresh, persisted (hashed) refresh token."""
    raw_refresh = secrets.token_urlsafe(32)
    session.add(
        RefreshToken(
            id=new_id(),
            user_id=user_id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=dt.datetime.now(dt.UTC)
            + dt.timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    return TokenPair(access_token=signer.issue_access(str(user_id)), refresh_token=raw_refresh)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    session: AsyncSession = Depends(get_session),
    signer: TokenSigner = Depends(get_signer),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    user = User(
        id=new_id(),
        email=body.email,
        password_hash=await hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    pair = await _issue_pair(session, signer, settings, user.id)
    await session.commit()
    return pair


@router.post("/login")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
    signer: TokenSigner = Depends(get_signer),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None:
        # spend the same argon2 cost as a real verify to equalize timing (m1)
        await verify_password(DUMMY_PASSWORD_HASH, body.password)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not await verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    pair = await _issue_pair(session, signer, settings, user.id)
    await session.commit()
    return pair


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    signer: TokenSigner = Depends(get_signer),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    token_hash = hash_refresh_token(body.refresh_token)
    now = dt.datetime.now(dt.UTC)
    # Atomic single-use rotation: flip revoked_at NULL→now in one statement.
    # The row lock means exactly one of two concurrent callers (or a replay of
    # an already-spent token) updates a row; the loser matches nothing and is
    # rejected — this is what makes rotation and reuse-detection race-safe (M1).
    revoked = (
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(revoked_at=now)
            .returning(RefreshToken.user_id)
        )
    ).one_or_none()
    if revoked is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    pair = await _issue_pair(session, signer, settings, revoked.user_id)
    await session.commit()
    return pair


@router.get("/me")
async def get_me(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return UserProfile.model_validate(user)


@router.patch("/me")
async def patch_me(
    body: UpdateMeRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if body.email is not None:
        user.email = body.email
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.password is not None:
        user.password_hash = await hash_password(body.password)
        # a credential change invalidates every outstanding session (M2, §9):
        # a stolen refresh token must not survive the password reset.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=dt.datetime.now(dt.UTC))
        )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    await session.commit()
    return UserProfile.model_validate(user)
