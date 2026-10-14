"""Add automotive workflow and capability columns to existing ForgeIQ records.

Revision ID: 0003_automotive_ai_search
Revises: 0002_dynamic_rescheduling
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_automotive_ai_search"
down_revision = "0002_dynamic_rescheduling"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    # Some fresh installs bootstrap tables from the current ORM metadata in
    # 0001; older installations have only the original columns. Add each field
    # only when absent, so both paths safely converge on this schema revision.
    columns = _columns("jobs")
    if "component_type" not in columns:
        op.add_column("jobs", sa.Column("component_type", sa.String(length=40), nullable=True, server_default=sa.text("'other'")))
    if "status" not in columns:
        op.add_column("jobs", sa.Column("status", sa.String(length=24), nullable=True, server_default=sa.text("'queued'")))
    columns = _columns("machines")
    if "processing_capabilities" not in columns:
        op.add_column("machines", sa.Column("processing_capabilities", sa.JSON(), nullable=True))
    if "maintenance_schedule" not in columns:
        op.add_column("machines", sa.Column("maintenance_schedule", sa.JSON(), nullable=True))
    columns = _columns("operations")
    if "required_capability" not in columns:
        op.add_column("operations", sa.Column("required_capability", sa.String(length=80), nullable=True))

    op.execute("UPDATE jobs SET component_type = 'other' WHERE component_type IS NULL")
    op.execute("UPDATE jobs SET status = 'queued' WHERE status IS NULL")
    op.execute("UPDATE machines SET processing_capabilities = '[]' WHERE processing_capabilities IS NULL")
    op.execute("UPDATE machines SET maintenance_schedule = '[]' WHERE maintenance_schedule IS NULL")
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("component_type", existing_type=sa.String(length=40), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=24), nullable=False)
    with op.batch_alter_table("machines") as batch:
        batch.alter_column("processing_capabilities", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("maintenance_schedule", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    raise RuntimeError("ForgeIQ schema downgrades are disabled to prevent accidental data loss. Preserve user records and apply reviewed forward-only migrations.")
