"""add profile activity_level

Revision ID: d1ffb381aea0
Revises: a9db49bf7f24
Create Date: 2026-06-08 11:22:53.275746

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1ffb381aea0'
down_revision: str | None = 'a9db49bf7f24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


activity_level = sa.Enum(
    "SEDENTARY",
    "LIGHTLY_ACTIVE",
    "MODERATELY_ACTIVE",
    "VERY_ACTIVE",
    "EXTRA_ACTIVE",
    name="activity_level",
)


def upgrade() -> None:
    activity_level.create(op.get_bind(), checkfirst=True)
    op.add_column("profiles", sa.Column("activity_level", activity_level, nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "activity_level")
    activity_level.drop(op.get_bind(), checkfirst=True)
