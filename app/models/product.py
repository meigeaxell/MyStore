from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "stock_quantity >= 0",
            name="ck_products_stock_quantity_nonnegative",
        ),
        CheckConstraint(
            "min_stock_quantity >= 0",
            name="ck_products_min_stock_quantity_nonnegative",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"),
        nullable=False,
    )

    sku: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    barcode: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    specification: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    stock_quantity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    min_stock_quantity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
