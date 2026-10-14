"""Persist operator-triggered rescheduling events and their schedule impact.

Revision ID: 0002_dynamic_rescheduling
Revises: 0001_initial_schema
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_dynamic_rescheduling"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disruption_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("parent_schedule_id", sa.String(length=36), sa.ForeignKey("schedule_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revised_schedule_id", sa.String(length=36), sa.ForeignKey("schedule_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("impact", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_disruption_events_parent_schedule_id", "disruption_events", ["parent_schedule_id"])


def downgrade() -> None:
    raise RuntimeError("ForgeIQ schema downgrades are disabled to prevent accidental data loss. Back up and plan an additive migration before changing production schemas.")
