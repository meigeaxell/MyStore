from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CashRegister(Base):
    __tablename__ = "cash_registers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # USD or TMT
    balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )


class CashTransaction(Base):
    __tablename__ = "cash_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    cash_register_id: Mapped[int] = mapped_column(
        ForeignKey("cash_registers.id"),
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # income, expense, refund
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("1.0000"),
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )
    sale_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales.id"),
        nullable=True,
    )

