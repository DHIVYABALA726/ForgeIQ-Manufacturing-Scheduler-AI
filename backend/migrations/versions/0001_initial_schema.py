"""Initial ForgeIQ application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-13
"""
from __future__ import annotations
from alembic import op
from app import models  # noqa: F401 — register all application tables
from app.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep revision 0001 fixed at the original schema. New tables are introduced
    # only by later additive revisions so an upgraded empty database is repeatable.
    for table in Base.metadata.sorted_tables:
        if table.name != "disruption_events":
            table.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("ForgeIQ schema downgrades are disabled to prevent accidental data loss. Back up and plan an additive migration before changing production schemas.")
