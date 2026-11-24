"""Единые визуальные диалоги выбора товаров и складских позиций (Фаза VII)."""
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.repositories.product_repository import (
    is_system_category_code,
    list_categories,
    list_products_inventory,
)
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.product_dialog import ProductDialog
from app.ui.widgets import (
    configure_dialog_buttons,
    configure_table,
    make_button,
    money_str,
    show_toast,
    style_combo,
)


class CatalogProductSelectorDialog(QDialog):
    """Визуальный выбор товара/модели из каталога (для Закупок и приёма Trade-In / Б/У)."""

    def __init__(
        self,
        title: str = "Katalogdan haryt saýlamak",
        initial_query: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(860, 520)
        self.setStyleSheet(theme.STYLE)

        self.products: list[dict] = []
        self.filtered: list[dict] = []
        self.categories: dict[int, str] = {}
        self.selected_product: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        top = QHBoxLayout()
        head = QLabel(title)
        head.setObjectName("cardTitle")
        top.addWidget(head, 1)

        new_btn = make_button("+ Katalogda täze haryt döret")
        new_btn.clicked.connect(self._create_product)
        top.addWidget(new_btn)
        root.addLayout(top)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search_input = QLineEdit(initial_query)
        self.search_input.setPlaceholderText(
            "Ady, kategoriýa, brend, model, referens ýa-da ştrihkod boýunça gözleg..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(38)
        self.search_input.textChanged.connect(self._apply_filter)

        self.category_combo = style_combo(QComboBox())
        self.category_combo.setMinimumWidth(190)
        self.category_combo.setMinimumHeight(38)
        self.category_combo.addItem("Ähli kategoriýalar", None)
        self.category_combo.currentIndexChanged.connect(self._apply_filter)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_combo)
        root.addLayout(filters)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Öz bahasy",
            "Skladda",
            "Enjamlar (IMEI)",
        ])
        configure_table(self.table, stretch_col=0, row_height=42)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._confirm_selection())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._confirm_selection)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("Tapyldy: 0")
        self.count_label.setObjectName("mutedText")
        footer.addWidget(self.count_label)
        footer.addStretch()

        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        select_btn = make_button("Harydy saýla", "primary")
        select_btn.clicked.connect(self._confirm_selection)
        footer.addWidget(cancel_btn)
        footer.addWidget(select_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, select_btn, cancel_btn)
        self._reload_data()
        self.search_input.setFocus()

    def _reload_data(self) -> None:
        raw_products, _all_cats = list_products_inventory()
        # Hide standalone IMEI phone units from quantitative catalog selector
        self.products = [p for p in raw_products if not p.get("is_phone_unit", False)]
        self.categories = {
            c.id: c.name
            for c in list_categories(active_only=True)
            if not is_system_category_code(c.code)
        }
        cur_cat = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Ähli kategoriýalar", None)
        for cid, cname in self.categories.items():
            self.category_combo.addItem(cname, cid)
        idx = self.category_combo.findData(cur_cat)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.category_combo.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        words = [w for w in self.search_input.text().strip().lower().split() if w]
        cat_id = self.category_combo.currentData()
        self.filtered = []

        for p in self.products:
            if cat_id is not None and p["category_id"] != cat_id:
                continue
            if words:
                hay = " ".join([
                    p["name"],
                    p["category"],
                    p["brand"],
                    p["model"],
                    p.get("reference", ""),
                    p.get("barcode", ""),
                ]).lower()
                if not all(w in hay for w in words):
                    continue
            self.filtered.append(p)

        self.table.setRowCount(len(self.filtered))
        self.count_label.setText(f"Tapylan harytlar: {len(self.filtered)}")
        for r, p in enumerate(self.filtered):
            bm = " / ".join(filter(None, [p["brand"], p["model"]])) or "—"
            imei_txt = (
                f"Täze: {p['new_devices']} • B/U: {p['used_devices']}"
                if p["total_devices"] > 0
                else "Sanly"
            )
            vals = [
                p["name"],
                p["category"],
                bm,
                p.get("cost_display", "—"),
                f"{p['quantity']} sany",
                imei_txt,
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (3, 4, 5):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, cell)

        if self.filtered:
            self.table.selectRow(0)

    def _create_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec() and dlg.created_product_id is not None:
            self._reload_data()
            for idx, p in enumerate(self.filtered):
                if p["id"] == dlg.created_product_id:
                    self.table.selectRow(idx)
                    break

    def _confirm_selection(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.filtered)):
            show_toast(self, "Tablisadan haryt saýlaň.", kind="info")
            return
        self.selected_product = self.filtered[row]
        self.accept()


class InventorySelectorDialog(QDialog):
    """Визуальный выбор доступного товара или IMEI-устройства со склада (для Продаж и Trade-In)."""

    def __init__(
        self,
        title: str = "Skladdan haryt ýa-da enjam saýlamak",
        initial_query: str = "",
        exclude_stock_item_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(920, 540)
        self.setStyleSheet(theme.STYLE)

        self.exclude_stock_item_id = exclude_stock_item_id
        self.all_entries: list[dict] = []
        self.filtered: list[dict] = []
        self.selected_item: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        head = QLabel(title)
        head.setObjectName("cardTitle")
        root.addWidget(head)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search_input = QLineEdit(initial_query)
        self.search_input.setPlaceholderText(
            "Ady, kategoriýa, brend, model, referens, ştrihkod ýa-da IMEI boýunça gözleg..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(38)
        self.search_input.textChanged.connect(self._apply_filter)

        self.category_combo = style_combo(QComboBox())
        self.category_combo.setMinimumWidth(175)
        self.category_combo.setMinimumHeight(38)
        self.category_combo.addItem("Ähli kategoriýalar", None)
        self.category_combo.currentIndexChanged.connect(self._apply_filter)

        self.type_combo = style_combo(QComboBox())
        self.type_combo.setMinimumWidth(185)
        self.type_combo.setMinimumHeight(38)
        self.type_combo.addItem("Ähli elýeterliler", "all")
        self.type_combo.addItem("Täze enjamlar (IMEI)", "new_imei")
        self.type_combo.addItem("B/U enjamlar (IMEI)", "used_imei")
        self.type_combo.addItem("Aksessuarlar (IMEI-siz)", "accessory")
        self.type_combo.currentIndexChanged.connect(self._apply_filter)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_combo)
        filters.addWidget(self.type_combo)
        root.addLayout(filters)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Haryt",
            "Kategoriýa",
            "Brend / Model",
            "Öz bahasy",
            "IMEI / Görnüş",
            "Elýeterli",
        ])
        configure_table(self.table, stretch_col=0, row_height=42)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._confirm_selection())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._confirm_selection)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("Elýeterli setirler: 0")
        self.count_label.setObjectName("mutedText")
        footer.addWidget(self.count_label)
        footer.addStretch()

        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        select_btn = make_button("Saýla we goş", "primary")
        select_btn.clicked.connect(self._confirm_selection)
        footer.addWidget(cancel_btn)
        footer.addWidget(select_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, select_btn, cancel_btn)
        self._load_inventory()
        self.search_input.setFocus()

    def _load_inventory(self) -> None:
        self.all_entries = []
        default_curr = SettingsService.get("default_currency", "TMT")
        default_rate = SettingsService.get_default_exchange_rate()

        with SessionLocal() as session:
            categories = session.scalars(
                select(Category).where(Category.is_active.is_(True)).order_by(Category.name.asc())
            ).all()
            cat_map = {c.id: c.name for c in categories}

            self.category_combo.blockSignals(True)
            self.category_combo.clear()
            self.category_combo.addItem("Ähli kategoriýalar", None)
            for c in categories:
                self.category_combo.addItem(c.name, c.id)
            self.category_combo.blockSignals(False)

            products = session.scalars(
                select(Product)
                .where(Product.is_active.is_(True), Product.stock_quantity > 0)
                .order_by(Product.name.asc())
            ).all()
            prod_map = {p.id: p for p in products}

            stock_items = session.scalars(
                select(StockItem)
                .where(StockItem.status == "in_stock")
                .order_by(StockItem.id.desc())
            ).all()

            imei_count_by_prod: dict[int, int] = {}
            for st in stock_items:
                if self.exclude_stock_item_id and st.id == self.exclude_stock_item_id:
                    continue
                prod = prod_map.get(st.product_id)
                if prod is None:
                    continue
                imei_count_by_prod[prod.id] = imei_count_by_prod.get(prod.id, 0) + 1
                is_new = st.condition == "new"
                if st.unit_cost is not None and Decimal(str(st.unit_cost)) > 0:
                    cost_display = (
                        f"{money_str(st.unit_cost)} {(st.cost_currency or default_curr).strip().upper()}"
                    )
                else:
                    u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                        session=session,
                        product_id=prod.id,
                        stock_item=st,
                        fallback_currency=default_curr,
                        fallback_rate=default_rate,
                    )
                    cost_display = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"

                is_phone = bool(getattr(prod, "is_phone_unit", False))
                spec_parts = [x for x in (st.memory, st.color) if x]
                if not is_new and st.battery_health:
                    bh = st.battery_health.strip()
                    spec_parts.append(bh if bh.lower().startswith("bat") else f"Bat: {bh}")
                phone_spec_str = " • ".join(spec_parts)

                self.all_entries.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "brand": prod.brand or "",
                    "model": prod.model or "",
                    "reference": prod.specification or "",
                    "barcode": prod.barcode or "",
                    "category_id": prod.category_id,
                    "category": cat_map.get(prod.category_id, "—"),
                    "cost_display": cost_display,
                    "stock_item_id": st.id,
                    "imei": st.imei1,
                    "imei2": st.imei2 or "",
                    "serial_number": st.serial_number or "",
                    "memory": st.memory or "",
                    "color": st.color or "",
                    "battery_health": st.battery_health or "",
                    "cosmetic_condition": st.cosmetic_condition or "",
                    "phone_spec_str": phone_spec_str,
                    "is_phone_unit": is_phone,
                    "condition": st.condition,
                    "type_code": "new_imei" if is_new else "used_imei",
                    "type_label": "Täze (IMEI)" if is_new else "B/U (IMEI)",
                    "stock_quantity": prod.stock_quantity,
                    "avail_label": "IMEI" if is_phone else "1 sany (IMEI)",
                })

            for prod in products:
                if getattr(prod, "is_phone_unit", False):
                    continue
                non_imei_qty = prod.stock_quantity - imei_count_by_prod.get(prod.id, 0)
                if non_imei_qty > 0:
                    u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                        session=session,
                        product_id=prod.id,
                        stock_item=None,
                        fallback_currency=default_curr,
                        fallback_rate=default_rate,
                    )
                    cost_display = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"
                    self.all_entries.append({
                        "product_id": prod.id,
                        "product_name": prod.name,
                        "brand": prod.brand or "",
                        "model": prod.model or "",
                        "reference": prod.specification or "",
                        "barcode": prod.barcode or "",
                        "category_id": prod.category_id,
                        "category": cat_map.get(prod.category_id, "—"),
                        "cost_display": cost_display,
                        "stock_item_id": None,
                        "imei": None,
                        "imei2": "",
                        "serial_number": "",
                        "memory": "",
                        "color": "",
                        "battery_health": "",
                        "cosmetic_condition": "",
                        "phone_spec_str": "",
                        "is_phone_unit": False,
                        "condition": "new",
                        "type_code": "accessory",
                        "type_label": "Sanly",
                        "stock_quantity": prod.stock_quantity,
                        "avail_label": f"{non_imei_qty} sany",
                    })

        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        words = [w for w in self.search_input.text().strip().lower().split() if w]
        cat_id = self.category_combo.currentData()
        type_code = self.type_combo.currentData()

        self.filtered = []
        for entry in self.all_entries:
            if cat_id is not None and entry["category_id"] != cat_id:
                continue
            if type_code != "all" and entry["type_code"] != type_code:
                continue
            if words:
                hay = " ".join([
                    entry["product_name"],
                    entry["category"],
                    entry["brand"],
                    entry["model"],
                    entry["reference"],
                    entry["barcode"],
                    entry["imei"] or "",
                    entry["imei2"],
                    entry["serial_number"],
                    entry.get("memory", ""),
                    entry.get("color", ""),
                    entry.get("battery_health", ""),
                    entry.get("cosmetic_condition", ""),
                ]).lower()
                if not all(w in hay for w in words):
                    continue
            self.filtered.append(entry)

        self.table.setRowCount(len(self.filtered))
        self.count_label.setText(f"Elýeterli setirler: {len(self.filtered)}")
        for r, entry in enumerate(self.filtered):
            if entry.get("is_phone_unit"):
                bm = entry.get("phone_spec_str") or entry.get("reference") or "—"
            else:
                bm = " / ".join(filter(None, [entry["brand"], entry["model"]])) or "—"
            if entry["imei"]:
                imei_type_col = f"{entry['imei']} ({entry['type_label']})"
                if entry["serial_number"]:
                    imei_type_col += f" • S/N: {entry['serial_number']}"
            else:
                imei_type_col = entry["type_label"]
            vals = [
                entry["product_name"],
                entry["category"],
                bm,
                entry["cost_display"],
                imei_type_col,
                entry["avail_label"],
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (3, 4, 5):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    color = (
                        theme.BLUE
                        if entry["type_code"] == "new_imei"
                        else (theme.ACCENT if entry["type_code"] == "used_imei" else theme.TEAL)
                    )
                    cell.setForeground(QColor(color))
                self.table.setItem(r, c, cell)

        if self.filtered:
            self.table.selectRow(0)

    def _confirm_selection(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.filtered)):
            show_toast(self, "Tablisadan haryt ýa-da enjam saýlaň.", kind="info")
            return
        self.selected_item = self.filtered[row]
        self.accept()
