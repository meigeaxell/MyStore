from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DeviceExchange(Base):
    __tablename__ = "device_exchanges"

    id: Mapped[int] = mapped_column(primary_key=True)

    exchange_number: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
    )

    exchange_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    original_sale_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales.id"),
        nullable=True,
    )

    original_sale_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_items.id"),
        nullable=True,
    )

    old_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )

    old_stock_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_items.id"),
        nullable=True,
    )

    old_imei: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    old_condition: Mapped[str | None] = mapped_column(
        String(30),
        default="used",
        server_default="used",
        nullable=True,
    )

    old_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    new_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )

    new_stock_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_items.id"),
        nullable=True,
    )

    new_imei: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    new_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    new_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        server_default="0.00",
        nullable=False,
    )

    new_cost_currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        server_default="USD",
        nullable=False,
    )

    new_cost_exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        default=Decimal("1.0000"),
        server_default="1.0000",
        nullable=False,
    )

    price_difference: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        default=Decimal("1.0000"),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
