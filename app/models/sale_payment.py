from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SalePayment(Base):
    __tablename__ = "sale_payments"

    id: Mapped[int] = mapped_column(primary_key=True)

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id"),
        nullable=False,
    )

    payment_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        default=Decimal("1.0000"),
        server_default="1.0000",
        nullable=False,
    )

    cash_register_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_registers.id"),
        nullable=True,
    )

    payment_type: Mapped[str] = mapped_column(
        String(30),
        default="payment",
        server_default="payment",
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

