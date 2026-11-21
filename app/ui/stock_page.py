from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database.engine import SessionLocal
from app.repositories.product_repository import (
    get_product_with_devices,
    list_products_inventory,
    register_stock_item,
)
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_management_dialog import CategoryManagementDialog
from app.ui.product_dialog import ProductDialog
from app.ui.widgets import (
    Card,
    configure_table,
    make_button,
    make_stat_card,
    money_str,
    style_combo,
)

SOURCES = [
    ("Üpjün ediji / Alyş", "supplier"),
    ("Müşderiden satyn alma (B/U)", "direct_buyout"),
    ("Trade-In (Çalyşyk)", "trade_in"),
    ("Başlangyç galyndy girizmek", "initial_stock"),
]

SOURCE_LABELS = {code: label for label, code in SOURCES}


class StockItemDialog(QDialog):
    """Haryt karty: IMEI boýunça enjamlar (täze we B/U), hasaba alyş we hereket taryhy."""

    def __init__(
        self,
        product_id: int | None = None,
        product_name: str = "",
        default_condition: str = "new",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.product_name = product_name
        self.default_condition = default_condition
        self._products_cache: list[dict] = []

        self.setWindowTitle(
            f"Haryt karty we enjamlar — {product_name}"
            if product_name
            else "Enjamy hasaba almak (IMEI)"
        )
        self.setMinimumSize(880, 620)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._reload_products_combo()
        self._load_items()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.title_label = QLabel("Haryt karty we aýratyn enjamlar (IMEI)")
        self.title_label.setObjectName("pageTitle")
        top.addWidget(self.title_label, 1)

        edit_prod_btn = make_button("✏ Harydy üýtget")
        edit_prod_btn.clicked.connect(self._edit_current_product)
        top.addWidget(edit_prod_btn)
        root.addLayout(top)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedText")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_devices_tab(), "📱 Enjamlar (IMEI) we hasaba alyş")
        self.tabs.addTab(self._build_history_tab(), "📜 Alyş, satyş we hereket taryhy")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        imei_hist_btn = make_button("📜 Saýlanan IMEI-niň doly taryhy")
        imei_hist_btn.clicked.connect(self._open_selected_imei_history)
        footer.addWidget(imei_hist_btn)
        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _build_devices_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        add_card = Card(margins=(16, 14, 16, 14), spacing=10)
        add_title = QLabel("Enjamy sklada hasaba al (Täze ýa-da B/U)")
        add_title.setObjectName("cardTitle")
        add_card.body.addWidget(add_title)

        form = QFormLayout()
        form.setSpacing(8)

        prod_row = QHBoxLayout()
        self.product_combo = style_combo(QComboBox())
        self.product_combo.currentIndexChanged.connect(self._on_product_combo_changed)
        prod_row.addWidget(self.product_combo, 1)
        new_prod_btn = make_button("+ Täze model döret")
        new_prod_btn.clicked.connect(self._create_new_product)
        prod_row.addWidget(new_prod_btn)
        form.addRow("Model / Haryt *:", prod_row)

        row1 = QHBoxLayout()
        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 (hökmany)*")
        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi (S/N)")
        row1.addWidget(self.imei1_input, 2)
        row1.addWidget(self.imei2_input, 2)
        row1.addWidget(self.sn_input, 1)
        form.addRow("Belgiler:", row1)

        row2 = QHBoxLayout()
        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        if self.default_condition == "used":
            self.condition_combo.setCurrentIndex(1)

        self.source_combo = style_combo(QComboBox())
        for label, code in SOURCES:
            self.source_combo.addItem(label, code)
        if self.default_condition == "used":
            self.source_combo.setCurrentIndex(1)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))

        row2.addWidget(QLabel("Ýagdaýy:"))
        row2.addWidget(self.condition_combo)
        row2.addWidget(QLabel("Çeşme:"))
        row2.addWidget(self.source_combo)
        row2.addWidget(QLabel("Öz bahasy:"))
        row2.addWidget(self.cost_spin)
        row2.addWidget(self.cost_curr_combo)
        row2.addWidget(QLabel("Kurs:"))
        row2.addWidget(self.rate_spin)
        form.addRow("Şertler:", row2)

        row3 = QHBoxLayout()
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(
            "Bellik: korpusyň ýagdaýy, batareýa %, komplekt (hökmany däl)..."
        )
        add_btn = make_button("+ Enjamy sklada goş", "primary")
        add_btn.clicked.connect(self._add_stock_item)
        row3.addWidget(self.notes_input, 1)
        row3.addWidget(add_btn)
        form.addRow("Bellik:", row3)

        add_card.body.addLayout(form)
        layout.addWidget(add_card)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "IMEI 1",
            "IMEI 2 / S/N",
            "Ýagdaýy",
            "Çeşme",
            "Öz bahasy",
            "Status",
            "Bellik",
        ])
        configure_table(self.table, stretch_col=[1, 7], row_height=42)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._open_selected_imei_history())
        layout.addWidget(self.table, 1)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels([
            "Sene",
            "Amal",
            "Üýtgeşme",
            "Resminama",
            "Baha / Öz bahasy",
            "Jikme-jik",
        ])
        configure_table(self.history_table, stretch_col=5, row_height=42)
        layout.addWidget(self.history_table, 1)
        return tab

    def _reload_products_combo(self) -> None:
        products, _cats = list_products_inventory()
        self._products_cache = products
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        for p in products:
            self.product_combo.addItem(f"{p['name']} ({p['sku']})", p["id"])
        if self.product_id is not None:
            idx = self.product_combo.findData(self.product_id)
            if idx >= 0:
                self.product_combo.setCurrentIndex(idx)
        elif self.product_combo.count() > 0:
            self.product_combo.setCurrentIndex(0)
            self.product_id = self.product_combo.currentData()
        self.product_combo.blockSignals(False)

    def _on_product_combo_changed(self) -> None:
        self.product_id = self.product_combo.currentData()
        self._load_items()

    def _create_new_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec() and dlg.created_product_id is not None:
            self.product_id = dlg.created_product_id
            self._reload_products_combo()
            self._load_items()

    def _edit_current_product(self) -> None:
        if self.product_id is None:
            return
        dlg = ProductDialog(self, product_id=self.product_id)
        if dlg.exec():
            self._reload_products_combo()
            self._load_items()

    def _load_items(self) -> None:
        if self.product_id is None:
            return
        product, in_stock_cnt, items = get_product_with_devices(self.product_id)
        if product is None:
            return

        self.product_name = product.name
        self.title_label.setText(f"{product.name} ({product.sku})")
        new_in_stock = sum(1 for i in items if i.status == "in_stock" and i.condition == "new")
        used_in_stock = sum(1 for i in items if i.status == "in_stock" and i.condition != "new")
        brand_model = " / ".join(filter(None, [product.brand, product.model])) or "—"

        self.summary_label.setText(
            f"Brend / Model: {brand_model}   |   "
            f"Skladdaky jemi galyndy: {product.stock_quantity} sany (iň azy: {product.min_stock_quantity})   |   "
            f"IMEI-li bar enjamlar: {in_stock_cnt} (Täze: {new_in_stock}, B/U: {used_in_stock})   |   "
            f"Jemi IMEI ýazgysy: {len(items)}"
        )

        self.table.setRowCount(len(items))
        now = datetime.now()
        for r, it in enumerate(items):
            cost_text = (
                f"{money_str(it.unit_cost)} {it.cost_currency or ''}".strip()
                if it.unit_cost is not None
                else "—"
            )
            if it.status == "in_stock":
                days = max(0, (now - it.created_at).days) if it.created_at else 0
                status_text = f"Bar ({days} gün)"
            else:
                status_text = "Satyldy"
            cond_text = "Täze" if it.condition == "new" else "B/U"
            imei2_sn = " / ".join(filter(None, [it.imei2, it.serial_number])) or "—"
            src_text = SOURCE_LABELS.get(it.acquisition_source or "", it.acquisition_source or "—")

            vals = [
                str(it.id),
                it.imei1,
                imei2_sn,
                cond_text,
                src_text,
                cost_text,
                status_text,
                it.notes or "—",
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 3, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    cell.setForeground(
                        QColor(theme.BLUE if it.condition == "new" else theme.ACCENT)
                    )
                if c == 6:
                    cell.setForeground(
                        QColor(theme.GREEN if it.status == "in_stock" else theme.MUTED)
                    )
                self.table.setItem(r, c, cell)

        with SessionLocal() as session:
            events = ReportService.get_product_history(session, self.product_id)

        self.history_table.setRowCount(len(events))
        for i, ev in enumerate(events):
            d_str = ev["date"].strftime("%d.%m.%Y %H:%M") if ev["date"] else "—"
            vals = [
                d_str,
                ev["event_type"],
                ev["quantity_change"],
                ev["document"],
                ev["price_info"],
                ev["details"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (2, 3, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 2:
                    cell.setForeground(
                        QColor(theme.GREEN if val.startswith("+") else theme.RED)
                    )
                self.history_table.setItem(i, c, cell)

    def _add_stock_item(self) -> None:
        if self.product_id is None:
            QMessageBox.warning(self, "Haryt saýlaň", "Ilki haryt modelini saýlaň ýa-da dörediň.")
            return
        try:
            register_stock_item(
                product_id=self.product_id,
                imei1=self.imei1_input.text(),
                imei2=self.imei2_input.text(),
                serial_number=self.sn_input.text(),
                condition=self.condition_combo.currentData(),
                unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                cost_currency=self.cost_curr_combo.currentText(),
                cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                acquisition_source=self.source_combo.currentData(),
                notes=self.notes_input.text(),
                increment_stock=True,
            )
            self.imei1_input.clear()
            self.imei2_input.clear()
            self.sn_input.clear()
            self.notes_input.clear()
            self._load_items()
            QMessageBox.information(self, "Enjam goşuldy", "Enjam sklada üstünlikli hasaba alyndy.")
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Enjamy ýatda saklap bolmady:\n{err}")

    def _open_selected_imei_history(self) -> None:
        from app.ui.reports_page import ImeiHistoryDialog

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Enjam saýlaň",
                "Doly taryhyny görmek üçin tablisadan enjam setirini saýlaň.",
            )
            return
        id_cell = self.table.item(row, 0)
        imei_cell = self.table.item(row, 1)
        if not id_cell or not imei_cell:
            return
        dlg = ImeiHistoryDialog(
            int(id_cell.text()),
            imei_cell.text(),
            self.product_name,
            self,
        )
        dlg.exec()


class StockPage(QWidget):
    """Harytlar we sklad bölümi."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        self.products: list[dict] = []
        self.categories: dict[int, str] = {}

        self._build_ui()
        self._load_data()

    def refresh_data(self) -> None:
        self._load_data()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Harytlar we sklad")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Haryt katalogi, sklad galyndylary, täze we B/U telefonlaryň IMEI hasaby"
        )
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        self.count_label = QLabel("Harytlar: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        cat_btn = make_button("Kategoriýalar")
        cat_btn.clicked.connect(self._open_category_management)
        header.addWidget(cat_btn)

        used_btn = make_button("+ Enjam goş (IMEI / B/U)")
        used_btn.clicked.connect(lambda: self._open_device_intake(default_condition="used"))
        header.addWidget(used_btn)

        add_prod_btn = make_button("+ Haryt goş", "primary")
        add_prod_btn.clicked.connect(self._open_add_product)
        header.addWidget(add_prod_btn)

        refresh_btn = make_button("↻ Täzele")
        refresh_btn.clicked.connect(self._load_data)
        header.addWidget(refresh_btn)

        layout.addLayout(header)

        # Görkeziji kartlary
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(14)

        self.total_value = QLabel("0")
        self.devices_value = QLabel("0 (Täze: 0 • B/U: 0)")
        self.low_stock_value = QLabel("0")
        self.out_of_stock_value = QLabel("0")

        stats_layout.addWidget(
            make_stat_card("Katalogdaky harytlar", self.total_value, theme.NAVY, "Işjeň modeller we aksessuarlar")
        )
        stats_layout.addWidget(
            make_stat_card(
                "IMEI boýunça bar enjamlar",
                self.devices_value,
                theme.BLUE,
                "Telefonlaryň aýratyn hasaby",
                small_value=True,
            )
        )
        stats_layout.addWidget(
            make_stat_card("Az galyndy", self.low_stock_value, theme.ACCENT, "Üstüni ýetirmeli")
        )
        stats_layout.addWidget(
            make_stat_card("Skladda ýok", self.out_of_stock_value, theme.RED, "Galyndysy nol")
        )
        layout.addLayout(stats_layout)

        # Gözleg we süzgüçler
        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Ady, brend, model, SKU ýa-da enjamyň IMEI-si boýunça gözleg..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._filter_products)

        self.category_filter = style_combo(QComboBox())
        self.category_filter.setMinimumWidth(190)
        self.category_filter.setMinimumHeight(40)
        self.category_filter.addItem("Ähli kategoriýalar", None)
        self.category_filter.currentIndexChanged.connect(self._filter_products)

        self.status_filter = style_combo(QComboBox())
        self.status_filter.setMinimumWidth(190)
        self.status_filter.setMinimumHeight(40)
        self.status_filter.addItem("Ähli sklad ýagdaýlary", "all")
        self.status_filter.addItem("Skladda bar", "in_stock")
        self.status_filter.addItem("B/U enjamlar bar", "has_used")
        self.status_filter.addItem("Köp duran (> 30 gün)", "stale_30")
        self.status_filter.addItem("Az galyndy", "low_stock")
        self.status_filter.addItem("Skladda ýok", "out_of_stock")
        self.status_filter.currentIndexChanged.connect(self._filter_products)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_filter)
        filters.addWidget(self.status_filter)
        layout.addLayout(filters)

        # Harytlar we galyndylar tablisasy
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "SKU",
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Skladda",
            "IMEI (Täze / B/U)",
            "Iň az galyndy",
            "Status",
        ])
        configure_table(self.table, stretch_col=1, row_height=48)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, 1)

        # Tablisanyň aşagyndaky amallar paneli
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(10)

        details_btn = make_button("📱 Haryt karty we enjamlar (IMEI)", "primary")
        details_btn.clicked.connect(self._open_selected_imei_dialog)
        actions_bar.addWidget(details_btn)

        edit_btn = make_button("✏ Harydy üýtget")
        edit_btn.clicked.connect(self._edit_selected_product)
        actions_bar.addWidget(edit_btn)

        add_imei_btn = make_button("+ Saýlanan haryda IMEI goş")
        add_imei_btn.clicked.connect(self._open_selected_imei_dialog)
        actions_bar.addWidget(add_imei_btn)

        history_btn = make_button("📜 Hereket taryhy")
        history_btn.clicked.connect(self._open_selected_product_history)
        actions_bar.addWidget(history_btn)

        actions_bar.addStretch()
        hint = QLabel("Enjamlaryny (IMEI) we taryhyny açmak üçin harydy iki gezek basyň.")
        hint.setObjectName("mutedText")
        actions_bar.addWidget(hint)
        layout.addLayout(actions_bar)

    def _load_data(self) -> None:
        self.products, self.categories = list_products_inventory()
        self._update_statistics()
        self._update_category_filter()
        self._filter_products()

    def _update_statistics(self) -> None:
        total = len(self.products)
        new_devs = sum(p["new_devices"] for p in self.products)
        used_devs = sum(p["used_devices"] for p in self.products)
        low_stock = sum(
            1
            for p in self.products
            if p["quantity"] > 0 and p["minimum"] > 0 and p["quantity"] <= p["minimum"]
        )
        out_of_stock = sum(1 for p in self.products if p["quantity"] == 0)

        self.total_value.setText(str(total))
        self.devices_value.setText(f"{new_devs + used_devs} (Täze: {new_devs} • B/U: {used_devs})")
        self.low_stock_value.setText(str(low_stock))
        self.out_of_stock_value.setText(str(out_of_stock))

    def _update_category_filter(self) -> None:
        selected_category = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Ähli kategoriýalar", None)
        for category_id, name in self.categories.items():
            self.category_filter.addItem(name, category_id)
        index = self.category_filter.findData(selected_category)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _filter_products(self, *_args) -> None:
        search = self.search_input.text().strip().lower()
        category_id = self.category_filter.currentData()
        status_mode = self.status_filter.currentData()

        filtered = []
        for p in self.products:
            if category_id is not None and p["category_id"] != category_id:
                continue
            if status_mode == "in_stock" and p["quantity"] <= 0:
                continue
            if status_mode == "has_used" and p["used_devices"] <= 0:
                continue
            if status_mode == "stale_30" and p.get("max_days_in_stock", 0) < 30:
                continue
            if status_mode == "low_stock" and not (
                0 < p["quantity"] <= p["minimum"] and p["minimum"] > 0
            ):
                continue
            if status_mode == "out_of_stock" and p["quantity"] != 0:
                continue

            if search:
                searchable = " ".join([
                    p["sku"],
                    p["name"],
                    p["brand"],
                    p["model"],
                    p["category"],
                    p["imei_search_blob"],
                ]).lower()
                if search not in searchable:
                    continue

            filtered.append(p)

        self._show_products(filtered)

    def _show_products(self, products: list[dict]) -> None:
        self.table.setRowCount(len(products))
        self.count_label.setText(f"Görkezilen harytlar: {len(products)}")

        for row, p in enumerate(products):
            brand_model = " / ".join(filter(None, [p["brand"], p["model"]])) or "—"
            if p["total_devices"] > 0:
                imei_summary = f"Täze: {p['new_devices']} • B/U: {p['used_devices']}"
            else:
                imei_summary = "San boýunça hasap"

            values = [
                p["sku"],
                p["name"],
                p["category"],
                brand_model,
                f"{p['quantity']} sany",
                imei_summary,
                str(p["minimum"]),
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (0, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

            if p["quantity"] == 0:
                status = "Skladda ýok"
                color = theme.RED
            elif p["minimum"] > 0 and p["quantity"] <= p["minimum"]:
                status = "Az galyndy"
                color = theme.ACCENT
            else:
                status = "Bar"
                color = theme.GREEN

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor("white"))
            status_item.setBackground(QColor(color))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 7, status_item)

            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, p["id"])
            self.table.item(row, 1).setData(Qt.ItemDataRole.UserRole, p["name"])

    def _selected_product(self) -> tuple[int, str] | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Haryt saýlaň",
                "Bu amaly ýerine ýetirmek üçin tablisadan haryt saýlaň.",
            )
            return None
        id_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        if id_item is None or name_item is None:
            return None
        return (
            id_item.data(Qt.ItemDataRole.UserRole),
            name_item.data(Qt.ItemDataRole.UserRole) or name_item.text(),
        )

    def _open_add_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec():
            self._load_data()

    def _edit_selected_product(self) -> None:
        sel = self._selected_product()
        if sel is None:
            return
        product_id, _name = sel
        dlg = ProductDialog(self, product_id=product_id)
        if dlg.exec():
            self._load_data()

    def _open_category_management(self) -> None:
        dlg = CategoryManagementDialog(self)
        dlg.exec()
        self._load_data()

    def _open_device_intake(self, default_condition: str = "used") -> None:
        row = self.table.currentRow()
        prod_id = None
        prod_name = ""
        if row >= 0 and self.table.item(row, 0) is not None:
            prod_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            prod_name = self.table.item(row, 1).text()
        dlg = StockItemDialog(
            product_id=prod_id,
            product_name=prod_name,
            default_condition=default_condition,
            parent=self,
        )
        dlg.exec()
        self._load_data()

    def _open_selected_imei_dialog(self) -> None:
        sel = self._selected_product()
        if sel is None:
            return
        prod_id, prod_name = sel
        dlg = StockItemDialog(product_id=prod_id, product_name=prod_name, parent=self)
        dlg.exec()
        self._load_data()

    def _open_selected_product_history(self) -> None:
        from app.ui.reports_page import ProductHistoryDialog

        sel = self._selected_product()
        if sel is None:
            return
        prod_id, prod_name = sel
        dlg = ProductHistoryDialog(prod_id, prod_name, self)
        dlg.exec()

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        id_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        if id_item is None or name_item is None:
            return
        prod_id = id_item.data(Qt.ItemDataRole.UserRole)
        prod_name = name_item.data(Qt.ItemDataRole.UserRole) or name_item.text()
        dlg = StockItemDialog(product_id=prod_id, product_name=prod_name, parent=self)
        dlg.exec()
        self._load_data()
