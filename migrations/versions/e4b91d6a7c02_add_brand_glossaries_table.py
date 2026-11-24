"""add brand_glossaries table for brand-indexed OCR lookup

Revision ID: e4b91d6a7c02
Revises: c2f7a9d41e83
Create Date: 2026-11-24 12:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b91d6a7c02"
down_revision: str | Sequence[str] | None = "c2f7a9d41e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_glossaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("brand_key", sa.String(length=100), nullable=False),
        sa.Column("brand_display", sa.String(length=100), nullable=False),
        sa.Column("product_name", sa.String(length=150), nullable=False),
        sa.Column("model_text", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("reference_text", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("category_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_brand_glossaries_product_id", "brand_glossaries", ["product_id"], unique=True)
    op.create_index("ix_brand_glossaries_brand_key", "brand_glossaries", ["brand_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_brand_glossaries_brand_key", table_name="brand_glossaries")
    op.drop_index("ix_brand_glossaries_product_id", table_name="brand_glossaries")
    op.drop_table("brand_glossaries")
