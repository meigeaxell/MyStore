from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database.engine import SessionLocal
from app.repositories.product_repository import (
    deactivate_product,
    delete_stock_item,
    get_product_with_devices,
    list_products_inventory,
    register_stock_item,
    restore_product,
    update_stock_item,
)
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_management_dialog import CategoryManagementDialog
from app.ui.product_dialog import ProductDialog
from app.ui.widgets import (
    Card,
    configure_dialog_buttons,
    configure_table,
    make_button,
    make_stat_card,
    money_str,
    show_toast,
    style_combo,
)

SOURCES = [
    ("Üpjün ediji / Alyş", "supplier"),
    ("Müşderiden satyn alma (B/U)", "direct_buyout"),
    ("Trade-In (Çalyşyk)", "trade_in"),
    ("Başlangyç galyndy girizmek", "initial_stock"),
]

SOURCE_LABELS = {code: label for label, code in SOURCES}

STOCK_ITEM_STATUSES = [
    ("Skladda bar (in_stock)", "in_stock"),
    ("Satyldy (sold)", "sold"),
    ("Hasapdan çykaryldy (written_off)", "written_off"),
]

ROLE_ITEM_TYPE = Qt.ItemDataRole.UserRole
ROLE_PRODUCT_ID = Qt.ItemDataRole.UserRole + 1
ROLE_PRODUCT_NAME = Qt.ItemDataRole.UserRole + 2
ROLE_IS_ACTIVE = Qt.ItemDataRole.UserRole + 3
ROLE_TOTAL_DEVICES = Qt.ItemDataRole.UserRole + 4


class EditStockItemDialog(QDialog):
    """Полное редактирование отдельного устройства (StockItem) по IMEI."""

    def __init__(self, stock_item_id: int, parent=None) -> None:
        super().__init__(parent)
        self.stock_item_id = stock_item_id
        self.setWindowTitle(f"Enjamy üýtgetmek (ID #{stock_item_id})")
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_data()
        self.imei1_input.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(f"Enjamyň (StockItem #{self.stock_item_id}) maglumatlaryny üýtgetmek")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.product_combo = style_combo(QComboBox())
        form.addRow("Model / Haryt *:", self.product_combo)

        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 *")
        form.addRow("IMEI 1 *:", self.imei1_input)

        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        form.addRow("IMEI 2:", self.imei2_input)

        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi S/N (hökmany däl)")
        form.addRow("Seriýa belgisi (S/N):", self.sn_input)

        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        form.addRow("Ýagdaýy:", self.condition_combo)

        self.status_combo = style_combo(QComboBox())
        for label, code in STOCK_ITEM_STATUSES:
            self.status_combo.addItem(label, code)
        form.addRow("Status:", self.status_combo)

        self.source_combo = style_combo(QComboBox())
        self.source_combo.addItem("— Görkezilmedik —", "")
        for label, code in SOURCES:
            self.source_combo.addItem(label, code)
        form.addRow("Çeşme:", self.source_combo)

        cost_row = QHBoxLayout()
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.cost_curr_combo)
        cost_row.addWidget(QLabel("Kurs:"))
        cost_row.addWidget(self.rate_spin)
        form.addRow("Öz bahasy:", cost_row)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Korpus, batareýa %, komplekt, bellik...")
        form.addRow("Bellik:", self.notes_input)

        root.addLayout(form)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Üýtgeşmeleri ýatda sakla", "primary")
        save_btn.clicked.connect(self._save)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)

    def _load_data(self) -> None:
        from app.models.stock_item import StockItem

        products, _cats = list_products_inventory(include_archived=True)
        self.product_combo.clear()
        for p in products:
            suffix = " [ARHIW]" if not p.get("is_active", True) else ""
            cat_part = f" ({p['category']})" if p.get("category") else ""
            self.product_combo.addItem(f"{p['name']}{cat_part}{suffix}", p["id"])

        with SessionLocal() as session:
            st = session.get(StockItem, self.stock_item_id)
            if st is None:
                QMessageBox.warning(self, "Tapylmady", "Enjam bazada tapylmady.")
                self.reject()
                return

            idx = self.product_combo.findData(st.product_id)
            if idx >= 0:
                self.product_combo.setCurrentIndex(idx)
            self.imei1_input.setText(st.imei1 or "")
            self.imei2_input.setText(st.imei2 or "")
            self.sn_input.setText(st.serial_number or "")
            c_idx = self.condition_combo.findData("used" if st.condition != "new" else "new")
            if c_idx >= 0:
                self.condition_combo.setCurrentIndex(c_idx)
            s_idx = self.status_combo.findData(st.status)
            if s_idx >= 0:
                self.status_combo.setCurrentIndex(s_idx)
            src_idx = self.source_combo.findData(st.acquisition_source or "")
            if src_idx >= 0:
                self.source_combo.setCurrentIndex(src_idx)
            if st.unit_cost is not None:
                self.cost_spin.setValue(float(st.unit_cost))
            if st.cost_currency in ("USD", "TMT"):
                self.cost_curr_combo.setCurrentText(st.cost_currency)
            if st.cost_exchange_rate is not None and float(st.cost_exchange_rate) > 0:
                self.rate_spin.setValue(float(st.cost_exchange_rate))
            self.notes_input.setText(st.notes or "")

    def _save(self) -> None:
        pid = self.product_combo.currentData()
        if pid is None:
            QMessageBox.warning(self, "Ýalňyşlyk", "Haryt modelini saýlaň.")
            return
        try:
            update_stock_item(
                stock_item_id=self.stock_item_id,
                product_id=int(pid),
                imei1=self.imei1_input.text(),
                imei2=self.imei2_input.text(),
                serial_number=self.sn_input.text(),
                condition=self.condition_combo.currentData(),
                status=self.status_combo.currentData(),
                unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                cost_currency=self.cost_curr_combo.currentText(),
                cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                acquisition_source=self.source_combo.currentData() or None,
                notes=self.notes_input.text(),
            )
            show_toast(
                self.parentWidget() or self,
                "Enjamyň maglumatlary üstünlikli täzelendi.",
                kind="success",
            )
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Üýtgeşmeleri saklap bolmady:\n{err}")


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
        self.imei1_input.setFocus()

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
        edit_imei_btn = make_button("✏ Saýlanan enjamy üýtget", "primary")
        edit_imei_btn.clicked.connect(self._edit_selected_stock_item)
        footer.addWidget(edit_imei_btn)

        del_imei_btn = make_button("🗑 Enjamy poz", "danger")
        del_imei_btn.clicked.connect(self._delete_selected_stock_item)
        footer.addWidget(del_imei_btn)

        imei_hist_btn = make_button("📜 Saýlanan IMEI-niň doly taryhy")
        imei_hist_btn.clicked.connect(self._open_selected_imei_history)
        footer.addWidget(imei_hist_btn)
        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, self.add_device_btn, close_btn)

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
        self.add_device_btn = make_button("+ Enjamy sklada goş", "primary")
        self.add_device_btn.clicked.connect(self._add_stock_item)
        row3.addWidget(self.notes_input, 1)
        row3.addWidget(self.add_device_btn)
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
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._edit_selected_stock_item())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._edit_selected_stock_item)
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
            elif it.status == "written_off":
                status_text = "Hasapdan çykaryldy"
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
            self.imei1_input.setFocus()
            show_toast(self, "Enjam sklada üstünlikli hasaba alyndy.", kind="success")
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Enjamy ýatda saklap bolmady:\n{err}")

    def _edit_selected_stock_item(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Üýtgetmek üçin tablisadan enjam setirini saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        if not id_cell:
            return
        dlg = EditStockItemDialog(int(id_cell.text()), self)
        if dlg.exec():
            self._load_items()

    def _delete_selected_stock_item(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Pozmak üçin tablisadan enjam setirini saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        imei_cell = self.table.item(row, 1)
        if not id_cell or not imei_cell:
            return
        ans = QMessageBox.question(
            self,
            "Enjamy pozmak",
            f"IMEI {imei_cell.text()} enjamyny skladyň sanawyndan hakykatdan hem pozmalymy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_stock_item(int(id_cell.text()))
            self._load_items()
            show_toast(self, "Enjam üstünlikli pozuldy.", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Pozup bolmady", str(err))

    def _open_selected_imei_history(self) -> None:
        from app.ui.reports_page import ImeiHistoryDialog

        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Doly taryhyny görmek üçin tablisadan enjam setirini saýlaň.", kind="info")
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

        self.count_label = QLabel("Jemi: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        cat_btn = make_button("Kategoriýalar")
        cat_btn.clicked.connect(self._open_category_management)
        header.addWidget(cat_btn)

        used_btn = make_button("+ Enjam (IMEI)")
        used_btn.clicked.connect(lambda: self._open_device_intake(default_condition="used"))
        header.addWidget(used_btn)

        add_prod_btn = make_button("+ Haryt goş (Ctrl+N)", "primary")
        add_prod_btn.clicked.connect(self._open_add_product)
        header.addWidget(add_prod_btn)

        self.add_product_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.add_product_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.add_product_shortcut.activated.connect(self._open_add_product)

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
            "Ady, kategoriýa, brend, model, referens, ştrihkod ýa-da IMEI boýunça gözleg..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._filter_products)

        self.category_filter = style_combo(QComboBox())
        self.category_filter.setMinimumWidth(175)
        self.category_filter.setMinimumHeight(40)
        self.category_filter.addItem("Ähli kategoriýalar", None)
        self.category_filter.currentIndexChanged.connect(self._filter_products)

        self.status_filter = style_combo(QComboBox())
        self.status_filter.setMinimumWidth(190)
        self.status_filter.setMinimumHeight(40)
        self.status_filter.addItem("Ähli işjeň harytlar", "all")
        self.status_filter.addItem("Skladda bar", "in_stock")
        self.status_filter.addItem("B/U enjamlar bar", "has_used")
        self.status_filter.addItem("Köp duran (> 30 gün)", "stale_30")
        self.status_filter.addItem("Az galyndy", "low_stock")
        self.status_filter.addItem("Skladda ýok", "out_of_stock")
        self.status_filter.addItem("📦 Arhiwdäki harytlar", "archived")
        self.status_filter.currentIndexChanged.connect(self._filter_products)

        self.group_combo = style_combo(QComboBox())
        self.group_combo.setMinimumWidth(205)
        self.group_combo.setMinimumHeight(40)
        self.group_combo.addItem("Topar: Ady boýunça", "name")
        self.group_combo.addItem("Topar: Brend boýunça", "brand")
        self.group_combo.addItem("Topar: Kategoriýa boýunça", "category")
        self.group_combo.addItem("Toparlama: Öçük", "none")
        self._sync_group_combo()
        self.group_combo.currentIndexChanged.connect(self._on_group_mode_changed)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.group_combo)
        layout.addLayout(filters)

        # Harytlar we galyndylar agajy (toparlanan ýa-da adaty sanaw)
        self.tree = QTreeWidget()
        self.table = self.tree
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Öz bahasy",
            "Skladda",
            "IMEI (Täze / B/U)",
            "Status",
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(22)

        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 125), (2, 145), (3, 105), (4, 85), (5, 130), (6, 100)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(col, width)

        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._on_item_activated)
        layout.addWidget(self.tree, 1)

        # Sanawyň aşagyndaky amallar paneli
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(10)

        details_btn = make_button("📱 Haryt karty we enjamlar (IMEI)", "primary")
        details_btn.clicked.connect(self._open_selected_imei_dialog)
        actions_bar.addWidget(details_btn)

        edit_btn = make_button("✏ Harydy üýtget")
        edit_btn.clicked.connect(self._edit_selected_product)
        actions_bar.addWidget(edit_btn)

        self.archive_btn = make_button("📦 Arhiwe geçir / ♻ Dikelt")
        self.archive_btn.clicked.connect(self._toggle_archive_selected_product)
        actions_bar.addWidget(self.archive_btn)

        history_btn = make_button("📜 Hereket taryhy")
        history_btn.clicked.connect(self._open_selected_product_history)
        actions_bar.addWidget(history_btn)

        actions_bar.addStretch()
        hint = QLabel(
            "Iki gezek / Enter: IMEI enjamda — enjamlar karty, sanly harytda — harydy üýtgetmek."
        )
        hint.setObjectName("mutedText")
        actions_bar.addWidget(hint)
        layout.addLayout(actions_bar)

    def _sync_group_combo(self) -> None:
        mode = SettingsService.get_stock_group_mode()
        self.group_combo.blockSignals(True)
        idx = self.group_combo.findData(mode)
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
        self.group_combo.blockSignals(False)

    def _on_group_mode_changed(self) -> None:
        mode = self.group_combo.currentData() or "name"
        SettingsService.set_stock_group_mode(mode)
        self._filter_products()

    def _load_data(self) -> None:
        self._sync_group_combo()
        self.products, self.categories = list_products_inventory(include_archived=True)
        self._update_statistics()
        self._update_category_filter()
        self._filter_products()

    def _update_statistics(self) -> None:
        active_products = [p for p in self.products if p.get("is_active", True)]
        total = len(active_products)
        new_devs = sum(p["new_devices"] for p in active_products)
        used_devs = sum(p["used_devices"] for p in active_products)
        low_stock = sum(
            1
            for p in active_products
            if p["quantity"] > 0 and p["minimum"] > 0 and p["quantity"] <= p["minimum"]
        )
        out_of_stock = sum(1 for p in active_products if p["quantity"] == 0)

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
        tokens = search.split() if search else []
        category_id = self.category_filter.currentData()
        status_mode = self.status_filter.currentData()

        filtered = []
        for p in self.products:
            is_active = p.get("is_active", True)
            if status_mode == "archived":
                if is_active:
                    continue
            else:
                if not is_active:
                    continue
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

            if tokens:
                searchable = " ".join([
                    p["name"],
                    p["category"],
                    p["brand"],
                    p["model"],
                    p.get("reference", ""),
                    p.get("barcode", ""),
                    p["imei_search_blob"],
                ]).lower()
                if not all(tok in searchable for tok in tokens):
                    continue

            filtered.append(p)

        self._show_products(filtered, has_search=bool(tokens))

    def _make_product_tree_item(self, p: dict) -> QTreeWidgetItem:
        brand_model = " / ".join(filter(None, [p["brand"], p["model"]])) or "—"
        if p["total_devices"] > 0:
            imei_summary = f"Täze: {p['new_devices']} • B/U: {p['used_devices']}"
        else:
            imei_summary = "San boýunça hasap"

        if not p.get("is_active", True):
            status = "Arhiw"
            color = theme.MUTED
        elif p["quantity"] == 0:
            status = "Skladda ýok"
            color = theme.RED
        elif p["minimum"] > 0 and p["quantity"] <= p["minimum"]:
            status = "Az galyndy"
            color = theme.ACCENT
        else:
            status = "Bar"
            color = theme.GREEN

        item = QTreeWidgetItem([
            p["name"],
            p["category"],
            brand_model,
            p.get("cost_display", "—"),
            f"{p['quantity']} sany",
            imei_summary,
            status,
        ])
        for col in (3, 4, 5, 6):
            item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

        status_font = QFont(self.tree.font())
        status_font.setBold(True)
        item.setFont(6, status_font)
        item.setForeground(6, QColor(color))
        item.setSizeHint(0, QSize(0, 42))

        tooltip_parts = []
        if p.get("reference"):
            tooltip_parts.append(f"Referens (OCR): {p['reference']}")
        if p.get("barcode"):
            tooltip_parts.append(f"Ştrihkod: {p['barcode']}")
        if p.get("minimum"):
            tooltip_parts.append(f"Iň az galyndy: {p['minimum']} sany")
        if tooltip_parts:
            tip = "\n".join(tooltip_parts)
            for col in range(7):
                item.setToolTip(col, tip)

        item.setData(0, ROLE_ITEM_TYPE, "product")
        item.setData(0, ROLE_PRODUCT_ID, p["id"])
        item.setData(0, ROLE_PRODUCT_NAME, p["name"])
        item.setData(0, ROLE_IS_ACTIVE, bool(p.get("is_active", True)))
        item.setData(0, ROLE_TOTAL_DEVICES, int(p.get("total_devices", 0)))
        return item

    def _show_products(self, products: list[dict], has_search: bool = False) -> None:
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            group_mode = self.group_combo.currentData() or "name"

            if group_mode == "none":
                self.tree.setRootIsDecorated(False)
                self.tree.setIndentation(0)
                for p in products:
                    self.tree.addTopLevelItem(self._make_product_tree_item(p))
                self.count_label.setText(f"Jemi: {len(products)}")
                return

            self.tree.setRootIsDecorated(True)
            self.tree.setIndentation(22)

            groups: dict[str, tuple[str, list[dict]]] = {}
            for p in products:
                if group_mode == "brand":
                    raw = (p.get("brand") or "").strip()
                    key = raw.lower() if raw else "\uffff__no_brand__"
                    display = raw if raw else "Brendsiz"
                elif group_mode == "category":
                    raw = (p.get("category") or "").strip()
                    key = raw.lower() if raw else "\uffff__no_cat__"
                    display = raw if raw else "Kategoriýasyz"
                else:
                    raw = (p.get("name") or "").strip()
                    key = raw.lower() if raw else "\uffff__unnamed__"
                    display = raw if raw else "—"

                if key not in groups:
                    groups[key] = (display, [])
                groups[key][1].append(p)

            sorted_groups = sorted(groups.items(), key=lambda kv: kv[0])

            group_font = QFont(self.tree.font())
            group_font.setBold(True)
            group_bg = QColor("#EEF2F6")
            group_fg = QColor(theme.NAVY)

            for _key, (label, items) in sorted_groups:
                total_qty = sum(int(x.get("quantity", 0)) for x in items)
                total_devs = sum(int(x.get("total_devices", 0)) for x in items)
                g_new = sum(int(x.get("new_devices", 0)) for x in items)
                g_used = sum(int(x.get("used_devices", 0)) for x in items)

                if group_mode == "name":
                    cats = list(dict.fromkeys(x["category"] for x in items if x.get("category")))
                    if len(cats) > 3:
                        cats_str = f"{', '.join(cats[:3])} +{len(cats) - 3}"
                    else:
                        cats_str = ", ".join(cats)
                    header_title = f"📁 {label}"
                    sub_col = f"{len(items)} görnüş"
                    meta_col = cats_str
                elif group_mode == "brand":
                    header_title = f"🏷 {label}"
                    sub_col = f"{len(items)} haryt"
                    meta_col = ""
                else:
                    header_title = f"📂 {label}"
                    sub_col = f"{len(items)} haryt"
                    meta_col = ""

                imei_col = f"Täze: {g_new} • B/U: {g_used}" if total_devs > 0 else ""

                group_item = QTreeWidgetItem([
                    header_title,
                    sub_col,
                    meta_col,
                    "",
                    f"{total_qty} sany",
                    imei_col,
                    "",
                ])
                group_item.setData(0, ROLE_ITEM_TYPE, "group")
                group_item.setSizeHint(0, QSize(0, 38))
                for col in range(7):
                    group_item.setFont(col, group_font)
                    group_item.setBackground(col, group_bg)
                    group_item.setForeground(col, group_fg)
                for col in (4, 5):
                    group_item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

                for prod in items:
                    group_item.addChild(self._make_product_tree_item(prod))

                self.tree.addTopLevelItem(group_item)

            if has_search or len(sorted_groups) <= 40:
                self.tree.expandAll()

            self.count_label.setText(f"Jemi: {len(products)} ({len(sorted_groups)} topar)")
        finally:
            self.tree.setUpdatesEnabled(True)

    def _selected_product_meta(self, silent: bool = False) -> dict | None:
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_ITEM_TYPE) != "product":
            if not silent:
                show_toast(
                    self,
                    "Bu amaly ýerine ýetirmek üçin sanawdan haryt setirini saýlaň.",
                    kind="info",
                )
            return None
        return {
            "id": item.data(0, ROLE_PRODUCT_ID),
            "name": item.data(0, ROLE_PRODUCT_NAME) or item.text(0),
            "is_active": bool(item.data(0, ROLE_IS_ACTIVE)),
            "total_devices": int(item.data(0, ROLE_TOTAL_DEVICES) or 0),
        }

    def _open_add_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec():
            self._load_data()

    def _edit_selected_product(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        dlg = ProductDialog(self, product_id=meta["id"])
        if dlg.exec():
            self._load_data()

    def _toggle_archive_selected_product(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        product_id = meta["id"]
        prod_name = meta["name"]
        is_active = meta["is_active"]

        if not is_active:
            try:
                restore_product(product_id)
                self._load_data()
                show_toast(
                    self,
                    f"«{prod_name}» harydy arhiwden işjeň kataloga gaýtaryldy.",
                    kind="success",
                )
            except (ValueError, SQLAlchemyError) as err:
                QMessageBox.warning(self, "Ýalňyşlyk", str(err))
            return

        ans = QMessageBox.question(
            self,
            "Harydy arhiwe geçirmek",
            f"«{prod_name}» harydyny arhiwe geçirmek isleýärsiňizmi?\n"
            "Skladda galyndy bolsa-da arhiwe geçiriler (galyndylar we taryh saklanar, islendik wagt dikeldip bolýar).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            deactivate_product(product_id, force=True)
            self._load_data()
            show_toast(self, f"«{prod_name}» arhiwe geçirildi.", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _open_category_management(self) -> None:
        dlg = CategoryManagementDialog(self)
        dlg.exec()
        self._load_data()

    def _open_device_intake(self, default_condition: str = "used") -> None:
        meta = self._selected_product_meta(silent=True)
        prod_id = meta["id"] if meta is not None else None
        prod_name = meta["name"] if meta is not None else ""
        dlg = StockItemDialog(
            product_id=prod_id,
            product_name=prod_name,
            default_condition=default_condition,
            parent=self,
        )
        dlg.exec()
        self._load_data()

    def _open_selected_imei_dialog(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        dlg = StockItemDialog(product_id=meta["id"], product_name=meta["name"], parent=self)
        dlg.exec()
        self._load_data()

    def _open_selected_product_history(self) -> None:
        from app.ui.reports_page import ProductHistoryDialog

        meta = self._selected_product_meta()
        if meta is None:
            return
        dlg = ProductHistoryDialog(meta["id"], meta["name"], self)
        dlg.exec()

    def _activate_tree_item(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        item_type = item.data(0, ROLE_ITEM_TYPE)
        if item_type == "group":
            item.setExpanded(not item.isExpanded())
            return
        if item_type != "product":
            return

        prod_id = item.data(0, ROLE_PRODUCT_ID)
        prod_name = item.data(0, ROLE_PRODUCT_NAME) or item.text(0)
        total_devices = int(item.data(0, ROLE_TOTAL_DEVICES) or 0)

        if total_devices > 0:
            dlg = StockItemDialog(product_id=prod_id, product_name=prod_name, parent=self)
            dlg.exec()
            self._load_data()
        else:
            dlg = ProductDialog(self, product_id=prod_id)
            if dlg.exec():
                self._load_data()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        self._activate_tree_item(item)

    def _on_item_activated(self) -> None:
        self._activate_tree_item(self.tree.currentItem())
