
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.product import Product


def get_low_stock_products():
    """Возвращает активные товары, остаток которых достиг минимума."""
    with SessionLocal() as session:
        statement = (
            select(Product)
            .where(
                Product.is_active.is_(True),
                Product.min_stock_quantity > 0,
                Product.stock_quantity <= Product.min_stock_quantity,
            )
            .order_by(Product.stock_quantity.asc(), Product.name.asc())
        )

        return session.scalars(statement).all()
