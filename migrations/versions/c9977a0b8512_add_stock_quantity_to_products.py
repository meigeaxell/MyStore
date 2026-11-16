
"""Add stock quantity to products

Revision ID: c9977a0b8512
Revises: 8c6c4778bb36
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9977a0b8512"
down_revision: str | Sequence[str] | None = "8c6c4778bb36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("products", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "stock_quantity",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_products_stock_quantity_nonnegative",
            "stock_quantity >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("products", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_products_stock_quantity_nonnegative",
            type_="check",
        )
        batch_op.drop_column("stock_quantity")
