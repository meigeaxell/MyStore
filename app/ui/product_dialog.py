
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.ui.category_dialog import CategoryDialog


def _make_arrow_icon(color: str = "#F58A2E") -> str:
    """Рисует стрелку-галочку вниз и возвращает путь к PNG для QSS."""
    path = Path(tempfile.gettempdir()) / "mobilestore_arrow_down.png"
    pm = QPixmap(24, 24)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(color), 2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    painter.setPen(pen)
    painter.drawPolyline(
        [
            QPointF(7, 9.5),
            QPointF(12, 14.5),
            QPointF(17, 9.5),
        ]
    )
    painter.end()

    pm.save(str(path))
    return path.as_posix()


DIALOG_STYLE = """
    QDialog { background-color: #F6F7F9; color: #1D2939; }
    QLabel { color: #1D2939; }

    QLineEdit, QComboBox {
        background-color: white;
        color: #1D2939;
        border: 1px solid #E8EBF0;
        border-radius: 8px;
        padding: 8px;
    }
    QLineEdit:focus, QComboBox:focus, QComboBox:on {
        border: 1px solid #F58A2E;
    }

    QComboBox::drop-down {
        background-color: #FFF3E6;
        border: none;
        border-left: 1px solid #E8EBF0;
        width: 32px;
        border-top-right-radius: 8px;
        border-bottom-right-radius: 8px;
    }
    QComboBox::down-arrow {
        image: url(__ARROW__);
        width: 16px;
        height: 16px;
    }

    QPushButton {
        background-color: #F58A2E;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 9px;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #E87922; }
"""


POPUP_CONTAINER_STYLE = """
    QFrame#comboPopup {
        background-color: white;
        border: 1px solid #E8EBF0;
        border-radius: 8px;
    }
"""


POPUP_VIEW_STYLE = """
    QListView {
        background-color: white;
        color: #1D2939;
        border: none;
        outline: none;
        padding: 4px;
    }
    QListView::item {
        min-height: 30px;
        padding: 0 10px;
        border-radius: 6px;
        color: #1D2939;
        background-color: transparent;
    }
    QListView::item:hover, QListView::item:selected {
        background-color: #FFE6CC;
        color: #1D2939;
    }
"""


class ProductDialog(QDialog):
    """Окно добавления и редактирования товара."""

    def __init__(
        self,
        parent=None,
        product_id: int | None = None,
    ) -> None:
        super().__init__(parent)

        self.product_id = product_id

        if self.product_id is None:
            self.setWindowTitle("Добавление товара")
        else:
            self.setWindowTitle("Редактирование товара")

        self.setMinimumWidth(400)
        self.setStyleSheet(
            DIALOG_STYLE.replace("__ARROW__", _make_arrow_icon())
        )

        self._build_ui()
        self._load_categories()

        if self.product_id is not None:
            self._load_product()

    def _load_product(self) -> None:
        """Загружает существующий товар в поля формы."""
        try:
            with SessionLocal() as session:
                product = session.get(Product, self.product_id)

                if product is None:
                    QMessageBox.warning(
                        self,
                        "Товар не найден",
                        "Не удалось найти выбранный товар.",
                    )
                    self.reject()
                    return
                self.deactivate_button.show()

                self.name_input.setText(product.name)
                self.brand_input.setText(product.brand or "")
                self.model_input.setText(product.model or "")
                self.specification_input.setText(
                    product.specification or ""
                )
                self.stock_input.setText(str(product.stock_quantity))
                self.min_stock_input.setText(
                    str(product.min_stock_quantity)
                )

                index = self.category_input.findData(
                    product.category_id
                )

                if index >= 0:
                    self.category_input.setCurrentIndex(index)
                else:
                    category = session.get(
                        Category,
                        product.category_id,
                    )
                    if category is not None:
                        self.category_input.addItem(
                            f"{category.name} (неактивна)",
                            category.id,
                        )
                        self.category_input.setCurrentIndex(
                            self.category_input.count() - 1
                        )

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка загрузки",
                f"Не удалось загрузить товар:\n{error}",
            )
            self.reject()

    @staticmethod
    def _style_combo_popup(combo: QComboBox) -> None:
        """Настраивает светлое оформление выпадающего списка."""
        view = QListView()
        combo.setView(view)
        view.setStyleSheet(POPUP_VIEW_STYLE)

        container = view.window()
        container.setObjectName("comboPopup")
        container.setStyleSheet(POPUP_CONTAINER_STYLE)
        container.setAutoFillBackground(True)

        palette = container.palette()
        for role in (
            QPalette.ColorRole.Window,
            QPalette.ColorRole.Base,
        ):
            palette.setColor(role, QColor("white"))

        palette.setColor(
            QPalette.ColorRole.Text,
            QColor("#1D2939"),
        )
        palette.setColor(
            QPalette.ColorRole.WindowText,
            QColor("#1D2939"),
        )

        container.setPalette(palette)
        view.setPalette(palette)

    def _add_category(self) -> None:
        """Открывает окно создания категории."""
        dialog = CategoryDialog(self)

        if dialog.exec():
            self._load_categories()

            index = self.category_input.findData(
                dialog.created_category_id
            )

            if index >= 0:
                self.category_input.setCurrentIndex(index)

    def _load_categories(self) -> None:
        """Загружает активные категории."""
        with SessionLocal() as session:
            categories = session.scalars(
                select(Category)
                .where(Category.is_active.is_(True))
                .order_by(Category.name)
            ).all()

        self.category_input.clear()

        for category in categories:
            self.category_input.addItem(
                category.name,
                category.id,
            )

        self.category_input.setCurrentIndex(-1)

    def _build_ui(self) -> None:
        """Создаёт элементы формы."""
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Например, iPhone 16")

        self.category_input = QComboBox()
        self.category_input.setPlaceholderText(
            "Выберите категорию"
        )
        self._style_combo_popup(self.category_input)

        self.brand_input = QLineEdit()
        self.brand_input.setPlaceholderText("Необязательно")

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Необязательно")

        self.specification_input = QLineEdit()
        self.specification_input.setPlaceholderText(
            "Необязательно"
        )
        self.stock_input = QLineEdit()
        self.stock_input.setPlaceholderText("0")    

        self.min_stock_input = QLineEdit()
        self.min_stock_input.setPlaceholderText("0")

        form.addRow("Название *", self.name_input)
        
        

        category_layout = QHBoxLayout()
        category_layout.addWidget(self.category_input)

        self.add_category_button = QPushButton("+")
        self.add_category_button.setFixedWidth(40)
        self.add_category_button.setToolTip(
            "Создать новую категорию"
        )
        self.add_category_button.clicked.connect(
            self._add_category
        )

        category_layout.addWidget(self.add_category_button)
        form.addRow("Категория *", category_layout)

        form.addRow("Бренд", self.brand_input)
        form.addRow("Модель", self.model_input)
        form.addRow("Характеристики", self.specification_input)
        form.addRow("Количество на складе", self.stock_input)
        form.addRow("Минимальный остаток", self.min_stock_input)

        layout.addLayout(form)

        self.save_button = QPushButton("Сохранить")
        self.cancel_button = QPushButton("Отмена")
        self.deactivate_button = QPushButton("Деактивировать товар")
        self.deactivate_button.clicked.connect(self._deactivate_product)
        self.deactivate_button.hide()

        self.save_button.clicked.connect(self._save_product)
        self.cancel_button.clicked.connect(self.reject)

        layout.addWidget(self.save_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.deactivate_button)

    def _deactivate_product(self) -> None:
        if self.product_id is None:
            return

        answer = QMessageBox.question(
            self,
            "Деактивация товара",
            "Вы действительно хотите деактивировать этот товар?\n"
            "Он исчезнет из активного каталога.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            with SessionLocal() as session:
                product = session.get(Product, self.product_id)

                if product is None:
                    QMessageBox.warning(
                        self,
                        "Товар не найден",
                        "Не удалось найти товар.",
                    )
                    return

                stock_items = session.scalars(
                    select(StockItem).where(
                        StockItem.product_id == self.product_id,
                        StockItem.status == "in_stock",
                    )
                ).first()

                if product.stock_quantity > 0 or stock_items is not None:
                    QMessageBox.warning(
                        self,
                        "Нельзя деактивировать",
                        "У товара ещё есть остатки на складе.\n"
                        "Сначала необходимо распродать или списать их.",
                    )
                    return

                product.is_active = False
                session.commit()

            QMessageBox.information(
                self,
                "Готово",
                "Товар успешно деактивирован.",
            )
            self.accept()

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось деактивировать товар:\n{error}",
            )

    def _save_product(self) -> None:
        """Создаёт новый товар или сохраняет изменения."""
        name = self.name_input.text().strip()
        category_id = self.category_input.currentData()
        brand = self.brand_input.text().strip() or None
        model = self.model_input.text().strip() or None
        specification = (
            self.specification_input.text().strip() or None
        )

        if not name:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Введите название товара.",
            )
            return

        if category_id is None:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Выберите категорию товара.",
            )
            return

        min_stock_text = self.min_stock_input.text().strip()

        if not min_stock_text:
            min_stock_quantity = 0
        elif not min_stock_text.isdigit():
            QMessageBox.warning(
                self,
                "Ошибка",
                "Минимальный остаток должен быть целым "
                "неотрицательным числом.",
            )
            return
        else:
            min_stock_quantity = int(min_stock_text)



        stock_text = self.stock_input.text().strip()
        
        if not stock_text:
            stock_quantity = 0
        elif not stock_text.isdigit():
            QMessageBox.warning(
                self,
                "Ошибка",
                "Количество на складе должно быть целым "
                "неотрицательным числом.",
            )
            return
        else:
            stock_quantity = int(stock_text)

        try:
            with SessionLocal() as session:
                if self.product_id is None:
                    last_product = session.scalar(
                        select(Product)
                        .order_by(Product.id.desc())
                        .limit(1)
                    )

                    next_number = (
                        last_product.id + 1
                        if last_product
                        else 1
                    )
                    sku = f"PRD_{next_number:06d}"

                    product = Product(
                        category_id=category_id,
                        sku=sku,
                        name=name,
                        brand=brand,
                        model=model,
                        specification=specification,
                        min_stock_quantity=min_stock_quantity,
                        stock_quantity=stock_quantity,   
                    )

                    session.add(product)
                    success_message = (
                        f"Товар «{name}» успешно добавлен."
                    )

                else:
                    product = session.get(
                        Product,
                        self.product_id,
                    )

                    if product is None:
                        QMessageBox.warning(
                            self,
                            "Товар не найден",
                            "Не удалось найти товар для изменения.",
                        )
                        return

                    product.category_id = category_id
                    product.name = name
                    product.brand = brand
                    product.model = model
                    product.specification = specification
                    product.stock_quantity = stock_quantity
                    product.min_stock_quantity = (
                        min_stock_quantity
                    )

                    success_message = (
                        f"Изменения товара «{name}» сохранены."
                    )

                session.commit()

            QMessageBox.information(
                self,
                "Готово",
                success_message,
            )
            self.accept()

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить товар:\n{error}",
            )
