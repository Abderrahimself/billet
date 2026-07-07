"""Pydantic request/response contracts (§6 catalog). Validation lives here (§9).

Availability (`quantity − sold − holds`) is never modelled here — it is booking's
truth, computed live (rule 1, D5). Catalog exposes tier *definitions* only.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENCY = "MAD"  # D9 — single currency for the MVP


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    venue_name: str = Field(min_length=1, max_length=200)
    venue_city: str = Field(min_length=1, max_length=100)
    starts_at: dt.datetime
    cover_key: str | None = Field(default=None, max_length=500)


class EventUpdate(BaseModel):
    # every field optional; only those explicitly provided are applied
    # (model_dump(exclude_unset=True)), so `cover_key: null` clears it.
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    venue_name: str | None = Field(default=None, min_length=1, max_length=200)
    venue_city: str | None = Field(default=None, min_length=1, max_length=100)
    starts_at: dt.datetime | None = None
    cover_key: str | None = Field(default=None, max_length=500)


_PRICE_CENT_MAX = 2_147_483_647  # int4 column ceiling — reject before asyncpg does (→ 422 not 500)
_QUANTITY_MAX = 1_000_000  # a sane inventory cap, also well inside int4


class TierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_cent: int = Field(ge=0, le=_PRICE_CENT_MAX)  # centimes (D9)
    quantity: int = Field(gt=0, le=_QUANTITY_MAX)
    max_per_order: int = Field(default=4, ge=1, le=4)  # D15
    sale_starts_at: dt.datetime
    sale_ends_at: dt.datetime

    @model_validator(mode="after")
    def _check_window(self) -> TierCreate:
        if self.sale_ends_at <= self.sale_starts_at:
            raise ValueError("sale_ends_at must be after sale_starts_at")
        return self


class TierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_cent: int | None = Field(default=None, ge=0, le=_PRICE_CENT_MAX)
    quantity: int | None = Field(default=None, gt=0, le=_QUANTITY_MAX)
    max_per_order: int | None = Field(default=None, ge=1, le=4)
    sale_starts_at: dt.datetime | None = None
    sale_ends_at: dt.datetime | None = None


class TierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    price_cent: int
    currency: str = CURRENCY
    quantity: int
    max_per_order: int
    sale_starts_at: dt.datetime
    sale_ends_at: dt.datetime


class EventPublic(BaseModel):
    """Public projection (screens 1–2). The organizer's internal auth user id is
    deliberately omitted — anonymous callers must not learn it (§9 privacy)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    description: str
    venue_name: str
    venue_city: str
    starts_at: dt.datetime
    cover_key: str | None
    status: Literal["draft", "published"]
    created_at: dt.datetime
    updated_at: dt.datetime


class EventOut(EventPublic):
    """Owner-facing projection (create/patch/publish) — includes organizer_id,
    which is the caller's own id."""

    organizer_id: uuid.UUID


class EventDetail(EventPublic):
    """Public event detail with tier definitions (screen 2)."""

    tiers: list[TierOut]


class InternalTier(BaseModel):
    """`GET /internal/tiers/{id}` — what booking reads (price/quantity/window)."""

    id: uuid.UUID
    event_id: uuid.UUID
    price_cent: int
    currency: str = CURRENCY
    quantity: int
    max_per_order: int
    sale_starts_at: dt.datetime
    sale_ends_at: dt.datetime
    event_status: Literal["draft", "published"]
