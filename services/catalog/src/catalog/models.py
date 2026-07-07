"""SQLAlchemy 2 models — catalog_db only (D5). Schema mirrors mvp.md §5.1.

Money is integer centimes (D9). ``organizer_id`` is a plain UUID reference to an
auth user — never a cross-database foreign key (§5 note, D5). ``status`` is a
native Postgres enum but maps to plain Python strings to keep the app layer free
of enum/serialization friction; the DB still enforces the domain.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DRAFT = "draft"
PUBLISHED = "published"
EVENT_STATUSES = (DRAFT, PUBLISHED)


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    venue_name: Mapped[str] = mapped_column(String, nullable=False)
    venue_city: Mapped[str] = mapped_column(String, nullable=False, index=True)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cover_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(*EVENT_STATUSES, name="event_status", create_type=False),
        server_default=DRAFT,
        nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=_utcnow, nullable=False
    )

    tiers: Mapped[list[Tier]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Tier.price_cent",
        passive_deletes=True,
    )


class Tier(Base):
    __tablename__ = "tiers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    price_cent: Mapped[int] = mapped_column(Integer, nullable=False)  # centimes, MAD (D9)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    max_per_order: Mapped[int] = mapped_column(Integer, server_default=text("4"), nullable=False)
    sale_starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sale_ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    event: Mapped[Event] = relationship(back_populates="tiers")

    __table_args__ = (
        CheckConstraint("price_cent >= 0", name="ck_tiers_price_cent_nonneg"),
        CheckConstraint("quantity > 0", name="ck_tiers_quantity_positive"),
        CheckConstraint("max_per_order BETWEEN 1 AND 4", name="ck_tiers_max_per_order"),  # D15
        CheckConstraint("sale_ends_at > sale_starts_at", name="ck_tiers_sale_window"),
    )
