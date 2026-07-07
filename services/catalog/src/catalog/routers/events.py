"""Event endpoints (§6 catalog). Public reads + owner-only writes (§9 authz)."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..deps import get_current_organizer_id
from ..models import PUBLISHED, Event
from ..schemas import EventCreate, EventDetail, EventOut, EventPublic, EventUpdate
from ..service import create_event, get_owned_event

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/events", response_model=list[EventPublic])
async def list_events(
    city: str | None = None,
    from_: dt.datetime | None = Query(default=None, alias="from"),
    session: AsyncSession = Depends(get_session),
) -> list[Event]:
    """Published, upcoming events (screen 1). Never draft; no availability (rule 1)."""
    threshold = from_ or dt.datetime.now(dt.UTC)
    stmt = select(Event).where(Event.status == PUBLISHED, Event.starts_at >= threshold)
    if city:
        stmt = stmt.where(func.lower(Event.venue_city) == city.lower())
    stmt = stmt.order_by(Event.starts_at)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/events/{slug}", response_model=EventDetail)
async def get_event(slug: str, session: AsyncSession = Depends(get_session)) -> Event:
    """Public detail by slug (screen 2). Tier definitions included; draft → 404."""
    event = (
        await session.execute(
            select(Event)
            .where(Event.slug == slug, Event.status == PUBLISHED)
            .options(selectinload(Event.tiers))
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def post_event(
    body: EventCreate,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Event:
    """Create a draft. The organizer is the authenticated subject (§6)."""
    return await create_event(session, organizer_id=organizer_id, data=body)


@router.patch("/events/{event_id}", response_model=EventOut)
async def patch_event(
    event_id: uuid.UUID,
    body: EventUpdate,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Event:
    """Owner-only event edit. slug/status/organizer_id are immutable here."""
    event = await get_owned_event(session, event_id, organizer_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    await session.commit()
    await session.refresh(event)
    return event


@router.post("/events/{event_id}/publish", response_model=EventOut)
async def publish_event(
    event_id: uuid.UUID,
    organizer_id: uuid.UUID = Depends(get_current_organizer_id),
    session: AsyncSession = Depends(get_session),
) -> Event:
    """draft → published (§2.3). Requires at least one tier — nothing to sell otherwise."""
    event = await get_owned_event(session, event_id, organizer_id, load_tiers=True)
    if event.status == PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "event already published")
    if not event.tiers:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot publish an event with no tiers")
    event.status = PUBLISHED
    await session.commit()
    await session.refresh(event)
    return event
