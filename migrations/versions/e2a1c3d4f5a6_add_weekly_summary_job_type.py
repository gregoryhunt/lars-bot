"""add weekly_summary job type

Revision ID: e2a1c3d4f5a6
Revises: d1ffb381aea0
Create Date: 2026-06-08 12:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a1c3d4f5a6"
down_revision: str | None = "d1ffb381aea0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The enum members are stored by NAME (see other models); add the new one.
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'WEEKLY_SUMMARY'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; nothing to do on downgrade.
    pass
