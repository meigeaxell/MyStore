from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.ui.category_management_dialog import CategoryManagementDialog
from app.ui.product_dialog import ProductDialog

ACTION_COLUMN = 6
ROW_HOVER_COLOR = "#FFF8F1"


class HoverTable(QTableWidget):
    """Таблица, которая знает, над какой ячейкой мышь, и сообщает о клике
    по колонке действий. Кнопки не виджеты, а рисуются делегатом: так они
    не зависят от padding в QSS и не ломают раскладку."""

    editRequested = Signal(int)  # id товара

    def __init__(self) -> None:
        super().__init__()
        self._hovered_row = -1
        self._hovered_col = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    @property
    def hovered_row(self) -> int:
        return self._hovered_row

    @property
    def hovered_col(self) -> int:
        return self._hovered_col

    def reset_hover(self) -> None:
        """Вызывать после перезаполнения таблицы."""
        self._set_hovered(-1, -1)

    def _set_hovered(self, row: int, col: int) -> None:
        if (row, col) == (self._hovered_row, self._hovered_col):
            return
        self._hovered_row, self._hovered_col = row, col
        over_action = row >= 0 and col == ACTION_COLUMN
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if over_action
            else Qt.CursorShape.ArrowCursor
        )
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self._set_hovered(index.row(), index.column())
        else:
            self._set_hovered(-1, -1)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(-1, -1)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == ACTION_COLUMN:
            item = self.item(index.row(), 0)
            if item is not None:
                self.editRequested.emit(item.data(Qt.ItemDataRole.UserRole))
        super().mouseReleaseEvent(event)


class RowHoverDelegate(QStyledItemDelegate):
    """Подсвечивает строку под курсором и рисует кнопку-карандаш
    в колонке действий."""

    BUTTON_SIZE = 32

    def __init__(self, table: HoverTable) -> None:
        super().__init__(table)
        self._table = table

    def paint(self, painter, option, index) -> None:
        row_hovered = index.row() == self._table.hovered_row
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if row_hovered and not selected:
            painter.fillRect(option.rect, QColor(ROW_HOVER_COLOR))

        if index.column() == ACTION_COLUMN:
            if row_hovered:
                over_button = self._table.hovered_col == ACTION_COLUMN
                self._paint_edit_button(painter, option.rect, over_button)
            return

        super().paint(painter, option, index)

    def _paint_edit_button(self, painter, cell, active: bool) -> None:
        size = self.BUTTON_SIZE
        rect = QRectF(
            cell.center().x() - size / 2,
            cell.center().y() - size / 2,
            size,
            size,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor("#FFD9B0" if active else "#FFE6CC"))
        painter.drawRoundedRect(rect, 8, 8)

        # карандаш рисуем фигурами, без шрифтовых символов
        painter.translate(rect.center())
        painter.rotate(45)
        painter.setBrush(QColor("#F58A2E"))
        painter.drawRoundedRect(QRectF(-3.2, -9, 6.4, 12), 1.5, 1.5)
        painter.drawPolygon(QPolygonF([
            QPointF(-3.2, 4), QPointF(3.2, 4), QPointF(0, 9.5),
        ]))
        painter.restore()


class CatalogPage(QWidget):
    """Страница каталога товаров."""

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

        header = QHBoxLayout()

        title = QLabel("Каталог товаров")
        title.setObjectName("pageTitle")

        self.count_label = QLabel("Товаров: 0")
        self.count_label.setObjectName("mutedText")

        header.addWidget(title)
        header.addStretch()

        self.add_button = QPushButton("+ Добавить товар")
        self.add_button.clicked.connect(self._open_add_dialog)
        self.add_button.setStyleSheet("""
    QPushButton {
        background-color: #F58A2E;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 16px;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #E87922;
    }
    QPushButton:pressed {
        background-color: #D96818;
    }
""")

        self.categories_button = QPushButton("Управление категориями")
        self.categories_button.clicked.connect(
            self._open_category_management
        )
        self.categories_button.setStyleSheet("""
        QPushButton {
            background-color: #F58A2E;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 9px 14px;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #E87922;
        }
""")    
        header.addWidget(self.categories_button)


        header.addWidget(self.add_button)
        header.addWidget(self.count_label)

        layout.addLayout(header)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Поиск по названию, бренду, модели или SKU..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
    QLineEdit {
        background-color: white;
        color: #1D2939;
        border: 1px solid #E8EBF0;
        border-radius: 8px;
        padding: 10px 12px;
    }
    QLineEdit:focus {
        border: 1px solid #F58A2E;
    }
""")
        self.search_input.textChanged.connect(self._filter_products)

        layout.addWidget(self.search_input)

        self.table = HoverTable()
        self.table.setItemDelegate(RowHoverDelegate(self.table))
        self.table.editRequested.connect(self._open_edit_dialog)
        self.table.setStyleSheet("""
    QTableWidget {
        background-color: #FFFFFF;
        color: #1D2939;
        border: none;
        border-radius: 12px;
        gridline-color: transparent;
        selection-background-color: #FFF3E6;
        selection-color: #1D2939;
        alternate-background-color: #FAFBFC;
        outline: none;
    }

    QHeaderView::section {
        background-color: #F8F9FB;
        color: #667085;
        padding: 13px 10px;
        border: none;
        border-bottom: 1px solid #E8EBF0;
        font-weight: 600;
        font-size: 12px;
    }

    QTableWidget::item {
        padding: 12px 10px;
        border: none;
        border-bottom: 1px solid #F0F1F3;
    }

    QTableWidget::item:selected {
        background-color: #FFF0E1;
        color: #1D2939;
    }

    QScrollBar:vertical {
        background: transparent;
        width: 7px;
        margin: 4px 2px;
    }

    QScrollBar::handle:vertical {
        background: #D0D5DD;
        border-radius: 3px;
        min-height: 30px;
    }

    QScrollBar::handle:vertical:hover {
        background: #98A2B3;
    }

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        height: 0;
    }
""")
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "SKU",
            "Название",
            "Категория",
            "Бренд",
            "Модель",
            "Остаток",
            "",
        ])

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, self.table.horizontalHeader().ResizeMode.Stretch
        )

        layout.addWidget(self.table)

    def _open_add_dialog(self) -> None:
        dialog = ProductDialog(self)

        if dialog.exec():
            self._load_data()


    def _open_category_management(self) -> None:
        dialog = CategoryManagementDialog(self)
        dialog.exec()
        self._load_data()


    def _open_edit_dialog(self, product_id: int) -> None:
        dialog = ProductDialog(self, product_id=product_id)

        if dialog.exec():
            self._load_data()

    def _load_data(self) -> None:
        with SessionLocal() as session:
            categories = session.scalars(select(Category)).all()

            products = session.scalars(
                select(Product)
                .where(Product.is_active.is_(True))
                .order_by(Product.name)
            ).all()

            self.categories = {
                category.id: category.name for category in categories
            }

            self.products = [
                {
                    "id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "category": self.categories.get(
                        product.category_id, "Без категории"
                    ),
                    "brand": product.brand or "—",
                    "model": product.model or "—",
                    "quantity": product.stock_quantity,
                }
                for product in products
            ]

        self.count_label.setText(f"Товаров: {len(self.products)}")
        self._show_products(self.products)

    def _show_products(self, products: list) -> None:
        self.table.setRowCount(len(products))

        for row, product in enumerate(products):
            values = [
                product["sku"],
                product["name"],
                product["category"],
                product["brand"],
                product["model"],
                str(product["quantity"]),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)

                if column == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.table.setItem(row, column, item)

            # id товара хранится в первой ячейке строки
            self.table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, product["id"]
            )

        self.table.reset_hover()

        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 140)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 60)

    def _filter_products(self, text: str) -> None:
        query = text.strip().lower()

        filtered = [
            product
            for product in self.products
            if query in " ".join([
                product["sku"],
                product["name"],
                product["category"],
                product["brand"],
                product["model"],
            ]).lower()
        ]

        self._show_products(filtered)
