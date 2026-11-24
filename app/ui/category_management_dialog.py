from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.product_repository import (
    deactivate_category,
    is_system_category_code,
    list_categories,
    rename_category,
)
from app.ui import theme
from app.ui.category_dialog import CategoryDialog
from app.ui.widgets import configure_dialog_buttons, make_button, show_toast


class CategoryManagementDialog(QDialog):
    """Окно управления категориями товаров (добавление, переименование, деактивация)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kategoriýalary dolandyrmak")
        self.setMinimumSize(460, 460)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Haryt kategoriýalary")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()

        add_btn = make_button("+ Täze kategoriýa", "primary")
        add_btn.clicked.connect(self._add_category)
        header.addWidget(add_btn)
        root.addLayout(header)

        self.category_list = QListWidget()
        self.category_list.setSpacing(2)
        self.category_list.currentItemChanged.connect(self._update_buttons_state)
        root.addWidget(self.category_list, 1)

        actions = QHBoxLayout()
        self.rename_button = make_button("Adyny üýtget")
        self.rename_button.clicked.connect(self._rename_category)
        self.deactivate_button = make_button("Öçür", "danger")
        self.deactivate_button.clicked.connect(self._deactivate_category)
        close_button = make_button("Ýap")
        close_button.clicked.connect(self.accept)

        actions.addWidget(self.rename_button)
        actions.addWidget(self.deactivate_button)
        actions.addStretch()
        actions.addWidget(close_button)
        root.addLayout(actions)

        configure_dialog_buttons(self, close_button)
        self._load_categories()

    def _load_categories(self) -> None:
        self.category_list.clear()
        try:
            for cat in list_categories(active_only=False):
                is_system = is_system_category_code(cat.code)
                markers: list[str] = []
                if is_system:
                    markers.append("🔒 Hemişelik")
                if not cat.is_active:
                    markers.append("işjeň däl")
                suffix = f"  •  {'  •  '.join(markers)}" if markers else ""
                item = QListWidgetItem(f"{cat.name}{suffix}")
                item.setData(Qt.ItemDataRole.UserRole, cat.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, cat.is_active)
                item.setData(Qt.ItemDataRole.UserRole + 2, cat.name)
                item.setData(Qt.ItemDataRole.UserRole + 3, is_system)
                self.category_list.addItem(item)
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Kategoriýalary ýükläp bolmady:\n{error}")
        self._update_buttons_state()

    def _update_buttons_state(self, *_args) -> None:
        item = self.category_list.currentItem()
        is_system = bool(item.data(Qt.ItemDataRole.UserRole + 3)) if item is not None else False
        self.rename_button.setEnabled(not is_system)
        self.deactivate_button.setEnabled(not is_system)

    def _add_category(self) -> None:
        dlg = CategoryDialog(self)
        if dlg.exec():
            self._load_categories()

    def _selected_category(self) -> tuple[int, bool, str, bool] | None:
        item = self.category_list.currentItem()
        if item is None:
            show_toast(self, "Ilki sanawdan kategoriýa saýlaň.", kind="info")
            return None
        return (
            item.data(Qt.ItemDataRole.UserRole),
            item.data(Qt.ItemDataRole.UserRole + 1),
            item.data(Qt.ItemDataRole.UserRole + 2),
            bool(item.data(Qt.ItemDataRole.UserRole + 3)),
        )

    def _rename_category(self) -> None:
        selected = self._selected_category()
        if selected is None:
            return
        cat_id, _active, old_name, is_system = selected
        if is_system:
            show_toast(
                self,
                "Hemişelik ulgam kategoriýasynyň adyny üýtgedip bolmaýar.",
                kind="warning",
            )
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Kategoriýanyň adyny üýtgetmek",
            "Kategoriýanyň täze ady:",
            text=old_name,
        )
        if not ok:
            return
        try:
            rename_category(cat_id, new_name)
            self._load_categories()
            show_toast(self, "Kategoriýanyň ady täzelendi.", kind="success")
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Kategoriýanyň adyny üýtgedip bolmady:\n{err}")

    def _deactivate_category(self) -> None:
        selected = self._selected_category()
        if selected is None:
            return
        cat_id, is_active, name, is_system = selected
        if is_system:
            show_toast(
                self,
                "Hemişelik ulgam kategoriýasyny öçürip bolmaýar.",
                kind="warning",
            )
            return
        if not is_active:
            show_toast(self, "Bu kategoriýa eýýäm öçürilen.", kind="info")
            return

        answer = QMessageBox.question(
            self,
            "Kategoriýany öçürmek",
            f"«{name}» kategoriýasyny öçürmek isleýärsiňizmi?\n"
            "Bar bolan harytlar saklanar, ýöne täze harytlar üçin bu kategoriýany saýlap bolmaz.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            deactivate_category(cat_id)
            self._load_categories()
            show_toast(self, f"«{name}» kategoriýasy öçürildi.", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Kategoriýany öçürip bolmady:\n{err}")
