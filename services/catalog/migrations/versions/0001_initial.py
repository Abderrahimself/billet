"""initial catalog schema — events + tiers (§5.1)

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Native enum for the event lifecycle (§2.3). Created explicitly so the
    # migration owns it (create_type=False on the column below); the catalog
    # role owns catalog_db and may create the type (D5).
    event_status = postgresql.ENUM("draft", "published", name="event_status")
    event_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("venue_name", sa.String(), nullable=False),
        sa.Column("venue_city", sa.String(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cover_key", sa.String(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("draft", "published", name="event_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("slug", name="uq_events_slug"),
    )
    op.create_index("ix_events_organizer_id", "events", ["organizer_id"])
    op.create_index("ix_events_venue_city", "events", ["venue_city"])
    # supports the public listing query (status = published AND starts_at >= now)
    op.create_index("ix_events_listing", "events", ["status", "starts_at"])

    op.create_table(
        "tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price_cent", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("max_per_order", sa.Integer(), server_default=sa.text("4"), nullable=False),
        sa.Column("sale_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sale_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tiers"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_tiers_event_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint("price_cent >= 0", name="ck_tiers_price_cent_nonneg"),
        sa.CheckConstraint("quantity > 0", name="ck_tiers_quantity_positive"),
        sa.CheckConstraint("max_per_order BETWEEN 1 AND 4", name="ck_tiers_max_per_order"),
        sa.CheckConstraint("sale_ends_at > sale_starts_at", name="ck_tiers_sale_window"),
    )
    op.create_index("ix_tiers_event_id", "tiers", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_tiers_event_id", table_name="tiers")
    op.drop_table("tiers")
    op.drop_index("ix_events_listing", table_name="events")
    op.drop_index("ix_events_venue_city", table_name="events")
    op.drop_index("ix_events_organizer_id", table_name="events")
    op.drop_table("events")
    postgresql.ENUM(name="event_status").drop(op.get_bind(), checkfirst=True)
