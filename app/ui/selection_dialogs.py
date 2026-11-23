"""Единые визуальные диалоги выбора товаров и складских позиций (Фаза VII)."""
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
from app.repositories.product_repository import list_products_inventory
from app.ui import theme
from app.ui.product_dialog import ProductDialog
from app.ui.widgets import (
    configure_dialog_buttons,
    configure_table,
    make_button,
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
        self.setMinimumSize(780, 520)
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
        self.search_input.setPlaceholderText("Ady, brend, model ýa-da SKU boýunça gözleg...")
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
            "SKU",
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Skladda",
            "Enjamlar (IMEI)",
        ])
        configure_table(self.table, stretch_col=1, row_height=42)
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
        self.products, self.categories = list_products_inventory()
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
        q = self.search_input.text().strip().lower()
        cat_id = self.category_combo.currentData()
        self.filtered = []

        for p in self.products:
            if cat_id is not None and p["category_id"] != cat_id:
                continue
            if q:
                hay = f"{p['sku']} {p.get('barcode', '')} {p['name']} {p['brand']} {p['model']} {p['category']}".lower()
                if q not in hay:
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
                p["sku"],
                p["name"],
                p["category"],
                bm,
                f"{p['quantity']} sany",
                imei_txt,
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 4, 5):
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
        self.setMinimumSize(840, 540)
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
        self.search_input.setPlaceholderText("Ady, brend, model, SKU ýa-da IMEI boýunça gözleg...")
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
            "Haryt / Model",
            "Kategoriýa",
            "SKU",
            "IMEI / Seriýa №",
            "Görnüş / Ýagdaýy",
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
                self.all_entries.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "brand": prod.brand or "",
                    "model": prod.model or "",
                    "category_id": prod.category_id,
                    "category": cat_map.get(prod.category_id, "—"),
                    "sku": prod.sku,
                    "stock_item_id": st.id,
                    "imei": st.imei1,
                    "imei2": st.imei2 or "",
                    "serial_number": st.serial_number or "",
                    "condition": st.condition,
                    "type_code": "new_imei" if is_new else "used_imei",
                    "type_label": "Täze (IMEI)" if is_new else "B/U (IMEI)",
                    "stock_quantity": prod.stock_quantity,
                    "avail_label": "1 sany (IMEI)",
                })

            for prod in products:
                non_imei_qty = prod.stock_quantity - imei_count_by_prod.get(prod.id, 0)
                if non_imei_qty > 0:
                    self.all_entries.append({
                        "product_id": prod.id,
                        "product_name": prod.name,
                        "brand": prod.brand or "",
                        "model": prod.model or "",
                        "category_id": prod.category_id,
                        "category": cat_map.get(prod.category_id, "—"),
                        "sku": prod.sku,
                        "stock_item_id": None,
                        "imei": None,
                        "imei2": "",
                        "serial_number": "",
                        "condition": "new",
                        "type_code": "accessory",
                        "type_label": "Sanly",
                        "stock_quantity": prod.stock_quantity,
                        "avail_label": f"{non_imei_qty} sany",
                    })

        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        q = self.search_input.text().strip().lower()
        cat_id = self.category_combo.currentData()
        type_code = self.type_combo.currentData()

        self.filtered = []
        for entry in self.all_entries:
            if cat_id is not None and entry["category_id"] != cat_id:
                continue
            if type_code != "all" and entry["type_code"] != type_code:
                continue
            if q:
                hay = " ".join([
                    entry["product_name"],
                    entry["brand"],
                    entry["model"],
                    entry["category"],
                    entry["sku"],
                    entry["imei"] or "",
                    entry["imei2"],
                    entry["serial_number"],
                ]).lower()
                if q not in hay:
                    continue
            self.filtered.append(entry)

        self.table.setRowCount(len(self.filtered))
        self.count_label.setText(f"Elýeterli setirler: {len(self.filtered)}")
        for r, entry in enumerate(self.filtered):
            imei_col = entry["imei"] or "IMEI-siz"
            if entry["serial_number"]:
                imei_col += f" (S/N: {entry['serial_number']})"
            vals = [
                entry["product_name"],
                entry["category"],
                entry["sku"],
                imei_col,
                entry["type_label"],
                entry["avail_label"],
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (2, 3, 4, 5):
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
