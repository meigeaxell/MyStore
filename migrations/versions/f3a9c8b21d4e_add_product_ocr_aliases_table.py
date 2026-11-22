"""add product_ocr_aliases table for accessory box recognition

Revision ID: f3a9c8b21d4e
Revises: e7b2a41c90f4
Create Date: 2026-11-22 12:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c8b21d4e"
down_revision: str | Sequence[str] | None = "e7b2a41c90f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_ocr_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("normalized_text", sa.String(length=255), nullable=False),
        sa.Column("raw_text", sa.String(length=500), nullable=True),
        sa.Column("hits", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "normalized_text",
            name="uq_product_ocr_aliases_product_norm",
        ),
    )
    op.create_index(
        op.f("ix_product_ocr_aliases_product_id"),
        "product_ocr_aliases",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_ocr_aliases_normalized_text"),
        "product_ocr_aliases",
        ["normalized_text"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_product_ocr_aliases_normalized_text"), table_name="product_ocr_aliases")
    op.drop_index(op.f("ix_product_ocr_aliases_product_id"), table_name="product_ocr_aliases")
    op.drop_table("product_ocr_aliases")
