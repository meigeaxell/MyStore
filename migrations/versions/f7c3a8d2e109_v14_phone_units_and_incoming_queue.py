"""add standalone phone unit fields, system phone categories, and incoming queue

Revision ID: f7c3a8d2e109
Revises: e4b91d6a7c02
Create Date: 2026-11-24 20:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7c3a8d2e109"
down_revision: str | Sequence[str] | None = "e4b91d6a7c02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "is_phone_unit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.add_column("stock_items", sa.Column("memory", sa.String(length=50), nullable=True))
    op.add_column("stock_items", sa.Column("color", sa.String(length=50), nullable=True))
    op.add_column("stock_items", sa.Column("battery_health", sa.String(length=30), nullable=True))
    op.add_column("stock_items", sa.Column("cosmetic_condition", sa.String(length=120), nullable=True))

    op.create_table(
        "incoming_queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("barcode", sa.String(length=100), nullable=True),
        sa.Column("imei1", sa.String(length=20), nullable=True),
        sa.Column("imei2", sa.String(length=20), nullable=True),
        sa.Column("serial_number", sa.String(length=100), nullable=True),
        sa.Column("condition", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("model_hint", sa.String(length=200), nullable=True),
        sa.Column("ocr_raw_text", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("supplier_name", sa.String(length=150), nullable=True),
        sa.Column("device_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_incoming_queue_items_item_kind", "incoming_queue_items", ["item_kind"])
    op.create_index("ix_incoming_queue_items_product_id", "incoming_queue_items", ["product_id"])
    op.create_index("ix_incoming_queue_items_barcode", "incoming_queue_items", ["barcode"])
    op.create_index("ix_incoming_queue_items_imei1", "incoming_queue_items", ["imei1"])

    # Создаём две постоянные системные категории телефонов (если их ещё нет)
    conn = op.get_bind()
    for code, name, desc in (
        ("PHONE_NEW", "Telefon Täze", "Täze telefonlar (IMEI boýunça hemişelik kategoriýa)"),
        ("PHONE_USED", "Telefon B/U", "Ulanylan B/U telefonlar (IMEI boýunça hemişelik kategoriýa)"),
    ):
        exists = conn.execute(
            sa.text(
                "SELECT id FROM categories WHERE code = :code OR lower(name) = lower(:name) LIMIT 1"
            ),
            {"code": code, "name": name},
        ).first()
        if exists is None:
            conn.execute(
                sa.text(
                    "INSERT INTO categories (name, code, description, is_active) "
                    "VALUES (:name, :code, :desc, 1)"
                ),
                {"name": name, "code": code, "desc": desc},
            )


def downgrade() -> None:
    op.drop_index("ix_incoming_queue_items_imei1", table_name="incoming_queue_items")
    op.drop_index("ix_incoming_queue_items_barcode", table_name="incoming_queue_items")
    op.drop_index("ix_incoming_queue_items_product_id", table_name="incoming_queue_items")
    op.drop_index("ix_incoming_queue_items_item_kind", table_name="incoming_queue_items")
    op.drop_table("incoming_queue_items")

    op.drop_column("stock_items", "cosmetic_condition")
    op.drop_column("stock_items", "battery_health")
    op.drop_column("stock_items", "color")
    op.drop_column("stock_items", "memory")
    op.drop_column("products", "is_phone_unit")
