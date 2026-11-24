from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
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
    is_system_category_code,
    list_categories,
    list_distinct_brands_and_models,
    restore_product,
    save_product,
)
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_dialog import CategoryDialog
from app.ui.widgets import configure_dialog_buttons, make_button, show_toast, style_combo


class ProductDialog(QDialog):
    """Окно добавления и редактирования карточки товара в едином модуле «Товары и склад»."""

    def __init__(
        self,
        parent=None,
        product_id: int | None = None,
        initial_barcode: str = "",
    ) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.initial_barcode = (initial_barcode or "").strip()
        self.created_product_id: int | None = None
        self._in_stock_imeis_count = 0
        self._is_active = True
        self._current_stock_qty = 0

        self.setWindowTitle(
            "Katalogda täze haryt" if self.product_id is None else "Harydy üýtgetmek"
        )
        self.setMinimumWidth(480)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_categories()
        self._setup_completers()

        if self.product_id is not None:
            self._load_product()
        else:
            self._apply_remembered_draft()
            if self.initial_barcode:
                self.barcode_input.setText(self.initial_barcode)

        self.name_input.setFocus()

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
        self.name_input.setPlaceholderText("Mysal: 14 Pro Max ýa-da Note 15 Pro Plus")
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
        self.brand_input.setPlaceholderText(
            "Harydyň / aksessuaryň brendi (mysal: Blueo, Hoco, Remax, Apple)"
        )
        form.addRow("Brend", self.brand_input)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText(
            "Enjam modeli / seriýasy (mysal: iPhone, Samsung, Xiaomi)"
        )
        form.addRow("Model", self.model_input)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("EAN-13 / ştrihkod skan et ýa-da ýaz (hökmany däl)")
        form.addRow("Ştrihkod (Barcode)", self.barcode_input)

        self.specification_input = QLineEdit()
        self.specification_input.setPlaceholderText(
            "Gutynyň üstündäki aýratyn sözler/kodlar (vergul bilen): X88, Anti-Dust, 9D..."
        )
        form.addRow("Referens (OCR sözler)", self.specification_input)

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
        self.deactivate_button = make_button("📦 Arhiwe geçir", "danger")
        self.deactivate_button.clicked.connect(self._toggle_archive_product)
        self.deactivate_button.hide()
        footer.addWidget(self.deactivate_button)

        self.clear_btn = make_button("↺ Arassala")
        self.clear_btn.setToolTip("Öňki doldurylan öýjükleri arassalamak")
        self.clear_btn.clicked.connect(self._clear_fields)
        if self.product_id is not None:
            self.clear_btn.hide()
        footer.addWidget(self.clear_btn)
        footer.addStretch()

        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Harydy ýatda sakla", "primary")
        save_btn.clicked.connect(self._save_product)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)

    def _setup_completers(self) -> None:
        try:
            brands, models = list_distinct_brands_and_models()
        except SQLAlchemyError:
            brands, models = [], []

        brand_completer = QCompleter(brands, self)
        brand_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        brand_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.brand_input.setCompleter(brand_completer)

        model_completer = QCompleter(models, self)
        model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.model_input.setCompleter(model_completer)

    def _apply_remembered_draft(self) -> None:
        remember = SettingsService.get_product_remember_fields()
        draft = SettingsService.get_last_product_draft()
        if not draft:
            return

        if remember.get("category") and draft.get("category_id") is not None:
            idx = self.category_input.findData(draft.get("category_id"))
            if idx >= 0:
                self.category_input.setCurrentIndex(idx)

        if remember.get("brand") and draft.get("brand"):
            self.brand_input.setText(str(draft["brand"]))

        if remember.get("model") and draft.get("model"):
            self.model_input.setText(str(draft["model"]))

        if remember.get("reference") and draft.get("reference"):
            self.specification_input.setText(str(draft["reference"]))

        if remember.get("cost"):
            raw_cost = draft.get("cost")
            if raw_cost is not None:
                try:
                    self.cost_spin.setValue(max(0.0, float(raw_cost)))
                except (ValueError, TypeError):
                    pass
            raw_curr = str(draft.get("cost_currency") or "").strip().upper()
            if raw_curr in ("USD", "TMT"):
                self.cost_curr_combo.setCurrentText(raw_curr)

        if remember.get("min_stock") and draft.get("min_stock") is not None:
            try:
                self.min_stock_spin.setValue(max(0, int(draft["min_stock"])))
            except (ValueError, TypeError):
                pass

        if remember.get("name") and draft.get("name"):
            self.name_input.setText(str(draft["name"]))

        if remember.get("barcode") and not self.initial_barcode and draft.get("barcode"):
            self.barcode_input.setText(str(draft["barcode"]))

    def _clear_fields(self) -> None:
        self.name_input.clear()
        self.brand_input.clear()
        self.model_input.clear()
        self.barcode_input.clear()
        self.specification_input.clear()
        self.stock_spin.setValue(0)
        self.cost_spin.setValue(0.0)
        self.cost_curr_combo.setCurrentText("USD")
        self.min_stock_spin.setValue(SettingsService.get_default_min_stock())
        self.name_input.setFocus()

    def _load_categories(self) -> None:
        self.category_input.clear()
        for category in list_categories(active_only=True):
            if is_system_category_code(category.code):
                continue
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

            self._is_active = bool(product.is_active)
            self._current_stock_qty = product.stock_quantity
            self.deactivate_button.setText(
                "📦 Arhiwe geçir" if self._is_active else "♻ Arhiwden dikelt"
            )
            self.deactivate_button.show()
            self._in_stock_imeis_count = in_stock_imeis
            self.name_input.setText(product.name)
            self.brand_input.setText(product.brand or "")
            self.model_input.setText(product.model or "")
            self.barcode_input.setText(product.barcode or "")
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
                        label = cat.name if cat.is_active else f"{cat.name} (işjeň däl)"
                        self.category_input.addItem(label, cat.id)
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
                barcode=self.barcode_input.text(),
            )
            self.created_product_id = product.id
            if self.cost_spin.value() > 0:
                SettingsService.set_product_default_cost(
                    product.id,
                    self.cost_spin.value(),
                    self.cost_curr_combo.currentText(),
                )
            if self.product_id is None:
                SettingsService.save_last_product_draft({
                    "category_id": self.category_input.currentData(),
                    "brand": self.brand_input.text().strip(),
                    "model": self.model_input.text().strip(),
                    "reference": self.specification_input.text().strip(),
                    "cost": float(self.cost_spin.value()),
                    "cost_currency": self.cost_curr_combo.currentText(),
                    "min_stock": int(self.min_stock_spin.value()),
                    "name": self.name_input.text().strip(),
                    "barcode": self.barcode_input.text().strip(),
                })
            msg = (
                f"«{product.name}» harydy üstünlikli goşuldy."
                if self.product_id is None
                else f"«{product.name}» harydynyň üýtgeşmeleri ýatda saklandy."
            )
            show_toast(self.parentWidget() or self, msg, kind="success")
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýatda saklama ýalňyşlygy", f"Harydy ýatda saklap bolmady:\n{err}")

    def _toggle_archive_product(self) -> None:
        if self.product_id is None:
            return
        if not self._is_active:
            try:
                restore_product(self.product_id)
                show_toast(
                    self.parentWidget() or self,
                    "Haryt arhiwden dikeldildi we işjeň kataloga gaýtaryldy.",
                    kind="success",
                )
                self.accept()
            except (ValueError, SQLAlchemyError) as err:
                QMessageBox.warning(self, "Ýalňyşlyk", str(err))
            return

        stock_warn = ""
        if self._current_stock_qty > 0 or self._in_stock_imeis_count > 0:
            stock_warn = (
                f"\n\n⚠ Üns beriň: skladda entek {self._current_stock_qty} sany "
                f"(IMEI: {self._in_stock_imeis_count}) bar.\n"
                "Arhiwe geçirileninde galyndylar we taryh saklanar, ýöne haryt satyşda görünmez."
            )
        answer = QMessageBox.question(
            self,
            "Harydy arhiwe geçirmek",
            "Bu harydy arhiwe geçirmek isleýärsiňizmi?\n"
            "Ol işjeň katalogdan gizlener (islendik wagt arhiwden dikeldip bolýar)."
            + stock_warn,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deactivate_product(self.product_id, force=True)
            show_toast(self.parentWidget() or self, "Haryt arhiwe geçirildi.", kind="success")
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Arhiwe geçirip bolmaýar", str(err))
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Harydy arhiwe geçirip bolmady:\n{err}")
