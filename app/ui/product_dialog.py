from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.repositories.product_repository import (
    deactivate_product,
    get_product_with_devices,
    list_categories,
    save_product,
)
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_dialog import CategoryDialog
from app.ui.widgets import make_button, style_combo


class ProductDialog(QDialog):
    """Окно добавления и редактирования карточки товара в едином модуле «Товары и склад»."""

    def __init__(self, parent=None, product_id: int | None = None) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.created_product_id: int | None = None
        self._in_stock_imeis_count = 0

        self.setWindowTitle(
            "Katalogda täze haryt" if self.product_id is None else "Harydy üýtgetmek"
        )
        self.setMinimumWidth(460)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_categories()

        if self.product_id is not None:
            self._load_product()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel(
            "Kataloga haryt goşmak" if self.product_id is None else "Haryt karty"
        )
        title.setObjectName("pageTitle")
        root.addWidget(title)

        hint = QLabel(
            "Telefonlar üçin haryt modelini dörediň, aýratyn enjamlary (IMEI) bolsa "
            "«+ Enjam goş (IMEI)» arkaly ýa-da alyşda goşuň."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Mysal: iPhone 16 Pro 256GB ýa-da Çehol Silicone Case")
        form.addRow("Harydyň ady *", self.name_input)

        cat_row = QHBoxLayout()
        self.category_input = style_combo(QComboBox())
        self.category_input.setPlaceholderText("Kategoriýa saýlaň")
        cat_row.addWidget(self.category_input, 1)

        add_cat_btn = make_button("+ Kategoriýa")
        add_cat_btn.setToolTip("Täze kategoriýa döretmek")
        add_cat_btn.clicked.connect(self._add_category)
        cat_row.addWidget(add_cat_btn)
        form.addRow("Kategoriýa *", cat_row)

        self.brand_input = QLineEdit()
        self.brand_input.setPlaceholderText("Mysal: Apple, Samsung, Xiaomi (hökmany däl)")
        form.addRow("Brend", self.brand_input)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Mysal: A3102 / S928B (hökmany däl)")
        form.addRow("Model", self.model_input)

        self.specification_input = QLineEdit()
        self.specification_input.setPlaceholderText("Reňk, ýat, aýratynlyklar (hökmany däl)")
        form.addRow("Aýratynlyklar", self.specification_input)

        self.stock_spin = QSpinBox()
        self.stock_spin.setRange(0, 1000000)
        self.stock_spin.setValue(0)
        form.addRow("Skladdaky sany", self.stock_spin)

        cost_row = QHBoxLayout()
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.cost_curr_combo)
        form.addRow("1 sanynyň öz bahasy", cost_row)

        self.min_stock_spin = QSpinBox()
        self.min_stock_spin.setRange(0, 100000)
        default_min = SettingsService.get_default_min_stock()
        self.min_stock_spin.setValue(default_min if self.product_id is None else 0)
        form.addRow("Iň az galyndy (sany)", self.min_stock_spin)

        root.addLayout(form)

        self.imei_note_label = QLabel()
        self.imei_note_label.setObjectName("mutedText")
        self.imei_note_label.setWordWrap(True)
        self.imei_note_label.hide()
        root.addWidget(self.imei_note_label)

        footer = QHBoxLayout()
        self.deactivate_button = make_button("Öçür (arhiwe geçir)", "danger")
        self.deactivate_button.clicked.connect(self._deactivate_product)
        self.deactivate_button.hide()
        footer.addWidget(self.deactivate_button)
        footer.addStretch()

        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Harydy ýatda sakla", "primary")
        save_btn.clicked.connect(self._save_product)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

    def _load_categories(self) -> None:
        self.category_input.clear()
        for category in list_categories(active_only=True):
            self.category_input.addItem(category.name, category.id)
        if self.category_input.count() > 0 and self.product_id is None:
            self.category_input.setCurrentIndex(0)

    def _add_category(self) -> None:
        dlg = CategoryDialog(self)
        if dlg.exec():
            self._load_categories()
            idx = self.category_input.findData(dlg.created_category_id)
            if idx >= 0:
                self.category_input.setCurrentIndex(idx)

    def _load_product(self) -> None:
        try:
            product, in_stock_imeis, _items = get_product_with_devices(self.product_id)
            if product is None:
                QMessageBox.warning(self, "Haryt tapylmady", "Saýlanan haryt tapylmady.")
                self.reject()
                return

            self.deactivate_button.show()
            self._in_stock_imeis_count = in_stock_imeis
            self.name_input.setText(product.name)
            self.brand_input.setText(product.brand or "")
            self.model_input.setText(product.model or "")
            self.specification_input.setText(product.specification or "")
            self.stock_spin.setMinimum(in_stock_imeis)
            self.stock_spin.setValue(product.stock_quantity)
            self.min_stock_spin.setValue(product.min_stock_quantity)

            saved_cost = SettingsService.get_product_default_cost(product.id)
            if saved_cost is not None:
                c_val, c_cur = saved_cost
                self.cost_spin.setValue(float(c_val))
                self.cost_curr_combo.setCurrentText(c_cur)
            else:
                with SessionLocal() as session:
                    latest_pi = session.execute(
                        select(PurchaseItem, Purchase)
                        .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
                        .where(
                            PurchaseItem.product_id == product.id,
                            Purchase.status == "active",
                        )
                        .order_by(Purchase.purchase_date.desc(), PurchaseItem.id.desc())
                    ).first()
                    if latest_pi:
                        pi, pur = latest_pi
                        self.cost_spin.setValue(float(pi.unit_cost))
                        self.cost_curr_combo.setCurrentText(pur.currency)

            if in_stock_imeis > 0:
                self.imei_note_label.setText(
                    f"ℹ Skladda {in_stock_imeis} sany aýratyn enjam (IMEI) hasaba alnan. "
                    f"Jemi sany {in_stock_imeis} sanydan az bolup bilmez."
                )
                self.imei_note_label.show()

            idx = self.category_input.findData(product.category_id)
            if idx >= 0:
                self.category_input.setCurrentIndex(idx)
            else:
                for cat in list_categories(active_only=False):
                    if cat.id == product.category_id:
                        self.category_input.addItem(f"{cat.name} (işjeň däl)", cat.id)
                        self.category_input.setCurrentIndex(self.category_input.count() - 1)
                        break
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Ýükleme ýalňyşlygy", f"Harydy ýükläp bolmady:\n{error}")
            self.reject()

    def _save_product(self) -> None:
        try:
            product = save_product(
                product_id=self.product_id,
                name=self.name_input.text(),
                category_id=self.category_input.currentData(),
                brand=self.brand_input.text(),
                model=self.model_input.text(),
                specification=self.specification_input.text(),
                stock_quantity=self.stock_spin.value(),
                min_stock_quantity=self.min_stock_spin.value(),
            )
            self.created_product_id = product.id
            if self.cost_spin.value() > 0:
                SettingsService.set_product_default_cost(
                    product.id,
                    self.cost_spin.value(),
                    self.cost_curr_combo.currentText(),
                )
            msg = (
                f"«{product.name}» ({product.sku}) harydy üstünlikli goşuldy."
                if self.product_id is None
                else f"«{product.name}» harydynyň üýtgeşmeleri ýatda saklandy."
            )
            QMessageBox.information(self, "Taýýar", msg)
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýatda saklama ýalňyşlygy", f"Harydy ýatda saklap bolmady:\n{err}")

    def _deactivate_product(self) -> None:
        if self.product_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Harydy öçürmek",
            "Bu harydy hakykatdan hem öçürmek (arhiwe geçirmek) isleýärsiňizmi?\n"
            "Ol işjeň katalogdan gizlener.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deactivate_product(self.product_id)
            QMessageBox.information(self, "Taýýar", "Haryt üstünlikli öçürildi.")
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Öçürip bolmaýar", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Harydy öçürip bolmady:\n{err}")
