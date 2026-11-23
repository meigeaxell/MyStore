"""add simurg fields to sales table

Revision ID: c2f7a9d41e83
Revises: a8c4e1f72b90
Create Date: 2026-11-23 21:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2f7a9d41e83"
down_revision: str | Sequence[str] | None = "a8c4e1f72b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_simurg",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column("simurg_payout_date", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.drop_column("simurg_payout_date")
        batch_op.drop_column("is_simurg")
