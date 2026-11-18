
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.ui import theme
from app.ui.widgets import Card


class StockPage(QWidget):
    """Страница складских остатков."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")

        self.products = []
        self.categories = {}

        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # Заголовок страницы
        header = QHBoxLayout()
        header.setSpacing(12)

        title = QLabel("Склад")
        title.setObjectName("pageTitle")

        header.addWidget(title)
        header.addStretch()

        self.count_label = QLabel("Товарных позиций: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        refresh_button = QPushButton("↻  Обновить")
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {theme.ACCENT_BG};
                border-color: {theme.ACCENT};
            }}
        """)
        refresh_button.clicked.connect(self._load_data)
        header.addWidget(refresh_button)

        layout.addLayout(header)

        # Карточки складской статистики
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(14)

        self.total_value = QLabel("0")
        self.low_stock_value = QLabel("0")
        self.out_of_stock_value = QLabel("0")

        stats_layout.addWidget(
            self._create_stat_card(
                "Всего товарных позиций",
                self.total_value,
                theme.NAVY,
                "Активные товары каталога",
            )
        )
        stats_layout.addWidget(
            self._create_stat_card(
                "Низкий остаток",
                self.low_stock_value,
                theme.ACCENT,
                "Требуют пополнения",
            )
        )
        stats_layout.addWidget(
            self._create_stat_card(
                "Нет в наличии",
                self.out_of_stock_value,
                theme.RED,
                "Нулевой остаток",
            )
        )

        layout.addLayout(stats_layout)

        # Поиск и фильтр категорий
        filters = QHBoxLayout()
        filters.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Поиск по названию, бренду, модели или SKU..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(42)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: white;
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 9px 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {theme.ACCENT};
            }}
        """)
        self.search_input.textChanged.connect(self._filter_products)

        self.category_filter = QComboBox()
        self.category_filter.setMinimumWidth(210)
        self.category_filter.setMinimumHeight(42)
        self.category_filter.setStyleSheet(f"""
            QComboBox {{
                background: white;
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QComboBox:focus {{
                border: 1px solid {theme.ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background: white;
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                selection-background-color: {theme.ACCENT_BG};
                selection-color: {theme.TEXT};
                padding: 4px;
            }}
        """)
        self.category_filter.addItem("Все категории", None)
        self.category_filter.currentIndexChanged.connect(
            self._filter_products
        )

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_filter)

        layout.addLayout(filters)

        # Таблица склада
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "SKU",
            "Название",
            "Категория",
            "На складе",
            "Минимум",
            "Состояние",
        ])

        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: white;
                color: {theme.TEXT};
                border: none;
                border-radius: 12px;
                gridline-color: transparent;
                selection-background-color: {theme.ACCENT_BG};
                selection-color: {theme.TEXT};
                alternate-background-color: #FAFBFC;
                outline: none;
            }}

            QHeaderView::section {{
                background: #F8F9FB;
                color: {theme.MUTED};
                padding: 13px 10px;
                border: none;
                border-bottom: 1px solid {theme.BORDER};
                font-weight: 600;
                font-size: 9pt;
            }}

            QTableWidget::item {{
                padding: 12px 10px;
                border: none;
                border-bottom: 1px solid #F0F1F3;
            }}

            QTableWidget::item:selected {{
                background: #FFF0E1;
                color: {theme.TEXT};
            }}

            QScrollBar:vertical {{
                background: transparent;
                width: 7px;
                margin: 4px 2px;
            }}

            QScrollBar::handle:vertical {{
                background: #D0D5DD;
                border-radius: 3px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: #98A2B3;
            }}

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)

        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(
            1, header_view.ResizeMode.Stretch
        )

        header_view.setSectionResizeMode(
            0, header_view.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            2, header_view.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            3, header_view.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            4, header_view.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            5, header_view.ResizeMode.ResizeToContents
        )

        layout.addWidget(self.table, 1)

    def _create_stat_card(
        self,
        title: str,
        value_label: QLabel,
        color: str,
        description: str,
    ) -> Card:
        card = Card(margins=(18, 14, 18, 14), spacing=5)

        title_label = QLabel(title)
        title_label.setObjectName("mutedText")

        value_label.setStyleSheet(
            f"color: {color}; font-size: 21pt; font-weight: 700;"
        )

        description_label = QLabel(description)
        description_label.setStyleSheet(
            f"color: {theme.MUTED}; font-size: 8.5pt;"
        )

        card.body.addWidget(title_label)
        card.body.addWidget(value_label)
        card.body.addWidget(description_label)

        return card

    def _load_data(self) -> None:
        with SessionLocal() as session:
            statement = (
                select(Product, Category.name)
                .join(Category, Product.category_id == Category.id)
                .where(Product.is_active.is_(True))
                .order_by(Product.name.asc())
            )

            rows = session.execute(statement).all()

            self.products = [
                {
                    "id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "category_id": product.category_id,
                    "category": category_name,
                    "brand": product.brand or "",
                    "model": product.model or "",
                    "quantity": product.stock_quantity,
                    "minimum": product.min_stock_quantity,
                }
                for product, category_name in rows
            ]

            categories_statement = (
                select(Category)
                .where(Category.is_active.is_(True))
                .order_by(Category.name.asc())
            )

            categories = session.scalars(
                categories_statement
            ).all()

            self.categories = {
                category.id: category.name
                for category in categories
            }

        self._update_statistics()
        self._update_category_filter()
        self._filter_products()

    def _update_statistics(self) -> None:
        total = len(self.products)

        low_stock = sum(
            1
            for product in self.products
            if (
                product["quantity"] > 0
                and product["minimum"] > 0
                and product["quantity"] <= product["minimum"]
            )
        )

        out_of_stock = sum(
            1
            for product in self.products
            if product["quantity"] == 0
        )

        self.total_value.setText(str(total))
        self.low_stock_value.setText(str(low_stock))
        self.out_of_stock_value.setText(str(out_of_stock))

    def _update_category_filter(self) -> None:
        selected_category = self.category_filter.currentData()

        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Все категории", None)

        for category_id, name in self.categories.items():
            self.category_filter.addItem(name, category_id)

        index = self.category_filter.findData(selected_category)

        if index >= 0:
            self.category_filter.setCurrentIndex(index)

        self.category_filter.blockSignals(False)

    def _filter_products(self, *_args) -> None:
        search = self.search_input.text().strip().lower()
        category_id = self.category_filter.currentData()

        filtered = []

        for product in self.products:
            if (
                category_id is not None
                and product["category_id"] != category_id
            ):
                continue

            searchable = " ".join([
                product["sku"],
                product["name"],
                product["brand"],
                product["model"],
                product["category"],
            ]).lower()

            if search and search not in searchable:
                continue

            filtered.append(product)

        self._show_products(filtered)

    def _show_products(self, products: list) -> None:
        self.table.setRowCount(len(products))
        self.count_label.setText(
            f"Товарных позиций: {len(products)}"
        )

        for row, product in enumerate(products):
            values = [
                product["sku"],
                product["name"],
                product["category"],
                str(product["quantity"]),
                str(product["minimum"]),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)

                if column in (3, 4):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.table.setItem(row, column, item)

            if product["quantity"] == 0:
                status = "Нет в наличии"
                color = theme.RED
            elif (
                product["minimum"] > 0
                and product["quantity"] <= product["minimum"]
            ):
                status = "Низкий остаток"
                color = theme.ACCENT
            else:
                status = "В наличии"
                color = theme.GREEN

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor("white"))
            status_item.setBackground(QColor(color))
            status_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
            )

            self.table.setItem(row, 5, status_item)
