"""Tier endpoints (§6 catalog). Tier CRUD is allowed only while the event is a
draft; once published the tiers are frozen (quantity immutable after publish,
MVP — extended here to the whole tier to avoid inventory desync with booking)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_organizer_id
from ..models import DRAFT, Tier
from ..schemas import TierCreate, TierOut, TierUpdate
from ..security import new_id
from ..service import get_owned_event, get_tier_of_event

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

_DRAFT_ONLY = "tiers can only be modified while the event is a draft"


async def _draft_event(
    session: AsyncSession, event_id: uuid.UUID, organizer_id: uuid.UUID
) -> None:
    event = await get_owned_event(session, event_id, organizer_id)
    if event.status != DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, _DRAFT_ONLY)


@router.post(
    "/events/{event_id}/tiers", response_model=TierOut, status_code=status.HTTP_201_CREATED
)
async def post_tier(
    event_id: uuid.UUID,
    body: TierCreate,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Tier:
    await _draft_event(session, event_id, organizer_id)
    tier = Tier(
        id=new_id(),
        event_id=event_id,
        name=body.name,
        price_cent=body.price_cent,
        quantity=body.quantity,
        max_per_order=body.max_per_order,
        sale_starts_at=body.sale_starts_at,
        sale_ends_at=body.sale_ends_at,
    )
    session.add(tier)
    await session.commit()
    await session.refresh(tier)
    return tier


@router.patch("/events/{event_id}/tiers/{tier_id}", response_model=TierOut)
async def patch_tier(
    event_id: uuid.UUID,
    tier_id: uuid.UUID,
    body: TierUpdate,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Tier:
    await _draft_event(session, event_id, organizer_id)
    tier = await get_tier_of_event(session, event_id, tier_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tier, field, value)
    if tier.sale_ends_at <= tier.sale_starts_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "sale_ends_at must be after sale_starts_at"
        )
    await session.commit()
    await session.refresh(tier)
    return tier


@router.delete("/events/{event_id}/tiers/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tier(
    event_id: uuid.UUID,
    tier_id: uuid.UUID,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _draft_event(session, event_id, organizer_id)
    tier = await get_tier_of_event(session, event_id, tier_id)
    await session.delete(tier)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
