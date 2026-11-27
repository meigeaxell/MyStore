"""add search_synonyms table for user-editable search glossary

Revision ID: a1b2c3d4e5f6
Revises: f7c3a8d2e109
Create Date: 2026-11-27 21:52:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f7c3a8d2e109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_synonyms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("expansions", sa.String(length=400), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_search_synonyms_term"), "search_synonyms", ["term"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_search_synonyms_term"), table_name="search_synonyms")
    op.drop_table("search_synonyms")
