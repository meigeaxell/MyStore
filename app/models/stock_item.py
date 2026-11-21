from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class StockItem(Base):
    __tablename__ = "stock_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )

    purchase_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchases.id"),
        nullable=True,
    )

    imei1: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
    )

    imei2: Mapped[str | None] = mapped_column(
        String(20),
        unique=True,
        nullable=True,
    )

    serial_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    condition: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="in_stock",
        nullable=False,
    )

    unit_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    cost_currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
    )

    cost_exchange_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    acquisition_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=True,
    )
