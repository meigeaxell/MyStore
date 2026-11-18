
"""add purchase cancellation and supplier refunds

Revision ID: b7e4c2a91f60
Revises: 86d9ddd318cf
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4c2a91f60"
down_revision: str | Sequence[str] | None = "86d9ddd318cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchases",
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
    )
    op.add_column(
        "purchases",
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "purchases",
        sa.Column(
            "cancellation_reason",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.create_table(
        "purchase_refunds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=False),
        sa.Column("refund_date", sa.DateTime(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_purchase_refunds_amount_positive",
        ),
        sa.CheckConstraint(
            "exchange_rate > 0",
            name="ck_purchase_refunds_exchange_rate_positive",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "purchase_refund_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_cash_movements_purchase_refund_id",
            "purchase_refunds",
            ["purchase_refund_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("cash_movements") as batch_op:
        batch_op.drop_constraint(
            "fk_cash_movements_purchase_refund_id",
            type_="foreignkey",
        )
        batch_op.drop_column("purchase_refund_id")

    op.drop_table("purchase_refunds")

    op.drop_column("purchases", "cancellation_reason")
    op.drop_column("purchases", "cancelled_at")
    op.drop_column("purchases", "status")
