
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.engine import SessionLocal
from app.models.category import Category


class CategoryDialog(QDialog):
    """Окно добавления категории."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Новая категория")
        self.setMinimumWidth(350)

        self.created_category_id = None

        self.setStyleSheet("""
            QDialog {
                background-color: #F6F7F9;
                color: #1D2939;
            }
            QLineEdit {
                background-color: white;
                color: #1D2939;
                border: 1px solid #E8EBF0;
                border-radius: 8px;
                padding: 8px;
            }
            QPushButton {
                background-color: #F58A2E;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 9px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E87922;
            }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Например, Смартфоны")

        form.addRow("Название категории *", self.name_input)
        layout.addLayout(form)

        self.save_button = QPushButton("Создать категорию")
        self.cancel_button = QPushButton("Отмена")

        self.save_button.clicked.connect(self._save_category)
        self.cancel_button.clicked.connect(self.reject)

        layout.addWidget(self.save_button)
        layout.addWidget(self.cancel_button)

    def _save_category(self) -> None:
        name = self.name_input.text().strip()

        if not name:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Введите название категории.",
            )
            return

        try:
            with SessionLocal() as session:
                existing = session.scalar(
                    select(Category).where(
                        func.lower(Category.name) == name.lower()
                    )
                )

                if existing:
                    QMessageBox.warning(
                        self,
                        "Категория существует",
                        "Категория с таким названием уже есть.",
                    )
                    return

                codes = session.scalars(
                    select(Category.code)
                ).all()

                numbers = [
                    int(code.replace("CAT_", ""))
                    for code in codes
                    if code.startswith("CAT_")
                    and code.replace("CAT_", "").isdigit()
                ]

                next_number = max(numbers, default=0) + 1
                code = f"CAT_{next_number:03d}"

                category = Category(
                    name=name,
                    code=code,
                )

                session.add(category)
                session.commit()
                session.refresh(category)

                self.created_category_id = category.id

            QMessageBox.information(
                self,
                "Готово",
                f"Категория «{name}» создана.",
            )

            self.accept()

        except IntegrityError:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось создать категорию. Возможно, такой код уже существует.",
            )
