from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class IncomingQueueItem(Base):
    """Элемент буферной очереди приёмки с мобильного сканера до подтверждения на ПК."""

    __tablename__ = "incoming_queue_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 'known' (товар найден в БД), 'unknown' (новый товар), 'phone_imei' (телефон по IMEI)
    item_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    barcode: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    imei1: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )

    imei2: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    serial_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    condition: Mapped[str] = mapped_column(
        String(20),
        default="new",
        server_default="new",
        nullable=False,
    )

    model_hint: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    ocr_raw_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )

    unit_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        server_default="USD",
        nullable=False,
    )

    supplier_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    device_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )
