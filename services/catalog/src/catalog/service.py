"""Domain logic between the routers and the DB (§6 behaviour, §2.3 lifecycle).

Ownership authorization (`organizer_id == sub`, §6) and the draft/publish gates
live here so the routers stay thin.
"""
from __future__ import annotations

import secrets
import uuid

from fastapi import HTTPException, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import DRAFT, Event, Tier
from .schemas import EventCreate
from .security import new_id

_SLUG_ATTEMPTS = 5


def make_slug(title: str) -> str:
    """A URL slug from the title plus a short random tail.

    The tail makes the slug unique in a single insert (no check-then-insert
    race) and keeps non-Latin titles (Arabic) usable — slugify transliterates
    French and falls back to ``event`` when it would otherwise be empty. The
    UNIQUE column remains the ultimate guard (see ``create_event``).
    """
    base = slugify(title, max_length=80, word_boundary=True) or "event"
    return f"{base}-{secrets.token_hex(4)}"


async def create_event(
    session: AsyncSession, *, organizer_id: uuid.UUID, data: EventCreate
) -> Event:
    for _ in range(_SLUG_ATTEMPTS):
        event = Event(
            id=new_id(),
            organizer_id=organizer_id,
            title=data.title,
            slug=make_slug(data.title),
            description=data.description,
            venue_name=data.venue_name,
            venue_city=data.venue_city,
            starts_at=data.starts_at,
            cover_key=data.cover_key,
            status=DRAFT,
        )
        session.add(event)
        try:
            await session.flush()
        except IntegrityError:  # astronomically rare slug collision — try a fresh tail
            await session.rollback()
            continue
        await session.commit()
        await session.refresh(event)
        return event
    raise HTTPException(status.HTTP_409_CONFLICT, "could not generate a unique slug")


async def get_owned_event(
    session: AsyncSession,
    event_id: uuid.UUID,
    organizer_id: uuid.UUID,
    *,
    load_tiers: bool = False,
) -> Event:
    """Fetch an event and enforce ownership: 404 if absent, 403 if not the owner."""
    stmt = select(Event).where(Event.id == event_id)
    if load_tiers:
        stmt = stmt.options(selectinload(Event.tiers))
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    if event.organizer_id != organizer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the event owner")
    return event


async def get_tier_of_event(
    session: AsyncSession, event_id: uuid.UUID, tier_id: uuid.UUID
) -> Tier:
    tier = (
        await session.execute(
            select(Tier).where(Tier.id == tier_id, Tier.event_id == event_id)
        )
    ).scalar_one_or_none()
    if tier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tier not found")
    return tier
