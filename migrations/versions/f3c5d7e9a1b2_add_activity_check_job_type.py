"""add activity_check job type

Revision ID: f3c5d7e9a1b2
Revises: d1bb4ae254b7
Create Date: 2026-06-08 13:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c5d7e9a1b2"
down_revision: str | None = "d1bb4ae254b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'ACTIVITY_CHECK'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; nothing to do on downgrade.
    pass
