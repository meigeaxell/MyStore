from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_items_quantity_positive"),
        CheckConstraint(
            "unit_cost >= 0",
            name="ck_purchase_items_unit_cost_nonnegative",
        ),
        CheckConstraint(
            "total_cost >= 0",
            name="ck_purchase_items_total_cost_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id"),
        nullable=False,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    unit_cost: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    total_cost: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
