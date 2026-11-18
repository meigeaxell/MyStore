from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PurchaseRefund(Base):
    __tablename__ = "purchase_refunds"
    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_purchase_refunds_amount_positive",
        ),
        CheckConstraint(
            "exchange_rate > 0",
            name="ck_purchase_refunds_exchange_rate_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id"),
        nullable=False,
    )

    refund_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    amount: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    exchange_rate: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )