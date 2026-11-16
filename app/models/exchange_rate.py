from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True)

    base_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    target_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    rate: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )

    effective_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )