
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category

DIALOG_STYLE = """
    QDialog {
        background-color: #F6F7F9;
        color: #1D2939;
    }
    QLabel {
        color: #1D2939;
        font-size: 13px;
    }
    QLineEdit {
        background-color: white;
        color: #1D2939;
        border: 1px solid #E8EBF0;
        border-radius: 8px;
        padding: 9px 10px;
        selection-background-color: #FFE6CC;
    }
    QLineEdit:focus {
        border: 1px solid #F58A2E;
    }
    QListWidget {
        background-color: white;
        color: #1D2939;
        border: 1px solid #E8EBF0;
        border-radius: 8px;
        padding: 5px;
        outline: none;
    }
    QListWidget::item {
        padding: 10px;
        border-radius: 5px;
        margin: 2px;
    }
    QListWidget::item:selected {
        background-color: #FFE6CC;
        color: #1D2939;
    }
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
"""


class CategoryRenameDialog(QDialog):
    def __init__(self, current_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Переименование категории")
        self.setMinimumWidth(340)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Новое название категории"))

        self.name_input = QLineEdit(current_name)
        self.name_input.selectAll()
        layout.addWidget(self.name_input)

        buttons = QHBoxLayout()
        save_button = QPushButton("Сохранить")
        cancel_button = QPushButton("Отмена")

        save_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def get_name(self) -> str:
        return self.name_input.text().strip()


class CategoryManagementDialog(QDialog):
    """Окно управления категориями."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Управление категориями")
        self.setMinimumSize(420, 450)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Список категорий")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        self.category_list = QListWidget()
        self.category_list.setSpacing(2)
        layout.addWidget(self.category_list)

        buttons = QHBoxLayout()

        self.rename_button = QPushButton("Переименовать")
        self.deactivate_button = QPushButton("Деактивировать")
        self.close_button = QPushButton("Закрыть")

        self.rename_button.clicked.connect(self._rename_category)
        self.deactivate_button.clicked.connect(self._deactivate_category)
        self.close_button.clicked.connect(self.accept)

        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.deactivate_button)

        layout.addLayout(buttons)
        layout.addWidget(self.close_button)

        self._load_categories()

    def _load_categories(self) -> None:
        self.category_list.clear()

        try:
            with SessionLocal() as session:
                categories = session.scalars(
                    select(Category).order_by(Category.name)
                ).all()

                for category in categories:
                    status = "" if category.is_active else "  •  неактивна"
                    item = QListWidgetItem(category.name + status)
                    item.setData(Qt.ItemDataRole.UserRole, category.id)
                    item.setData(
                        Qt.ItemDataRole.UserRole + 1,
                        category.is_active,
                    )
                    self.category_list.addItem(item)

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось загрузить категории:\n{error}",
            )

    def _selected_category(self):
        item = self.category_list.currentItem()

        if item is None:
            QMessageBox.warning(
                self,
                "Категория не выбрана",
                "Сначала выберите категорию.",
            )
            return None

        return (
            item.data(Qt.ItemDataRole.UserRole),
            item.data(Qt.ItemDataRole.UserRole + 1),
        )

    def _rename_category(self) -> None:
        selected = self._selected_category()
        if selected is None:
            return

        category_id, _ = selected
        item = self.category_list.currentItem()
        old_name = item.text().split("  •  неактивна")[0]

        dialog = CategoryRenameDialog(old_name, self)
        if not dialog.exec():
            return

        new_name = dialog.get_name()

        if not new_name:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Название категории не может быть пустым.",
            )
            return

        try:
            with SessionLocal() as session:
                duplicate = session.scalar(
                    select(Category).where(
                        func.lower(Category.name) == new_name.lower(),
                        Category.id != category_id,
                    )
                )

                if duplicate:
                    QMessageBox.warning(
                        self,
                        "Категория существует",
                        "Категория с таким названием уже есть.",
                    )
                    return

                category = session.get(Category, category_id)
                if category is None:
                    return

                category.name = new_name
                session.commit()

            self._load_categories()

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось переименовать категорию:\n{error}",
            )

    def _deactivate_category(self) -> None:
        selected = self._selected_category()
        if selected is None:
            return

        category_id, is_active = selected

        if not is_active:
            QMessageBox.information(
                self,
                "Категория уже неактивна",
                "Эта категория уже деактивирована.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Деактивация категории",
            "Деактивировать выбранную категорию?\n"
            "Связанные товары сохранятся, "
            "но категорию нельзя будет выбирать "
            "при создании новых товаров.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            with SessionLocal() as session:
                category = session.get(Category, category_id)
                if category is None:
                    return

                category.is_active = False
                session.commit()

            self._load_categories()

        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось деактивировать категорию:\n{error}",
            )
