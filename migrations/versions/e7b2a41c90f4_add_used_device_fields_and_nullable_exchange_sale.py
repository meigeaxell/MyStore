"""add used device fields and nullable exchange sale references

Revision ID: e7b2a41c90f4
Revises: d93b5c1a47e2
Create Date: 2026-11-19 06:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2a41c90f4"
down_revision: str | Sequence[str] | None = "d93b5c1a47e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stock_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("acquisition_source", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("notes", sa.String(length=255), nullable=True)
        )

    with op.batch_alter_table("device_exchanges", schema=None) as batch_op:
        batch_op.alter_column(
            "original_sale_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.alter_column(
            "original_sale_item_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "old_condition",
                sa.String(length=30),
                nullable=True,
                server_default="used",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("device_exchanges", schema=None) as batch_op:
        batch_op.drop_column("old_condition")
        batch_op.alter_column(
            "original_sale_item_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "original_sale_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("stock_items", schema=None) as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("acquisition_source")
