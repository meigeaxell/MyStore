"""Обратная совместимость: модуль Каталога объединён с «Товары и склад» (StockPage)."""
from app.ui.stock_page import StockPage as CatalogPage

__all__ = ["CatalogPage"]
