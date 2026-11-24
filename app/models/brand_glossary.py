from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class BrandGlossary(Base):
    """Индекс глоссария бренда для быстрого и точного OCR-распознавания коробок.

    Автоматически синхронизируется при добавлении/редактировании товара на складе:
    хранит связку (brand -> product_name, model_text, reference_text, category_name).
    """

    __tablename__ = "brand_glossaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    brand_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    brand_display: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    model_text: Mapped[str] = mapped_column(
        String(100),
        default="",
        server_default="",
        nullable=False,
    )
    reference_text: Mapped[str] = mapped_column(
        String(255),
        default="",
        server_default="",
        nullable=False,
    )
    category_name: Mapped[str] = mapped_column(
        String(120),
        default="",
        server_default="",
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )
