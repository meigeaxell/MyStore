from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)

    receipt_number: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
    )

    sale_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        default=Decimal("1.0000"),
        server_default="1.0000",
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    customer_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    customer_phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="completed",
        nullable=False,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    comment: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

