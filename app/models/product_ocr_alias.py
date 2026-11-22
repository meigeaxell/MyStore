from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProductOcrAlias(Base):
    """Запомненная надпись с коробки товара (самообучаемый алиас для OCR-поиска аксессуаров)."""

    __tablename__ = "product_ocr_aliases"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "normalized_text",
            name="uq_product_ocr_aliases_product_norm",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    normalized_text: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    raw_text: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    hits: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )
