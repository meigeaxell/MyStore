from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund
from app.repositories.product_repository import (
    find_products_by_barcode,
    get_low_stock_products,
)
from app.services.finance_service import FinanceService
from app.services.purchase_service import (
    PERSONAL_SOURCE_LABEL,
    add_purchase_payment,
    add_purchase_refund,
    cancel_purchase,
    create_purchase,
    get_purchase_balance,
    get_supplier_debt,
    is_personal_source_purchase,
)
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.selection_dialogs import CatalogProductSelectorDialog
from app.ui.widgets import (
    NUM_ALIGN,
    ClickableCard,
    align_numeric_columns,
    configure_dialog_buttons,
    configure_table,
    make_button,
    make_icon_button,
    make_stat_card,
    money_str,
    show_toast,
    style_combo,
)


def money_input(maximum: float = 999999999) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(0, maximum)
    field.setDecimals(2)
    field.setSingleStep(10)
    field.setMinimumHeight(36)
    return field


def rate_input() -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(0.0001, 999999.9999)
    field.setDecimals(4)
    field.setValue(float(SettingsService.get_default_exchange_rate()))
    field.setSingleStep(0.1)
    field.setMinimumHeight(36)
    return field


def fill_table(table: QTableWidget, rows: list[tuple]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if column > 0:
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, column, cell)


class ImeiEntryDialog(QDialog):
    """Окно ввода IMEI для товарной позиции закупки."""

    def __init__(
        self,
        product_name: str,
        max_quantity: int,
        existing_imeis: list[dict] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"IMEI — {product_name}")
        self.setMinimumSize(640, 440)
        self.setStyleSheet(theme.STYLE)

        self.max_quantity = max_quantity
        self.imei_list: list[dict] = list(existing_imeis or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(f"Enjamlar: {product_name}")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.counter_label = QLabel()
        self.counter_label.setObjectName("mutedText")
        root.addWidget(self.counter_label)

        form_row = QHBoxLayout()
        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 (hökmany)*")
        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa №")
        self.cond_input = style_combo(QComboBox())
        self.cond_input.addItem("Täze", "new")
        self.cond_input.addItem("B/U", "used")

        add_btn = make_button("+ IMEI goş", "secondary")
        add_btn.clicked.connect(self._add_imei)
        self.imei1_input.returnPressed.connect(self._add_imei)
        self.imei2_input.returnPressed.connect(self._add_imei)
        self.sn_input.returnPressed.connect(self._add_imei)

        form_row.addWidget(self.imei1_input, 2)
        form_row.addWidget(self.imei2_input, 2)
        form_row.addWidget(self.sn_input, 1)
        form_row.addWidget(self.cond_input)
        form_row.addWidget(add_btn)
        root.addLayout(form_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["IMEI 1", "IMEI 2", "Seriýa №", "Ýagdaýy"])
        configure_table(self.table, stretch_col=[0, 1], row_height=42)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        rem_btn = make_button("Saýlanan IMEI-ni poz", "danger")
        rem_btn.clicked.connect(self._remove_selected)
        footer.addWidget(rem_btn)
        footer.addStretch()

        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Taýýar", "primary")
        save_btn.clicked.connect(self.accept)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)
        self._refresh_table()
        self.imei1_input.setFocus()

    def _add_imei(self) -> None:
        if len(self.imei_list) >= self.max_quantity:
            QMessageBox.warning(
                self,
                "Çäk doldy",
                f"IMEI sany setirdäki sanyndan ({self.max_quantity}) köp bolup bilmez.",
            )
            return
        imei1 = self.imei1_input.text().strip()
        imei2 = self.imei2_input.text().strip() or None
        sn = self.sn_input.text().strip() or None
        cond = self.cond_input.currentData()

        if not imei1:
            QMessageBox.warning(self, "Ýalňyşlyk", "IMEI 1 giriziň.")
            return
        if imei2 and imei1 == imei2:
            QMessageBox.warning(self, "Ýalňyşlyk", "IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")
            return

        for rec in self.imei_list:
            existing_set = {rec["imei1"]}
            if rec.get("imei2"):
                existing_set.add(rec["imei2"])
            if imei1 in existing_set or (imei2 and imei2 in existing_set):
                QMessageBox.warning(self, "Gaýtalanma", "Bu IMEI eýýäm sanawa goşuldy.")
                return

        self.imei_list.append({
            "imei1": imei1,
            "imei2": imei2,
            "serial_number": sn,
            "condition": cond,
        })
        self.imei1_input.clear()
        self.imei2_input.clear()
        self.sn_input.clear()
        self._refresh_table()

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.imei_list):
            self.imei_list.pop(row)
            self._refresh_table()

    def _refresh_table(self) -> None:
        self.counter_label.setText(
            f"Goşulan IMEI: {len(self.imei_list)} / {self.max_quantity} sany "
            "(aksessuarlar üçin boş galdyryp bolýar)"
        )
        rows = [
            (
                r["imei1"],
                r.get("imei2") or "—",
                r.get("serial_number") or "—",
                "Täze" if r.get("condition", "new") == "new" else "B/U",
            )
            for r in self.imei_list
        ]
        fill_table(self.table, rows)


class PurchaseDialog(QDialog):
    """Окно создания новой закупки с адаптивной вёрсткой, таблицами и визуальным выбором товара."""

    def __init__(self, parent=None, initial_data: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Täze alyş")
        self.resize(900, 740)
        self.setMinimumSize(720, 540)
        self.setStyleSheet(theme.STYLE)

        self.items: list[dict] = []
        self.payments: list[dict] = []
        self.products: list[Product] = []
        self.suppliers: list[str] = []

        self._load_products()
        self._build_ui()
        if initial_data:
            self._apply_initial_data(initial_data)

    def _load_products(self) -> None:
        with SessionLocal() as session:
            self.products = list(
                session.scalars(
                    select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
                ).all()
            )
            raw_sups = session.scalars(
                select(Purchase.supplier_name)
                .where(Purchase.supplier_name.is_not(None))
                .distinct()
                .order_by(Purchase.supplier_name)
            ).all()
            self.suppliers = [s.strip() for s in raw_sups if s and s.strip()]

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("page")
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel("Täze alyş")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        document_form = QFormLayout()
        document_form.setSpacing(10)
        document_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.supplier_input = style_combo(QComboBox())
        self.supplier_input.setEditable(True)
        self.supplier_input.setMinimumHeight(36)
        self.supplier_input.addItem("")
        for sup in self.suppliers:
            self.supplier_input.addItem(sup)
        if self.supplier_input.lineEdit():
            self.supplier_input.lineEdit().setPlaceholderText(
                "Üpjün ediji (boş goýulsa — şahsy çeşme, bergisiz)"
            )

        self.currency_input = style_combo(QComboBox())
        self.currency_input.setMinimumHeight(36)
        self.currency_input.addItems(["USD", "TMT"])
        self.currency_input.currentTextChanged.connect(self._on_document_currency_changed)

        self.rate_input = rate_input()

        document_form.addRow("Üpjün ediji", self.supplier_input)
        document_form.addRow("Resminama walýutasy", self.currency_input)
        document_form.addRow("Kurs (1 USD = X TMT)", self.rate_input)
        root.addLayout(document_form)

        sec_row = QHBoxLayout()
        section = QLabel("Harytlar")
        section.setObjectName("cardTitle")
        sec_row.addWidget(section, 1)

        low_stock_btn = make_icon_button("Az galan harytlary doldur", "bolt")
        low_stock_btn.clicked.connect(self._fill_low_stock_products)
        sec_row.addWidget(low_stock_btn)
        root.addLayout(sec_row)

        barcode_row = QHBoxLayout()
        barcode_row.setSpacing(8)
        self.barcode_scan_input = QLineEdit()
        self.barcode_scan_input.setPlaceholderText(
            "Ştrihkod (Barcode) ýa-da SKU skan et / ýaz we Enter bas — san boýunça +1 goşular..."
        )
        self.barcode_scan_input.setClearButtonEnabled(True)
        self.barcode_scan_input.setMinimumHeight(38)
        self.barcode_scan_input.returnPressed.connect(self._add_item_by_barcode)
        barcode_add_btn = make_button("║█║ Ştrihkod bilen +1 goş")
        barcode_add_btn.setMinimumHeight(38)
        barcode_add_btn.clicked.connect(self._add_item_by_barcode)
        barcode_row.addWidget(self.barcode_scan_input, 1)
        barcode_row.addWidget(barcode_add_btn)
        root.addLayout(barcode_row)

        product_row = QHBoxLayout()
        product_row.setSpacing(8)

        self.product_input = style_combo(QComboBox())
        self.product_input.setMinimumHeight(38)
        self.product_input.setMinimumWidth(220)
        self.product_input.currentIndexChanged.connect(self._on_product_changed)

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 100000)
        self.quantity_input.setValue(1)
        self.quantity_input.setMinimumHeight(38)

        self.price_input = money_input()
        self.price_input.setMinimumWidth(110)

        self._populate_product_combo()

        browse_btn = make_icon_button("Katalog / Täze…", "search")
        browse_btn.setMinimumHeight(38)
        browse_btn.clicked.connect(self._open_catalog_selector)

        add_item_button = make_button("+ Haryt goş", "primary")
        add_item_button.setMinimumHeight(38)
        add_item_button.clicked.connect(self._add_item)

        product_row.addWidget(self.product_input, 1)
        product_row.addWidget(browse_btn)
        product_row.addWidget(QLabel("Sany"))
        product_row.addWidget(self.quantity_input)
        product_row.addWidget(QLabel("Baha"))
        product_row.addWidget(self.price_input)
        product_row.addWidget(add_item_button)
        root.addLayout(product_row)

        self.items_table = QTableWidget(0, 5)
        self.items_table.setHorizontalHeaderLabels([
            "Haryt", "Sany", "1 sanynyň bahasy", "Jemi", "IMEI",
        ])
        configure_table(self.items_table, stretch_col=0, row_height=42)
        self.items_table.setMinimumHeight(145)
        self.items_table.cellDoubleClicked.connect(self._edit_item_imeis)
        root.addWidget(self.items_table, 2)

        item_actions = QHBoxLayout()
        imei_button = make_icon_button("Saýlanan setir üçin IMEI görkez", "phone")
        imei_button.clicked.connect(self._open_imei_for_selected)
        remove_item_button = make_button("Saýlanan setiri poz", "danger")
        remove_item_button.clicked.connect(self._remove_item)
        item_actions.addWidget(imei_button)
        item_actions.addStretch()
        item_actions.addWidget(remove_item_button)
        root.addLayout(item_actions)

        self.total_label = QLabel("Jemi: 0.00 USD")
        self.total_label.setStyleSheet(
            f"font-size: 14.5pt; font-weight: 700; color: {theme.NAVY};"
        )
        root.addWidget(self.total_label)

        payment_title = QLabel("Başlangyç töleg")
        payment_title.setObjectName("cardTitle")
        root.addWidget(payment_title)

        payment_row = QHBoxLayout()
        payment_row.setSpacing(8)

        self.payment_currency = style_combo(QComboBox())
        self.payment_currency.setMinimumHeight(36)
        self.payment_currency.addItems(["USD", "TMT"])
        self.payment_amount = money_input()
        self.payment_amount.setMinimumWidth(120)
        self.payment_rate = rate_input()

        add_payment_button = make_button("+ Töleg goş")
        add_payment_button.setMinimumHeight(36)
        add_payment_button.clicked.connect(self._add_payment)

        payment_row.addWidget(QLabel("Walýuta"))
        payment_row.addWidget(self.payment_currency)
        payment_row.addWidget(QLabel("Jemi"))
        payment_row.addWidget(self.payment_amount, 1)
        payment_row.addWidget(QLabel("Kurs"))
        payment_row.addWidget(self.payment_rate)
        payment_row.addWidget(add_payment_button)
        root.addLayout(payment_row)

        self.payments_table = QTableWidget(0, 3)
        self.payments_table.setHorizontalHeaderLabels(["Walýuta", "Jemi", "Kurs"])
        configure_table(self.payments_table, stretch_col=1, row_height=40)
        self.payments_table.setMinimumHeight(110)
        root.addWidget(self.payments_table, 1)

        pay_actions = QHBoxLayout()
        pay_actions.addStretch()
        remove_payment_button = make_button("Saýlanan tölegi poz", "danger")
        remove_payment_button.clicked.connect(self._remove_payment)
        pay_actions.addWidget(remove_payment_button)
        root.addLayout(pay_actions)

        note_form = QFormLayout()
        self.note_input = QLineEdit()
        self.note_input.setMinimumHeight(36)
        self.note_input.setPlaceholderText("Hökmany däl")
        note_form.addRow("Bellik", self.note_input)
        root.addLayout(note_form)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        footer_bar = QWidget()
        footer_bar.setObjectName("dialogFooter")
        buttons = QHBoxLayout(footer_bar)
        buttons.setContentsMargins(24, 12, 24, 12)
        buttons.addStretch()

        cancel_button = make_button("Ýatyr")
        cancel_button.clicked.connect(self.reject)
        save_button = make_button("Alyşy ýatda sakla", "primary")
        save_button.clicked.connect(self._save)

        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        outer.addWidget(footer_bar)
        configure_dialog_buttons(self, save_button, cancel_button)

    def _populate_product_combo(self) -> None:
        cur_id = self.product_input.currentData()
        self.product_input.blockSignals(True)
        self.product_input.clear()
        for product in self.products:
            self.product_input.addItem(f"{product.name}  •  {product.sku}", product.id)
        idx = self.product_input.findData(cur_id)
        if idx >= 0:
            self.product_input.setCurrentIndex(idx)
        self.product_input.blockSignals(False)
        self._on_product_changed()

    def _resolve_last_unit_cost(self, product_id: int) -> Decimal:
        with SessionLocal() as session:
            row = session.execute(
                select(PurchaseItem.unit_cost)
                .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
                .where(
                    PurchaseItem.product_id == product_id,
                    Purchase.status == "active",
                )
                .order_by(Purchase.purchase_date.desc(), PurchaseItem.id.desc())
            ).first()
            if row and row[0] is not None:
                return Decimal(str(row[0]))
        default_cost = SettingsService.get_product_default_cost(product_id)
        if default_cost is not None:
            return default_cost[0]
        return Decimal("0.00")

    def _on_product_changed(self, *_args) -> None:
        if not hasattr(self, "price_input"):
            return
        pid = self.product_input.currentData()
        if pid is not None:
            last_cost = self._resolve_last_unit_cost(pid)
            self.price_input.setValue(float(last_cost))

    def _fill_low_stock_products(self) -> None:
        low_products = get_low_stock_products()
        if not low_products:
            show_toast(self, "Skladda iň az çäkden pes galyndyly haryt ýok.", kind="info")
            return
        added = 0
        for prod in low_products:
            if any(it["product_id"] == prod.id for it in self.items):
                continue
            needed_qty = max(1, (prod.min_stock_quantity - prod.stock_quantity) or 1)
            cost = self._resolve_last_unit_cost(prod.id)
            self.items.append({
                "product_id": prod.id,
                "name": prod.name,
                "quantity": needed_qty,
                "unit_cost": cost,
                "imeis": [],
            })
            added += 1
        self._refresh_items()
        show_toast(self, f"Sklady doldurmak üçin {added} sany setir goşuldy.", kind="success")

    def _apply_initial_data(self, data: dict) -> None:
        if data.get("supplier_name"):
            self.supplier_input.setCurrentText(data["supplier_name"])
        if data.get("currency") in ("USD", "TMT"):
            self.currency_input.setCurrentText(data["currency"])
        if data.get("exchange_rate"):
            self.rate_input.setValue(float(data["exchange_rate"]))
        for it in data.get("items", []):
            self.items.append({
                "product_id": it["product_id"],
                "name": it["name"],
                "quantity": it["quantity"],
                "unit_cost": Decimal(str(it["unit_cost"])),
                "imeis": [],
            })
        self._refresh_items()

    def _open_catalog_selector(self) -> None:
        dlg = CatalogProductSelectorDialog(
            title="Alyş üçin haryt saýlamak",
            parent=self,
        )
        if dlg.exec() and dlg.selected_product:
            self._load_products()
            self._populate_product_combo()
            idx = self.product_input.findData(dlg.selected_product["id"])
            if idx >= 0:
                self.product_input.setCurrentIndex(idx)

    def _add_item_by_barcode(self) -> None:
        raw_code = self.barcode_scan_input.text().strip()
        if not raw_code:
            return

        ru_layout = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
        en_layout = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
        trans_map = {ord(r): ord(e) for r, e in zip(ru_layout, en_layout)}
        trans_map.update({ord(r.upper()): ord(e.upper()) for r, e in zip(ru_layout, en_layout)})
        code_en = raw_code.translate(trans_map)

        matches = find_products_by_barcode(raw_code) or find_products_by_barcode(code_en)
        product = None
        if len(matches) == 1:
            product = matches[0]
        elif len(matches) > 1:
            labels = [
                f"{p.name}"
                + (f" — {' / '.join(filter(None, [p.brand, p.model, p.specification]))}" if any((p.brand, p.model, p.specification)) else "")
                for p in matches
            ]
            chosen, ok = QInputDialog.getItem(
                self,
                "Ştrihkod boýunça harydy saýlaň",
                f"«{raw_code}» ştrihkodyna {len(matches)} sany haryt gabat geldi:",
                labels,
                0,
                False,
            )
            if not ok:
                self.barcode_scan_input.selectAll()
                return
            product = matches[labels.index(chosen)]

        if product is None:
            from app.ui.product_dialog import ProductDialog

            ans = QMessageBox.question(
                self,
                "Ştrihkod tapylmady",
                f"«{raw_code}» ştrihkodly haryt katalogda tapylmady.\n"
                "Bu ştrihkod bilen täze haryt döredip alyşa goşmalymy?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                self.barcode_scan_input.selectAll()
                return
            dlg = ProductDialog(self, initial_barcode=code_en or raw_code)
            if not dlg.exec() or dlg.created_product_id is None:
                return
            self._load_products()
            self._populate_product_combo()
            with SessionLocal() as session:
                product = session.get(Product, dlg.created_product_id)
            if product is None:
                return

        # Если товар уже есть в таблице закупки (без IMEI), увеличиваем количество на +1
        for existing in self.items:
            if existing["product_id"] == product.id and not existing.get("imeis"):
                existing["quantity"] += 1
                self._refresh_items()
                self.barcode_scan_input.clear()
                self.barcode_scan_input.setFocus()
                return

        unit_cost = self._resolve_last_unit_cost(product.id)
        self.items.append({
            "product_id": product.id,
            "name": product.name,
            "quantity": 1,
            "unit_cost": unit_cost,
            "imeis": [],
        })
        self._refresh_items()
        idx = self.product_input.findData(product.id)
        if idx >= 0:
            self.product_input.setCurrentIndex(idx)
        self.barcode_scan_input.clear()
        self.barcode_scan_input.setFocus()

    def _on_document_currency_changed(self, _text: str) -> None:
        self._refresh_items()

    def _add_item(self) -> None:
        product_id = self.product_input.currentData()
        if product_id is None:
            QMessageBox.warning(self, "Haryt ýok", "Ilki katalogdan haryt saýlaň ýa-da dörediň.")
            return

        quantity = self.quantity_input.value()
        unit_cost = Decimal(str(self.price_input.value()))

        existing = next(
            (
                item
                for item in self.items
                if item["product_id"] == product_id and item["unit_cost"] == unit_cost
            ),
            None,
        )
        if existing:
            existing["quantity"] += quantity
        else:
            product_name = self.product_input.currentText().split("  •")[0]
            self.items.append({
                "product_id": product_id,
                "name": product_name,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "imeis": [],
            })
        self._refresh_items()

    def _open_imei_for_selected(self) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self,
                "Setir saýlanmadyk",
                "IMEI görkezmek üçin alyş tablisasyndan haryt setirini saýlaň.",
            )
            return
        self._edit_item_imeis(row, 4)

    def _edit_item_imeis(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self.items)):
            return
        item = self.items[row]
        dlg = ImeiEntryDialog(
            product_name=item["name"],
            max_quantity=item["quantity"],
            existing_imeis=item.get("imeis", []),
            parent=self,
        )
        if dlg.exec():
            item["imeis"] = dlg.imei_list
            self._refresh_items()

    def _remove_item(self) -> None:
        row = self.items_table.currentRow()
        if 0 <= row < len(self.items):
            self.items.pop(row)
            self._refresh_items()

    def _refresh_items(self) -> None:
        self.items_table.setRowCount(len(self.items))
        total = Decimal("0.00")

        for row, item in enumerate(self.items):
            line_total = item["unit_cost"] * item["quantity"]
            total += line_total
            imei_count = len(item.get("imeis", []))
            imei_text = f"{imei_count} IMEI" if imei_count > 0 else "—"

            values = [
                item["name"],
                str(item["quantity"]),
                money_str(item["unit_cost"]),
                money_str(line_total),
                imei_text,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.items_table.setItem(row, column, cell)

        self.total_label.setText(
            f"Jemi: {money_str(total)} {self.currency_input.currentText()}"
        )

    def _add_payment(self) -> None:
        amount = Decimal(str(self.payment_amount.value()))
        if amount <= 0:
            QMessageBox.warning(self, "Nädogry mukdar", "Noldan uly töleg mukdaryny görkeziň.")
            return

        self.payments.append({
            "currency": self.payment_currency.currentText(),
            "amount": amount,
            "exchange_rate": Decimal(str(self.payment_rate.value())),
        })
        self._refresh_payments()
        self.payment_amount.setValue(0)

    def _remove_payment(self) -> None:
        row = self.payments_table.currentRow()
        if 0 <= row < len(self.payments):
            self.payments.pop(row)
            self._refresh_payments()

    def _refresh_payments(self) -> None:
        self.payments_table.setRowCount(len(self.payments))
        for row, payment in enumerate(self.payments):
            values = [
                payment["currency"],
                money_str(payment["amount"]),
                money_str(payment["exchange_rate"]),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.payments_table.setItem(row, column, cell)

    def _save(self) -> None:
        if not self.items:
            QMessageBox.warning(self, "Haryt ýok", "Iň bolmanda bir haryt setirini goşuň.")
            return
        try:
            purchase_id = create_purchase(
                items=[
                    {
                        "product_id": item["product_id"],
                        "quantity": item["quantity"],
                        "unit_cost": item["unit_cost"],
                        "imeis": item.get("imeis", []),
                    }
                    for item in self.items
                ],
                currency=self.currency_input.currentText(),
                exchange_rate=self.rate_input.value(),
                payments=self.payments,
                note=self.note_input.text().strip() or None,
                supplier_name=self.supplier_input.currentText().strip() or None,
            )
            show_toast(self.parentWidget() or self, f"Alyş №{purchase_id} üstünlikli ýatda saklandy.", kind="success")
            self.accept()
        except (ValueError, TypeError, KeyError) as error:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Ýatda saklama ýalňyşlygy", f"Alyşy ýatda saklap bolmady:\n{error}")


class RefundDialog(QDialog):
    """Регистрация возврата денег от поставщика."""

    def __init__(self, purchase_currency: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Üpjün edijiden puluň yzyna gaýtarylmasy")
        self.setMinimumWidth(440)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Yzyna gaýtarmany hasaba almak")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        info = QLabel(
            f"Alyş walýutasy: {purchase_currency}\n"
            "Hakyky alnan mukdary we gaýtarylan günki kursy görkeziň."
        )
        info.setObjectName("mutedText")
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        self.currency_input = style_combo(QComboBox())
        self.currency_input.addItems(["USD", "TMT"])
        self.amount_input = money_input()
        self.rate_input = rate_input()
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Hökmany däl")

        form.addRow("Gaýtarma walýutasy", self.currency_input)
        form.addRow("Gaýtarma mukdary", self.amount_input)
        form.addRow("Kurs (1 USD = X TMT)", self.rate_input)
        form.addRow("Bellik", self.description_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = make_button("Ýatyr")
        cancel_button.clicked.connect(self.reject)
        save_button = make_button("Gaýtarmany hasaba al", "primary")
        save_button.clicked.connect(self._validate)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)
        configure_dialog_buttons(self, save_button, cancel_button)
        self.amount_input.setFocus()

    def _validate(self) -> None:
        if self.amount_input.value() <= 0:
            QMessageBox.warning(self, "Nädogry mukdar", "Gaýtarma mukdary noldan uly bolmaly.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "currency": self.currency_input.currentText(),
            "amount": Decimal(str(self.amount_input.value())),
            "exchange_rate": Decimal(str(self.rate_input.value())),
            "description": self.description_input.text().strip() or None,
        }


class PurchaseDetailsDialog(QDialog):
    """Просмотр закупки, платежей, аннулирования и возвратов с адаптивной прокруткой."""

    def __init__(self, purchase_id: int, parent=None) -> None:
        super().__init__(parent)
        self.purchase_id = purchase_id

        self.setWindowTitle(f"Alyş №{purchase_id}")
        self.resize(860, 740)
        self.setMinimumSize(700, 520)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("page")
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        self.title_label = QLabel(f"Alyş №{self.purchase_id}")
        self.title_label.setObjectName("pageTitle")
        root.addWidget(self.title_label)

        self.info_label = QLabel()
        self.info_label.setObjectName("mutedText")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        self.status_label = QLabel()
        root.addWidget(self.status_label)

        self.balance_label = QLabel()
        root.addWidget(self.balance_label)

        self.cancellation_label = QLabel()
        self.cancellation_label.setWordWrap(True)
        self.cancellation_label.setObjectName("mutedText")
        root.addWidget(self.cancellation_label)

        items_title = QLabel("Alyşyň düzümi")
        items_title.setObjectName("cardTitle")
        root.addWidget(items_title)

        self.items_table = QTableWidget(0, 6)
        self.items_table.setHorizontalHeaderLabels([
            "Haryt", "Kategoriýa", "Brend / Model", "Sany", "Baha", "Jemi",
        ])
        configure_table(self.items_table, stretch_col=[0, 2], row_height=42)
        self.items_table.setMinimumHeight(130)
        root.addWidget(self.items_table)

        payments_title = QLabel("Tölegler taryhy")
        payments_title.setObjectName("cardTitle")
        root.addWidget(payments_title)

        self.payments_table = QTableWidget(0, 4)
        self.payments_table.setHorizontalHeaderLabels(["Sene", "Walýuta", "Jemi", "Kurs"])
        configure_table(self.payments_table, stretch_col=0, row_height=40)
        self.payments_table.setMinimumHeight(110)
        root.addWidget(self.payments_table)

        self.payment_section = QWidget()
        payment_layout = QVBoxLayout(self.payment_section)
        payment_layout.setContentsMargins(0, 0, 0, 0)
        payment_layout.setSpacing(8)

        payment_title = QLabel("Üpjün edijä töleg goşmak")
        payment_title.setObjectName("cardTitle")
        payment_layout.addWidget(payment_title)

        payment_row = QHBoxLayout()
        self.payment_currency = style_combo(QComboBox())
        self.payment_currency.addItems(["USD", "TMT"])
        self.payment_amount = money_input()
        self.payment_rate = rate_input()
        add_payment_button = make_button("Töleg goş", "primary")
        add_payment_button.clicked.connect(self._add_payment)

        payment_row.addWidget(QLabel("Walýuta"))
        payment_row.addWidget(self.payment_currency)
        payment_row.addWidget(QLabel("Jemi"))
        payment_row.addWidget(self.payment_amount, 1)
        payment_row.addWidget(QLabel("Kurs"))
        payment_row.addWidget(self.payment_rate)
        payment_row.addWidget(add_payment_button)
        payment_layout.addLayout(payment_row)
        root.addWidget(self.payment_section)

        refunds_title = QLabel("Üpjün edijiden yzyna gaýtarmalar taryhy")
        refunds_title.setObjectName("cardTitle")
        root.addWidget(refunds_title)

        self.refunds_table = QTableWidget(0, 4)
        self.refunds_table.setHorizontalHeaderLabels(["Sene", "Walýuta", "Jemi", "Bellik"])
        configure_table(self.refunds_table, stretch_col=3, row_height=40)
        self.refunds_table.setMinimumHeight(105)
        root.addWidget(self.refunds_table)

        self.refund_section = QWidget()
        refund_layout = QVBoxLayout(self.refund_section)
        refund_layout.setContentsMargins(0, 0, 0, 0)
        self.refund_hint = QLabel()
        self.refund_hint.setObjectName("mutedText")
        self.refund_hint.setWordWrap(True)
        refund_layout.addWidget(self.refund_hint)
        self.refund_button = make_button("Gaýtarmany hasaba al", "primary")
        self.refund_button.clicked.connect(self._open_refund)
        refund_layout.addWidget(self.refund_button, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.refund_section)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        footer = QWidget()
        footer.setObjectName("dialogFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 12, 24, 12)
        buttons.addStretch()

        self.cancel_purchase_button = make_button("Alyşy ýatyr", "danger")
        self.cancel_purchase_button.clicked.connect(self._cancel_purchase)
        close_button = make_button("Ýap")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(self.cancel_purchase_button)
        buttons.addWidget(close_button)
        outer.addWidget(footer)
        configure_dialog_buttons(self, add_payment_button, close_button)

    def _load_data(self) -> None:
        with SessionLocal() as session:
            purchase = session.get(Purchase, self.purchase_id)
            if purchase is None:
                QMessageBox.warning(self, "Alyş tapylmady", "Resminama ýok.")
                self.reject()
                return

            self.currency = purchase.currency
            self.status = purchase.status
            self.document_rate = Decimal(str(purchase.exchange_rate))
            self.cancelled_at = purchase.cancelled_at if purchase.status == "cancelled" else None
            self.cancellation_reason = (
                purchase.cancellation_reason if purchase.status == "cancelled" else None
            )

            self.is_personal_source = is_personal_source_purchase(purchase)
            supplier_text = (
                PERSONAL_SOURCE_LABEL
                if self.is_personal_source
                else (purchase.supplier_name or "").strip()
            )
            self.info_label.setText(
                f"Sene: {purchase.purchase_date:%d.%m.%Y %H:%M}   |   "
                f"Üpjün ediji: {supplier_text}   |   "
                f"Walýuta: {purchase.currency}   |   "
                f"Kurs: {purchase.exchange_rate}"
            )

            items = session.execute(
                select(PurchaseItem, Product, Category.name)
                .join(Product, PurchaseItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(PurchaseItem.purchase_id == self.purchase_id)
            ).all()

            payments = session.scalars(
                select(PurchasePayment)
                .where(PurchasePayment.purchase_id == self.purchase_id)
                .order_by(PurchasePayment.payment_date)
            ).all()

            refunds = session.scalars(
                select(PurchaseRefund)
                .where(PurchaseRefund.purchase_id == self.purchase_id)
                .order_by(PurchaseRefund.refund_date)
            ).all()

            item_rows = []
            for item, prod, cat_name in items:
                bm = " / ".join(filter(None, [(prod.brand or "").strip(), (prod.model or "").strip()]))
                if not bm and getattr(prod, "is_phone_unit", False) and prod.specification:
                    bm = prod.specification.strip()
                item_rows.append((
                    prod.name,
                    cat_name or "—",
                    bm or "—",
                    item.quantity,
                    money_str(item.unit_cost),
                    money_str(item.total_cost),
                ))
            payment_rows = [
                (
                    p.payment_date.strftime("%d.%m.%Y %H:%M"),
                    p.currency,
                    money_str(p.amount),
                    money_str(p.exchange_rate),
                )
                for p in payments
            ]
            refund_rows = [
                (
                    r.refund_date.strftime("%d.%m.%Y %H:%M"),
                    r.currency,
                    money_str(r.amount),
                    r.description or "—",
                )
                for r in refunds
            ]

        fill_table(self.items_table, item_rows)
        fill_table(self.payments_table, payment_rows)
        fill_table(self.refunds_table, refund_rows)

        if self.status == "cancelled":
            debt = get_supplier_debt(self.purchase_id)
            self.status_label.setText("Status: Ýatyryldy")
            self.status_label.setStyleSheet(
                "font-weight: 700; color: #737B86; background: #F0F1F3; padding: 8px 12px; border-radius: 8px;"
            )
            self.balance_label.setText(f"Üpjün edijiniň bergisi: {money_str(debt)} {self.currency}")
            self.balance_label.setStyleSheet(
                f"font-size: 15pt; font-weight: 700; color: {theme.RED};"
            )
            cancelled_text = "Ýatyrylan senesi: "
            if self.cancelled_at:
                cancelled_text += self.cancelled_at.strftime("%d.%m.%Y %H:%M")
            cancelled_text += f"   |   Sebäbi: {self.cancellation_reason or '—'}"
            self.cancellation_label.setText(cancelled_text)

            self.payment_section.hide()
            self.cancel_purchase_button.hide()
            self.refund_section.show()
            self.refund_hint.setText(
                f"Üpjün ediji gaýtarmaly: {money_str(debt)} {self.currency}. Gaýtarmalar bölekleýin bolup biler."
            )
            self.refund_button.setEnabled(debt > 0)
        else:
            balance = get_purchase_balance(self.purchase_id)
            if self.is_personal_source:
                self.status_label.setText(f"Status: {PERSONAL_SOURCE_LABEL}")
                self.status_label.setStyleSheet(
                    f"font-weight: 700; color: {theme.BLUE}; background: #EFF6FF; padding: 8px 12px; border-radius: 8px;"
                )
                self.balance_label.setText(
                    f"Dükanyň galan bergisi: 0.00 {self.currency} ({PERSONAL_SOURCE_LABEL}, bergisiz)"
                )
                self.balance_label.setStyleSheet(
                    f"font-size: 15pt; font-weight: 700; color: {theme.GREEN};"
                )
                self.cancellation_label.clear()
                self.payment_section.hide()
                self.cancel_purchase_button.show()
                self.refund_section.hide()
            else:
                self.status_label.setText("Status: Tölendi" if balance == 0 else "Status: Işjeň alyş")
                self.status_label.setStyleSheet(
                    f"font-weight: 700; color: {theme.GREEN}; background: #EAF7EF; padding: 8px 12px; border-radius: 8px;"
                )
                self.balance_label.setText(f"Dükanyň galan bergisi: {money_str(balance)} {self.currency}")
                self.balance_label.setStyleSheet(
                    f"font-size: 15pt; font-weight: 700; color: {theme.ACCENT};"
                )
                self.cancellation_label.clear()
                self.payment_section.show()
                self.cancel_purchase_button.show()
                self.refund_section.hide()
                self.payment_rate.setValue(float(self.document_rate))

    def _add_payment(self) -> None:
        amount = Decimal(str(self.payment_amount.value()))
        if amount <= 0:
            QMessageBox.warning(self, "Nädogry mukdar", "Töleg mukdary noldan uly bolmaly.")
            return
        try:
            add_purchase_payment(
                purchase_id=self.purchase_id,
                currency=self.payment_currency.currentText(),
                amount=amount,
                exchange_rate=self.payment_rate.value(),
            )
            self.payment_amount.setValue(0)
            self._load_data()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Töleg ýalňyşlygy", f"Tölegi goşup bolmady:\n{error}")

    def _cancel_purchase(self) -> None:
        reason, accepted = QInputDialog.getText(
            self, "Alyşy ýatyrmak", "Ýatyrmagyň sebäbini görkeziň:"
        )
        if not accepted:
            return
        if not reason.strip():
            QMessageBox.warning(self, "Sebäp görkezilmedik", "Ýatyrmak üçin sebäbini görkezmek hökmany.")
            return

        confirmation = QMessageBox.question(
            self,
            "Ýatyrmagy tassyklamak",
            "Alyşy ýatyrmalymy?\n\n"
            "Harytlar skladdan aýrylar. Dükanyň tölenmedik bergisi nollanar, "
            "eýýäm tölenen pul bolsa üpjün edijiniň dükana bergisi bolar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        try:
            cancel_purchase(self.purchase_id, reason)
            show_toast(self, "Alyş üstünlikli ýatyryldy.", kind="success")
            self._load_data()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Alyşy ýatyryp bolmaýar", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Alyşy ýatyryp bolmady:\n{error}")

    def _open_refund(self) -> None:
        dialog = RefundDialog(self.currency, self)
        if not dialog.exec():
            return
        data = dialog.get_data()
        try:
            add_purchase_refund(
                purchase_id=self.purchase_id,
                currency=data["currency"],
                amount=data["amount"],
                exchange_rate=data["exchange_rate"],
                description=data["description"],
            )
            show_toast(self, "Gaýtarma hasaba alyndy we kassa žurnalyna goşuldy.", kind="success")
            self._load_data()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Gaýtarmany hasaba alyp bolmaýar", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(self, "Gaýtarma ýalňyşlygy", f"Gaýtarmany hasaba alyp bolmady:\n{error}")


class PurchasePage(QWidget):
    """Alyşlar žurnaly."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        self.purchases: list[dict] = []

        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Alyşlar")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()

        self.count_label = QLabel("Resminamalar: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        refresh_button = make_icon_button("Täzele", "refresh")
        refresh_button.clicked.connect(self._load_data)
        header.addWidget(refresh_button)

        add_button = make_button("+ Täze alyş", "primary")
        add_button.clicked.connect(self._open_new_purchase)
        header.addWidget(add_button)
        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)

        self.total_value = QLabel("0")
        stats.addWidget(make_stat_card("Jemi alyşlar", self.total_value, theme.NAVY), 1)

        self.debt_combined_value = QLabel("$0.00  |  0.00 TMT")
        stats.addWidget(
            make_stat_card(
                "Üpjün edijilere bergi (USD / TMT)",
                self.debt_combined_value,
                theme.RED,
                subtitle="Ähli işjeň alyşlar boýunça tölenmedik galyndy",
                small_value=True,
            ),
            2,
        )

        # Активная кликабельная карточка «Çykdajylar (şu aý)» -> открывает окно расходов
        self.expenses_card = ClickableCard(margins=(16, 12, 16, 12), spacing=4)
        self.expenses_card.setToolTip("Täze çykdajy ýazmak üçin basyň")
        self.expenses_card.clicked.connect(self._open_expense_dialog)
        exp_head = QHBoxLayout()
        exp_title = QLabel("Çykdajylar (şu aý)")
        exp_title.setObjectName("mutedText")
        exp_badge = QLabel("+ Çykdajy ýaz →")
        exp_badge.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 8.5pt; font-weight: 700; "
            f"background: {theme.ACCENT_BG}; padding: 2px 8px; border-radius: 6px;"
        )
        exp_head.addWidget(exp_title, 1)
        exp_head.addWidget(exp_badge)
        self.expenses_card.body.addLayout(exp_head)

        self.expenses_value = QLabel("$0.00  |  0.00 TMT")
        self.expenses_value.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 13.5pt; font-weight: 700;"
        )
        self.expenses_sub = QLabel("Şu aýda 0 ýazgy • Çykdajy goşmak üçin basyň")
        self.expenses_sub.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.5pt;")
        self.expenses_card.body.addWidget(self.expenses_value)
        self.expenses_card.body.addWidget(self.expenses_sub)
        stats.addWidget(self.expenses_card, 2)

        root.addLayout(stats)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Alyş belgisi, haryt, kategoriýa, model, üpjün ediji ýa-da bellik boýunça gözleg...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._filter_data)
        root.addWidget(self.search_input)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "№",
            "Sene",
            "Harytlar (Ady • Kategoriýa • Model)",
            "Üpjün ediji",
            "Walýuta",
            "Jemi",
            "Tölendi",
            "Galan bergi",
            "Ýagdaýy",
        ])
        configure_table(self.table, stretch_col=2, row_height=46)
        align_numeric_columns(self.table, (5, 6, 7))
        for col, width in ((0, 52), (1, 138), (3, 125), (4, 72), (5, 100), (6, 100), (7, 105), (8, 110)):
            self.table.setColumnWidth(col, width)
        self.table.cellDoubleClicked.connect(self._open_selected)
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_button)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        open_btn = make_icon_button("Saýlanan alyşy aç", "list", "primary")
        open_btn.clicked.connect(self._open_selected_button)
        actions.addWidget(open_btn)

        repeat_btn = make_icon_button("Saýlanan alyşy gaýtala", "repeat")
        repeat_btn.clicked.connect(self._repeat_selected_purchase)
        actions.addWidget(repeat_btn)

        actions.addStretch()

        hint = QLabel("Resminamany açmak üçin iki gezek ýa-da Enter basyň • Çykdajy ýazmak üçin «Çykdajylar» kartyna basyň.")
        hint.setObjectName("mutedText")
        actions.addWidget(hint)
        root.addLayout(actions)

    def _load_data(self) -> None:
        with SessionLocal() as session:
            purchases = session.scalars(
                select(Purchase).order_by(Purchase.purchase_date.desc())
            ).all()
            monthly_exp = FinanceService.get_monthly_expenses_summary(session)
            pur_ids = [p.id for p in purchases]
            pur_items_summary: dict[int, str] = {}
            if pur_ids:
                pi_rows = session.execute(
                    select(PurchaseItem, Product, Category.name)
                    .join(Product, PurchaseItem.product_id == Product.id)
                    .outerjoin(Category, Product.category_id == Category.id)
                    .where(PurchaseItem.purchase_id.in_(pur_ids))
                    .order_by(PurchaseItem.id.asc())
                ).all()
                grouped_p: dict[int, list[str]] = {}
                for pi, prod, cat_name in pi_rows:
                    bm = " / ".join(filter(None, [(prod.brand or "").strip(), (prod.model or "").strip()]))
                    if not bm and getattr(prod, "is_phone_unit", False) and prod.specification:
                        bm = prod.specification.strip()
                    meta = " • ".join(x for x in (cat_name or "", bm) if x)
                    qty_txt = f" ×{pi.quantity}" if int(pi.quantity or 1) > 1 else ""
                    lbl = f"{prod.name} ({meta}){qty_txt}" if meta else f"{prod.name}{qty_txt}"
                    grouped_p.setdefault(pi.purchase_id, []).append(lbl)
                for pid_k, labels in grouped_p.items():
                    if len(labels) > 2:
                        pur_items_summary[pid_k] = f"{', '.join(labels[:2])} (+{len(labels) - 2})"
                    else:
                        pur_items_summary[pid_k] = ", ".join(labels)

            self.purchases = [
                {
                    "id": p.id,
                    "date": p.purchase_date,
                    "items_summary": pur_items_summary.get(p.id, "—"),
                    "supplier": (
                        PERSONAL_SOURCE_LABEL
                        if is_personal_source_purchase(p)
                        else (p.supplier_name or "").strip()
                    ),
                    "is_personal": is_personal_source_purchase(p),
                    "currency": p.currency,
                    "total": Decimal(str(p.total_amount)),
                    "note": p.note or "",
                    "status": p.status,
                }
                for p in purchases
            ]

        debt_usd = Decimal("0.00")
        debt_tmt = Decimal("0.00")
        for purchase in self.purchases:
            purchase["balance"] = get_purchase_balance(purchase["id"])
            if purchase["status"] == "cancelled" or purchase["is_personal"]:
                purchase["paid"] = Decimal("0.00")
            else:
                purchase["paid"] = purchase["total"] - purchase["balance"]
                if purchase["currency"] == "USD":
                    debt_usd += purchase["balance"]
                else:
                    debt_tmt += purchase["balance"]

        self.total_value.setText(str(len(self.purchases)))
        self.debt_combined_value.setText(f"${money_str(debt_usd)} USD  |  {money_str(debt_tmt)} TMT")
        self.expenses_value.setText(
            f"${money_str(monthly_exp['USD'])} USD  |  {money_str(monthly_exp['TMT'])} TMT"
        )
        self.expenses_sub.setText(
            f"Şu aýda {monthly_exp['count']} ýazgy • Täze çykdajy goşmak üçin basyň"
        )
        self.count_label.setText(f"Resminamalar: {len(self.purchases)}")
        self._filter_data()

    def _open_expense_dialog(self) -> None:
        from app.ui.finance_page import ExpenseDialog

        dlg = ExpenseDialog(self)
        if dlg.exec():
            self._load_data()

    def _filter_data(self, *_args) -> None:
        query = self.search_input.text().strip().lower()
        words = [w for w in query.split() if w]
        filtered = [
            p
            for p in self.purchases
            if not words
            or all(
                w in f"{p['id']} {p['items_summary']} {p['supplier']} {p['note']}".lower()
                for w in words
            )
        ]

        self.table.setRowCount(len(filtered))
        for row, purchase in enumerate(filtered):
            balance = purchase["balance"]
            cancelled = purchase["status"] == "cancelled"

            if cancelled:
                status = "Ýatyryldy"
                status_color = "#858B94"
                paid_text = "—"
                balance_text = "—"
            elif purchase.get("is_personal"):
                status = PERSONAL_SOURCE_LABEL
                status_color = theme.BLUE
                paid_text = "—"
                balance_text = "0.00"
            else:
                status = "Tölendi" if balance == 0 else "Bergi bar"
                status_color = theme.GREEN if balance == 0 else theme.ACCENT
                paid_text = money_str(purchase["paid"])
                balance_text = money_str(balance)

            values = [
                str(purchase["id"]),
                purchase["date"].strftime("%d.%m.%Y %H:%M"),
                purchase["items_summary"],
                purchase["supplier"],
                purchase["currency"],
                money_str(purchase["total"]),
                paid_text,
                balance_text,
                status,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (5, 6, 7):
                    cell.setTextAlignment(NUM_ALIGN)
                elif column in (0, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    cell.setToolTip(purchase["items_summary"])
                if column == 8:
                    f = cell.font()
                    f.setBold(True)
                    cell.setFont(f)
                    cell.setForeground(QColor(status_color))
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if cancelled and column != 8:
                    cell.setForeground(QColor("#858B94"))
                self.table.setItem(row, column, cell)

            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, purchase["id"])

    def _open_new_purchase(self) -> None:
        dialog = PurchaseDialog(self)
        if dialog.exec():
            self._load_data()

    def _open_selected_button(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Tablisadan alyş setirini saýlaň.", kind="info")
            return
        self._open_selected(row, 0)

    def _repeat_selected_purchase(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            show_toast(self, "Gaýtalamak isleýän alyşyňyzy tablisadan saýlaň.", kind="info")
            return
        purchase_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        with SessionLocal() as session:
            pur = session.get(Purchase, purchase_id)
            if pur is None:
                return
            p_items = session.execute(
                select(PurchaseItem, Product.name)
                .join(Product, PurchaseItem.product_id == Product.id)
                .where(PurchaseItem.purchase_id == pur.id, Product.is_active.is_(True))
            ).all()
            init_data = {
                "supplier_name": pur.supplier_name or "",
                "currency": pur.currency,
                "exchange_rate": Decimal(str(pur.exchange_rate)),
                "items": [
                    {
                        "product_id": pi.product_id,
                        "name": p_name,
                        "quantity": pi.quantity,
                        "unit_cost": Decimal(str(pi.unit_cost)),
                    }
                    for pi, p_name in p_items
                ],
            }
        dlg = PurchaseDialog(self, initial_data=init_data)
        if dlg.exec():
            self._load_data()

    def _open_selected(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        purchase_id = item.data(Qt.ItemDataRole.UserRole)
        dialog = PurchaseDetailsDialog(purchase_id, self)
        dialog.exec()
        self._load_data()
