"""add sales cost basis debt and imei purchase fields

Revision ID: a4d8e91f20c3
Revises: 372f09181779
Create Date: 2026-11-19 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d8e91f20c3"
down_revision: str | Sequence[str] | None = "372f09181779"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("sales") as batch_op:
        batch_op.add_column(
            sa.Column(
                "exchange_rate",
                sa.Numeric(12, 4),
                server_default="1.0000",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("customer_name", sa.String(length=150), nullable=True)
        )
        batch_op.add_column(
            sa.Column("customer_phone", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("cancelled_at", sa.DateTime(), nullable=True)
        )

    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "unit_cost",
                sa.Numeric(12, 2),
                server_default="0.00",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "cost_currency",
                sa.String(length=3),
                server_default="USD",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "cost_exchange_rate",
                sa.Numeric(12, 4),
                server_default="1.0000",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_exchanged",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )

    with op.batch_alter_table("sale_payments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "payment_date",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "exchange_rate",
                sa.Numeric(12, 4),
                server_default="1.0000",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cash_register_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "payment_type",
                sa.String(length=30),
                server_default="payment",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("description", sa.String(length=255), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_sale_payments_cash_register_id",
            "cash_registers",
            ["cash_register_id"],
            ["id"],
        )

    with op.batch_alter_table("purchases") as batch_op:
        batch_op.add_column(
            sa.Column("supplier_name", sa.String(length=150), nullable=True)
        )

    with op.batch_alter_table("stock_items") as batch_op:
        batch_op.add_column(
            sa.Column("purchase_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True)
        )
        batch_op.add_column(
            sa.Column("cost_currency", sa.String(length=3), nullable=True)
        )
        batch_op.add_column(
            sa.Column("cost_exchange_rate", sa.Numeric(12, 4), nullable=True)
        )
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_stock_items_purchase_id",
            "purchases",
            ["purchase_id"],
            ["id"],
        )

    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "exchange_rate",
                sa.Numeric(12, 4),
                server_default="1.0000",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cash_register_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_cash_movements_cash_register_id",
            "cash_registers",
            ["cash_register_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.drop_constraint(
            "fk_cash_movements_cash_register_id",
            type_="foreignkey",
        )
        batch_op.drop_column("cash_register_id")
        batch_op.drop_column("exchange_rate")

    with op.batch_alter_table("stock_items") as batch_op:
        batch_op.drop_constraint(
            "fk_stock_items_purchase_id",
            type_="foreignkey",
        )
        batch_op.drop_column("created_at")
        batch_op.drop_column("cost_exchange_rate")
        batch_op.drop_column("cost_currency")
        batch_op.drop_column("unit_cost")
        batch_op.drop_column("purchase_id")

    with op.batch_alter_table("purchases") as batch_op:
        batch_op.drop_column("supplier_name")

    with op.batch_alter_table("sale_payments") as batch_op:
        batch_op.drop_constraint(
            "fk_sale_payments_cash_register_id",
            type_="foreignkey",
        )
        batch_op.drop_column("description")
        batch_op.drop_column("payment_type")
        batch_op.drop_column("cash_register_id")
        batch_op.drop_column("exchange_rate")
        batch_op.drop_column("payment_date")

    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.drop_column("is_exchanged")
        batch_op.drop_column("cost_exchange_rate")
        batch_op.drop_column("cost_currency")
        batch_op.drop_column("unit_cost")

    with op.batch_alter_table("sales") as batch_op:
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("customer_phone")
        batch_op.drop_column("customer_name")
        batch_op.drop_column("exchange_rate")
