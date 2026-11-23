"""add barcode column to products table

Revision ID: a8c4e1f72b90
Revises: f3a9c8b21d4e
Create Date: 2026-11-23 17:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8c4e1f72b90"
down_revision: str | Sequence[str] | None = "f3a9c8b21d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(sa.Column("barcode", sa.String(length=100), nullable=True))
        batch_op.create_index(op.f("ix_products_barcode"), ["barcode"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_products_barcode"))
        batch_op.drop_column("barcode")
