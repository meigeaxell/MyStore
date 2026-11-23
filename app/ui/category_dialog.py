from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.product_repository import create_category
from app.ui import theme
from app.ui.widgets import configure_dialog_buttons, make_button, show_toast


class CategoryDialog(QDialog):
    """Окно создания новой категории товаров."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Täze kategoriýa")
        self.setMinimumWidth(380)
        self.setStyleSheet(theme.STYLE)
        self.created_category_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        title = QLabel("Kategoriýa döretmek")
        title.setObjectName("cardTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Mysal: Smartfonlar, Çehollar, Zarýad enjamlary")
        form.addRow("Kategoriýanyň ady *", self.name_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Kategoriýa döret", "primary")
        save_btn.clicked.connect(self._save_category)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        configure_dialog_buttons(self, save_btn, cancel_btn)
        self.name_input.setFocus()

    def _save_category(self) -> None:
        try:
            category = create_category(self.name_input.text())
            self.created_category_id = category.id
            show_toast(
                self.parentWidget() or self,
                f"«{category.name}» kategoriýasy üstünlikli döredildi.",
                kind="success",
            )
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Kategoriýa döredip bolmady:\n{err}")
