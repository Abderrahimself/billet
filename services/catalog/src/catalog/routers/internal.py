"""Internal API (D3, §3.2 rule 2). Never routed by the gateway — reachable only
on the compose network. Booking reads a tier's price/quantity/sale-window here to
size a hold and snapshot the price at checkout (§6, D9). No auth: the network
boundary is the control, exactly like auth's JWKS endpoint.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..models import Tier
from ..schemas import InternalTier

router = APIRouter(tags=["internal"])


@router.get("/internal/tiers/{tier_id}", response_model=InternalTier)
async def get_internal_tier(
    tier_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> InternalTier:
    tier = (
        await session.execute(
            select(Tier).where(Tier.id == tier_id).options(selectinload(Tier.event))
        )
    ).scalar_one_or_none()
    if tier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tier not found")
    return InternalTier(
        id=tier.id,
        event_id=tier.event_id,
        price_cent=tier.price_cent,
        quantity=tier.quantity,
        max_per_order=tier.max_per_order,
        sale_starts_at=tier.sale_starts_at,
        sale_ends_at=tier.sale_ends_at,
        event_status=tier.event.status,
    )
