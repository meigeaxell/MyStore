from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from sqlalchemy import DateTime, Numeric, String


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)

    purchase_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    exchange_rate: Mapped[float] = mapped_column(
    Numeric(12, 4),
    nullable=False,
    )

    total_amount: Mapped[float] = mapped_column(
    Numeric(12, 2),
    nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )