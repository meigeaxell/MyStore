
"""add purchase items and payments

Revision ID: 86d9ddd318cf
Revises: fe8c48bfae5a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "86d9ddd318cf"
down_revision: str | Sequence[str] | None = "fe8c48bfae5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.DateTime(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=False),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_purchase_payments_amount_positive",
        ),
        sa.CheckConstraint(
            "exchange_rate > 0",
            name="ck_purchase_payments_exchange_rate_positive",
        ),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "purchase_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_purchase_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "total_cost >= 0",
            name="ck_purchase_items_total_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "unit_cost >= 0",
            name="ck_purchase_items_unit_cost_nonnegative",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.add_column(
            sa.Column("purchase_payment_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_cash_movements_purchase_payment_id",
            "purchase_payments",
            ["purchase_payment_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.drop_constraint(
            "fk_cash_movements_purchase_payment_id",
            type_="foreignkey",
        )
        batch_op.drop_column("purchase_payment_id")

    op.drop_table("purchase_items")
    op.drop_table("purchase_payments")
