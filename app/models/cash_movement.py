from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(primary_key=True)

    movement_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    movement_type: Mapped[str] = mapped_column(
        String(30),
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

    sale_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales.id"),
        nullable=True,
    )

    purchase_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_payments.id"),
        nullable=True,
    )

    purchase_refund_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_refunds.id"),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
