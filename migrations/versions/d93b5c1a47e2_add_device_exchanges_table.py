"""add device exchanges table

Revision ID: d93b5c1a47e2
Revises: a4d8e91f20c3
Create Date: 2026-11-19 02:12:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d93b5c1a47e2"
down_revision: str | Sequence[str] | None = "a4d8e91f20c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "device_exchanges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exchange_number", sa.String(length=30), nullable=False),
        sa.Column("exchange_date", sa.DateTime(), nullable=False),
        sa.Column("original_sale_id", sa.Integer(), nullable=False),
        sa.Column("original_sale_item_id", sa.Integer(), nullable=False),
        sa.Column("old_product_id", sa.Integer(), nullable=False),
        sa.Column("old_stock_item_id", sa.Integer(), nullable=True),
        sa.Column("old_imei", sa.String(length=30), nullable=True),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("new_product_id", sa.Integer(), nullable=False),
        sa.Column("new_stock_item_id", sa.Integer(), nullable=True),
        sa.Column("new_imei", sa.String(length=30), nullable=True),
        sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "new_unit_cost",
            sa.Numeric(12, 2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column(
            "new_cost_currency",
            sa.String(length=3),
            server_default="USD",
            nullable=False,
        ),
        sa.Column(
            "new_cost_exchange_rate",
            sa.Numeric(12, 4),
            server_default="1.0000",
            nullable=False,
        ),
        sa.Column("price_difference", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["new_product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["new_stock_item_id"], ["stock_items.id"]),
        sa.ForeignKeyConstraint(["old_product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["old_stock_item_id"], ["stock_items.id"]),
        sa.ForeignKeyConstraint(["original_sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(["original_sale_item_id"], ["sale_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange_number"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("device_exchanges")
