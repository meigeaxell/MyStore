from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
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
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.repositories.product_repository import list_products_inventory
from app.services.exchange_service import ExchangeService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.sales_page import SaleDetailsDialog
from app.ui.selection_dialogs import (
    CatalogProductSelectorDialog,
    InventorySelectorDialog,
)
from app.ui.widgets import (
    Card,
    configure_table,
    make_button,
    make_icon_button,
    money_str,
    show_toast,
    style_combo,
)


class ExchangePage(QWidget):
    """Страница «Обмен устройств (Trade-in)» — приём устройства по IMEI без обязательного чека."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")

        self.imei_check_info: dict | None = None
        self.available_replacements: list[dict] = []
        self.selected_replacement: dict | None = None
        self.history_rows: list[dict] = []

        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Enjam çalyşygy (Trade-In)")
        title.setObjectName("pageTitle")
        sub = QLabel(
            "Müşderiniň köne telefonyny IMEI boýunça kabul etmek (çek hökmany däl) we skladdaky enjama çalyşmak"
        )
        sub.setObjectName("mutedText")
        col.addWidget(title)
        col.addWidget(sub)
        header.addLayout(col, 1)

        refresh_btn = make_button("↻ Täzele")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_workflow_tab(), "Trade-In resmileşdiriş")
        self.tabs.addTab(self._create_history_tab(), "Çalyşyk taryhy")
        root.addWidget(self.tabs, 1)

    def _create_workflow_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(12)

        intake_card = Card(margins=(16, 14, 16, 14), spacing=10)
        step1_title = QLabel("1. Müşderiniň köne enjamyny kabul etmek (IMEI boýunça)")
        step1_title.setObjectName("cardTitle")
        intake_card.body.addWidget(step1_title)

        imei_row = QHBoxLayout()
        self.old_imei_input = QLineEdit()
        self.old_imei_input.setPlaceholderText("Köne enjamyň IMEI 1 belgisini giriziň ýa-da skanirläň *")
        self.old_imei_input.setMinimumHeight(38)
        self.old_imei_input.returnPressed.connect(self._check_incoming_imei)
        self.old_imei_input.textChanged.connect(self._on_old_imei_edited)

        check_btn = make_button("IMEI-ni bazada barla", "primary")
        check_btn.setMinimumHeight(38)
        check_btn.clicked.connect(self._check_incoming_imei)
        imei_row.addWidget(self.old_imei_input, 1)
        imei_row.addWidget(check_btn)
        intake_card.body.addLayout(imei_row)

        self.imei_status_banner = QLabel(
            "Müşderiniň enjamynyň IMEI-sini giriziň we «IMEI-ni bazada barla» basyň."
        )
        self.imei_status_banner.setWordWrap(True)
        self.imei_status_banner.setStyleSheet(
            f"padding: 8px 10px; border-radius: 8px; background: #F2F4F7; color: {theme.MUTED}; font-weight: 600;"
        )
        intake_card.body.addWidget(self.imei_status_banner)

        intake_form = QFormLayout()
        intake_form.setSpacing(8)

        model_row = QHBoxLayout()
        self.old_product_combo = style_combo(QComboBox())
        self.old_product_combo.setMinimumHeight(36)
        self.old_product_combo.currentIndexChanged.connect(self._recalculate_exchange)
        browse_model_btn = make_button("Model saýla / Döret…")
        browse_model_btn.clicked.connect(self._browse_old_product_model)
        model_row.addWidget(self.old_product_combo, 1)
        model_row.addWidget(browse_model_btn)
        intake_form.addRow("Enjamyň modeli *:", model_row)

        extra_row = QHBoxLayout()
        self.old_condition_combo = style_combo(QComboBox())
        self.old_condition_combo.addItem("B/U (Ulanylan)", "used")
        self.old_condition_combo.addItem("Täze", "new")
        self.old_imei2_input = QLineEdit()
        self.old_imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.old_sn_input = QLineEdit()
        self.old_sn_input.setPlaceholderText("Seriýa № (hökmany däl)")
        extra_row.addWidget(self.old_condition_combo)
        extra_row.addWidget(self.old_imei2_input, 1)
        extra_row.addWidget(self.old_sn_input, 1)
        intake_form.addRow("Ýagdaýy / Goşmaça:", extra_row)

        intake_card.body.addLayout(intake_form)
        left.addWidget(intake_card)

        step2_header = QHBoxLayout()
        step2_title = QLabel("2. Skladdan täze enjamy (çalyşygy) saýlaň")
        step2_title.setObjectName("cardTitle")
        step2_header.addWidget(step2_title, 1)

        browse_stock_btn = make_icon_button("Skladdan saýlamak penjiresi…", "search")
        browse_stock_btn.clicked.connect(self._open_replacement_selector_dialog)
        step2_header.addWidget(browse_stock_btn)
        left.addLayout(step2_header)

        self.rep_search_input = QLineEdit()
        self.rep_search_input.setPlaceholderText("Ady, SKU ýa-da IMEI boýunça sklad süzgüji...")
        self.rep_search_input.setClearButtonEnabled(True)
        self.rep_search_input.setMinimumHeight(38)
        self.rep_search_input.textChanged.connect(self._load_replacements)
        left.addWidget(self.rep_search_input)

        self.rep_table = QTableWidget(0, 4)
        self.rep_table.setHorizontalHeaderLabels([
            "Haryt / Model",
            "SKU",
            "IMEI",
            "Ýagdaýy / Galyndy",
        ])
        configure_table(self.rep_table, stretch_col=0, row_height=42)
        self.rep_table.itemSelectionChanged.connect(self._on_replacement_selected)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.rep_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._focus_new_price_after_select)
        left.addWidget(self.rep_table, 1)

        layout.addLayout(left, 3)

        right = Card()
        rl = right.body

        r_title = QLabel("3. Baha, hasaplama we tassyklama")
        r_title.setObjectName("cardTitle")
        rl.addWidget(r_title)

        self.selected_old_label = QLabel("Kabul edilýän enjam: görkezilmedik")
        self.selected_old_label.setWordWrap(True)
        self.selected_old_label.setStyleSheet("font-weight: 600;")
        rl.addWidget(self.selected_old_label)

        self.selected_new_label = QLabel("Çalşylýan enjam: saýlanmadyk")
        self.selected_new_label.setWordWrap(True)
        self.selected_new_label.setStyleSheet("font-weight: 600;")
        rl.addWidget(self.selected_new_label)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Çalyşyk walýutasy:"), 0, 0)
        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["TMT", "USD"])
        self.currency_combo.setCurrentText(SettingsService.get("default_currency", "TMT"))
        self.currency_combo.currentTextChanged.connect(self._recalculate_exchange)
        grid.addWidget(self.currency_combo, 0, 1)

        grid.addWidget(QLabel("Kurs (1 USD = X TMT):"), 1, 0)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.valueChanged.connect(self._recalculate_exchange)
        grid.addWidget(self.rate_spin, 1, 1)

        grid.addWidget(QLabel("Könäniň bahasy *:"), 2, 0)
        self.old_price_spin = QDoubleSpinBox()
        self.old_price_spin.setRange(0, 10000000)
        self.old_price_spin.setDecimals(2)
        self.old_price_spin.setMinimumHeight(36)
        self.old_price_spin.valueChanged.connect(self._recalculate_exchange)
        grid.addWidget(self.old_price_spin, 2, 1)

        grid.addWidget(QLabel("Täzäniň bahasy *:"), 3, 0)
        self.new_price_spin = QDoubleSpinBox()
        self.new_price_spin.setRange(0, 10000000)
        self.new_price_spin.setDecimals(2)
        self.new_price_spin.setMinimumHeight(36)
        self.new_price_spin.valueChanged.connect(self._recalculate_exchange)
        grid.addWidget(self.new_price_spin, 3, 1)

        grid.addWidget(QLabel("Goşmaça töleg tapawudy:"), 4, 0)
        self.diff_label = QLabel("0.00")
        self.diff_label.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {theme.ACCENT};")
        grid.addWidget(self.diff_label, 4, 1)

        rl.addLayout(grid)

        self.rule_status_label = QLabel("Köne enjamyň IMEI-sini görkeziň we täzesini saýlaň.")
        self.rule_status_label.setWordWrap(True)
        self.rule_status_label.setStyleSheet(
            "padding: 8px 10px; border-radius: 8px; background: #F2F4F7; font-weight: 600;"
        )
        rl.addWidget(self.rule_status_label)

        rl.addWidget(QLabel("Müşderiniň goşmaça tölegi (täzesi gymmat bolsa):"))
        pay_row = QHBoxLayout()
        self.pay_usd_spin = QDoubleSpinBox()
        self.pay_usd_spin.setRange(0, 10000000)
        self.pay_usd_spin.setDecimals(2)
        self.pay_usd_spin.setPrefix("USD: ")
        self.pay_usd_spin.setMinimumHeight(36)
        self.pay_usd_spin.valueChanged.connect(self._recalculate_exchange)

        self.pay_tmt_spin = QDoubleSpinBox()
        self.pay_tmt_spin.setRange(0, 10000000)
        self.pay_tmt_spin.setDecimals(2)
        self.pay_tmt_spin.setPrefix("TMT: ")
        self.pay_tmt_spin.setMinimumHeight(36)
        self.pay_tmt_spin.valueChanged.connect(self._recalculate_exchange)

        pay_row.addWidget(self.pay_usd_spin, 1)
        pay_row.addWidget(self.pay_tmt_spin, 1)
        rl.addLayout(pay_row)

        self.change_label = QLabel("Gaýtargy: 0.00")
        self.change_label.setStyleSheet(f"font-weight: 600; color: {theme.GREEN};")
        rl.addWidget(self.change_label)

        form = QFormLayout()
        form.setSpacing(8)
        self.reason_input = QLineEdit("Trade-In täze modele çalyşyk")
        self.reason_input.setPlaceholderText("Çalyşygyň sebäbi...")
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Korpus, batareýa, komplekt ýagdaýy...")
        form.addRow("Sebäp *", self.reason_input)
        form.addRow("Ýagdaýy / Bellik", self.note_input)
        rl.addLayout(form)

        rl.addStretch()

        self.confirm_btn = make_button("TRADE-IN TASSYKLA WE GEÇIR", "primary")
        self.confirm_btn.setMinimumHeight(46)
        self.confirm_btn.clicked.connect(self._submit_exchange)
        rl.addWidget(self.confirm_btn)

        layout.addWidget(right, 2)
        return widget

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Çalyşyk №, çek, model ýa-da IMEI boýunça gözleg...")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.setMinimumHeight(38)
        self.history_search.textChanged.connect(self._load_history)
        top.addWidget(self.history_search, 1)

        open_sale_btn = make_button("Bagly çeki aç")
        open_sale_btn.clicked.connect(self._open_history_original_sale)
        top.addWidget(open_sale_btn)
        layout.addLayout(top)

        self.history_table = QTableWidget(0, 9)
        self.history_table.setHorizontalHeaderLabels([
            "Çalyşyk №",
            "Sene",
            "Esas / Çek",
            "Sklada kabul edildi (IMEI)",
            "Müşderä berildi (IMEI)",
            "Könäniň bahasy",
            "Täzäniň bahasy",
            "Goşmaça töleg",
            "Sebäp / Bellik",
        ])
        configure_table(self.history_table, stretch_col=[3, 4], row_height=42)
        self.history_table.cellDoubleClicked.connect(
            lambda _r, _c: self._open_history_original_sale()
        )
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.history_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_history_original_sale)
        layout.addWidget(self.history_table, 1)
        return widget

    def refresh_data(self) -> None:
        self._reload_old_products_combo()
        self._load_replacements()
        self._load_history()
        self._recalculate_exchange()

    def _reload_old_products_combo(self) -> None:
        cur_id = self.old_product_combo.currentData()
        products, _cats = list_products_inventory()
        self.old_product_combo.blockSignals(True)
        self.old_product_combo.clear()
        self.old_product_combo.addItem("— Enjamyň modelini saýlaň —", None)
        for p in products:
            self.old_product_combo.addItem(f"{p['name']} ({p['sku']})", p["id"])
        idx = self.old_product_combo.findData(cur_id)
        if idx >= 0:
            self.old_product_combo.setCurrentIndex(idx)
        self.old_product_combo.blockSignals(False)

    def _browse_old_product_model(self) -> None:
        dlg = CatalogProductSelectorDialog(
            title="Kabul edilýän enjamyň modelini saýlamak (Trade-In)",
            parent=self,
        )
        if dlg.exec() and dlg.selected_product:
            self._reload_old_products_combo()
            idx = self.old_product_combo.findData(dlg.selected_product["id"])
            if idx >= 0:
                self.old_product_combo.setCurrentIndex(idx)
            self._recalculate_exchange()

    def _on_old_imei_edited(self) -> None:
        imei = self.old_imei_input.text().strip()
        if not imei:
            self.imei_check_info = None
            self.imei_status_banner.setText(
                "Müşderiniň enjamynyň IMEI-sini giriziň we «IMEI-ni bazada barla» basyň."
            )
            self.imei_status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #F2F4F7; color: {theme.MUTED}; font-weight: 600;"
            )
            self._recalculate_exchange()
            return
        self._check_incoming_imei(silent=True)

    def _check_incoming_imei(self, silent: bool = False) -> None:
        imei = self.old_imei_input.text().strip()
        if not imei:
            if not silent:
                show_toast(self, "Müşderiniň köne enjamynyň IMEI-sini görkeziň.", kind="info")
            return

        with SessionLocal() as session:
            info = ExchangeService.inspect_incoming_imei(session, imei)

        self.imei_check_info = info
        self.imei_status_banner.setText(info["message"])

        if not info["eligible"]:
            self.imei_status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FDECEA; color: {theme.RED}; font-weight: 700;"
            )
        elif info["status"] == "sold":
            self.imei_status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #EAF7EF; color: {theme.GREEN}; font-weight: 700;"
            )
            if info["product_id"]:
                idx = self.old_product_combo.findData(info["product_id"])
                if idx >= 0:
                    self.old_product_combo.setCurrentIndex(idx)
            if info["last_sale_price"] and self.old_price_spin.value() == 0:
                if info["last_sale_currency"] in ("USD", "TMT"):
                    self.currency_combo.setCurrentText(info["last_sale_currency"])
                self.old_price_spin.setValue(float(info["last_sale_price"]))
        else:
            self.imei_status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #E8F1FF; color: {theme.BLUE}; font-weight: 600;"
            )

        self._load_replacements()
        self._recalculate_exchange()

    def _open_replacement_selector_dialog(self) -> None:
        exclude_id = (
            self.imei_check_info.get("stock_item_id")
            if self.imei_check_info
            else None
        )
        dlg = InventorySelectorDialog(
            title="Çalyşyk üçin skladdan enjam ýa-da haryt saýlamak",
            initial_query=self.rep_search_input.text().strip(),
            exclude_stock_item_id=exclude_id,
            parent=self,
        )
        if dlg.exec() and dlg.selected_item:
            item = dlg.selected_item
            self.selected_replacement = {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "sku": item["sku"],
                "stock_item_id": item["stock_item_id"],
                "imei": item["imei"],
                "condition": item["condition"],
                "stock_quantity": item["stock_quantity"],
            }
            # Выделяем строку в таблице, если она там видна
            for row, rep in enumerate(self.available_replacements):
                if (
                    rep["product_id"] == item["product_id"]
                    and rep["stock_item_id"] == item["stock_item_id"]
                ):
                    self.rep_table.selectRow(row)
                    break
            self._recalculate_exchange()

    def _load_replacements(self, *_args) -> None:
        query = self.rep_search_input.text().strip()
        exclude_id = (
            self.imei_check_info.get("stock_item_id")
            if self.imei_check_info
            else None
        )
        with SessionLocal() as session:
            self.available_replacements = ExchangeService.find_available_replacement_items(
                session=session,
                search_query=query,
                exclude_stock_item_id=exclude_id,
            )

        self.rep_table.setRowCount(len(self.available_replacements))
        for i, rep in enumerate(self.available_replacements):
            cond_txt = (
                f"{'Täze' if rep['condition'] == 'new' else 'B/U'}"
                if rep["imei"]
                else f"Bar: {rep['stock_quantity']} sany"
            )
            vals = [
                rep["product_name"],
                rep["sku"],
                rep["imei"] or "IMEI-siz",
                cond_txt,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (1, 2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.rep_table.setItem(i, c, cell)

    def _on_replacement_selected(self) -> None:
        row = self.rep_table.currentRow()
        if 0 <= row < len(self.available_replacements):
            self.selected_replacement = self.available_replacements[row]
        self._recalculate_exchange()

    def _focus_new_price_after_select(self) -> None:
        self._on_replacement_selected()
        if self.selected_replacement is not None:
            self.new_price_spin.setFocus()
            self.new_price_spin.selectAll()

    def _recalculate_exchange(self, *_args) -> None:
        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        old_imei = self.old_imei_input.text().strip()
        old_prod_id = self.old_product_combo.currentData()
        old_prod_text = (
            self.old_product_combo.currentText().split(" (")[0]
            if old_prod_id
            else "Model saýlanmadyk"
        )
        old_price_doc = Decimal(f"{self.old_price_spin.value():.2f}")
        new_price_doc = Decimal(f"{self.new_price_spin.value():.2f}")

        if old_imei and old_prod_id:
            self.selected_old_label.setText(
                f"Kabul edilýär: {old_prod_text} • IMEI: {old_imei} ({old_price_doc:,.2f} {cur})"
            )
        else:
            self.selected_old_label.setText("Kabul edilýän enjam: IMEI görkeziň we model saýlaň")

        if self.selected_replacement:
            rep = self.selected_replacement
            imei_str = f" (IMEI: {rep['imei']})" if rep.get("imei") else ""
            self.selected_new_label.setText(f"Berilýär: {rep['product_name']}{imei_str}")
        else:
            self.selected_new_label.setText("Çalşylýan enjam: saýlanmadyk")

        diff = new_price_doc - old_price_doc
        self.diff_label.setText(f"{max(Decimal('0.00'), diff):,.2f} {cur}")

        can_confirm = True
        if not old_imei:
            can_confirm = False
            self.rule_status_label.setText("1. Müşderiniň köne enjamynyň IMEI-sini giriziň.")
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #F2F4F7; color: {theme.MUTED}; font-weight: 600;"
            )
        elif self.imei_check_info and not self.imei_check_info["eligible"]:
            can_confirm = False
            self.rule_status_label.setText(self.imei_check_info["message"])
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FDECEA; color: {theme.RED}; font-weight: 700;"
            )
        elif not old_prod_id:
            can_confirm = False
            self.rule_status_label.setText("1. Kabul edilýän enjamyň modelini (harydyny) saýlaň.")
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #F2F4F7; color: {theme.MUTED}; font-weight: 600;"
            )
        elif old_price_doc <= Decimal("0.00"):
            can_confirm = False
            self.rule_status_label.setText("Köne enjamyň bahasyny noldan uly görkeziň.")
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FFF3E6; color: {theme.ACCENT}; font-weight: 600;"
            )
        elif not self.selected_replacement:
            can_confirm = False
            self.rule_status_label.setText("2. Skladdan täze enjamy (çalyşygy) saýlaň.")
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #F2F4F7; color: {theme.MUTED}; font-weight: 600;"
            )
        elif new_price_doc <= Decimal("0.00"):
            can_confirm = False
            self.rule_status_label.setText("Täze enjamyň bahasyny noldan uly görkeziň.")
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FFF3E6; color: {theme.ACCENT}; font-weight: 600;"
            )
        elif new_price_doc < old_price_doc:
            can_confirm = False
            self.rule_status_label.setText(
                f"ÇALYŞYK GADAGAN: Täze enjam köneden {abs(diff):,.2f} {cur} arzan. "
                "Çalyşyk bahasy deň ýa-da gymmat bolmaly."
            )
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FDECEA; color: {theme.RED}; font-weight: 700;"
            )
        elif diff == Decimal("0.00"):
            self.rule_status_label.setText(
                "Bahalar deň: goşmaça töleg gerek däl."
            )
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #EAF7EF; color: {theme.GREEN}; font-weight: 700;"
            )
        else:
            self.rule_status_label.setText(
                f"Täze enjam gymmat: müşderiden {diff:,.2f} {cur} goşmaça töleg gerek."
            )
            self.rule_status_label.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FFF3E6; color: {theme.ACCENT}; font-weight: 700;"
            )

        p_usd = Decimal(f"{self.pay_usd_spin.value():.2f}")
        p_tmt = Decimal(f"{self.pay_tmt_spin.value():.2f}")
        paid = p_usd if cur == "USD" else p_usd * rate
        paid += p_tmt if cur == "TMT" else (p_tmt / rate if rate > 0 else Decimal("0.00"))

        required = max(Decimal("0.00"), diff)
        change = paid - required
        if change >= Decimal("0.00"):
            self.change_label.setText(f"Goşmaça tölegden gaýtargy: {change:,.2f} {cur}")
            self.change_label.setStyleSheet(f"font-weight: 600; color: {theme.GREEN};")
        else:
            self.change_label.setText(f"Goşmaça töleg ýetmeýär: {abs(change):,.2f} {cur}")
            self.change_label.setStyleSheet(f"font-weight: 600; color: {theme.RED};")

        self.confirm_btn.setEnabled(can_confirm)

    def _submit_exchange(self) -> None:
        old_imei = self.old_imei_input.text().strip()
        old_prod_id = self.old_product_combo.currentData()
        if not old_imei or not old_prod_id or not self.selected_replacement:
            return

        reason = self.reason_input.text().strip()
        if not reason:
            QMessageBox.warning(self, "Çalyşyk sebäbi", "Çalyşygyň sebäbini görkeziň.")
            return

        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        old_price = Decimal(f"{self.old_price_spin.value():.2f}")
        new_price = Decimal(f"{self.new_price_spin.value():.2f}")

        payments = []
        if self.pay_usd_spin.value() > 0:
            payments.append({
                "currency": "USD",
                "amount": Decimal(f"{self.pay_usd_spin.value():.2f}"),
                "exchange_rate": rate,
            })
        if self.pay_tmt_spin.value() > 0:
            payments.append({
                "currency": "TMT",
                "amount": Decimal(f"{self.pay_tmt_spin.value():.2f}"),
                "exchange_rate": rate,
            })

        rep = self.selected_replacement
        old_prod_name = self.old_product_combo.currentText().split(" (")[0]

        confirm = QMessageBox.question(
            self,
            "Trade-In çalyşygyny tassyklamak",
            f"Köne enjamy kabul etmegi we täzesini bermegi tassyklamalymy?\n\n"
            f"• Sklada kabul edilýär: {old_prod_name} (IMEI: {old_imei}) — {old_price:,.2f} {cur}\n"
            f"• Skladdan berilýär: {rep['product_name']} ({rep['imei'] or 'IMEI-siz'}) — {new_price:,.2f} {cur}\n"
            f"• Müşderiniň goşmaça tölegi: {max(Decimal('0.00'), new_price - old_price):,.2f} {cur}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            with SessionLocal() as session:
                ex_doc = ExchangeService.process_exchange(
                    session=session,
                    old_product_id=old_prod_id,
                    old_imei=old_imei,
                    old_imei2=self.old_imei2_input.text().strip() or None,
                    old_serial_number=self.old_sn_input.text().strip() or None,
                    old_price=old_price,
                    old_condition=self.old_condition_combo.currentData(),
                    new_product_id=rep["product_id"],
                    new_stock_item_id=rep["stock_item_id"],
                    new_imei=rep["imei"],
                    new_price=new_price,
                    currency=cur,
                    exchange_rate=rate,
                    payments=payments,
                    reason=reason,
                    note=self.note_input.text().strip() or None,
                )
                ex_num = ex_doc.exchange_number
                session.commit()

            show_toast(
                self,
                f"{ex_num} Trade-In çalyşyk resminamasy üstünlikli geçirildi.",
                kind="success",
                duration_ms=4000,
            )
            self.old_imei_input.clear()
            self.old_imei2_input.clear()
            self.old_sn_input.clear()
            self.old_price_spin.setValue(0)
            self.new_price_spin.setValue(0)
            self.pay_usd_spin.setValue(0)
            self.pay_tmt_spin.setValue(0)
            self.note_input.clear()
            self.selected_replacement = None
            self.refresh_data()
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Çalyşyk ýalňyşlygy", str(e))

    def _load_history(self, *_args) -> None:
        query = self.history_search.text().strip()
        with SessionLocal() as session:
            self.history_rows = ExchangeService.get_exchange_history(
                session=session,
                search_query=query,
            )

        self.history_table.setRowCount(len(self.history_rows))
        for i, row in enumerate(self.history_rows):
            date_str = (
                row["exchange_date"].strftime("%d.%m.%Y %H:%M")
                if row["exchange_date"]
                else "—"
            )
            cond_badge = "Täze" if row.get("old_condition") == "new" else "B/U"
            old_txt = f"{row['old_product_name']} (IMEI: {row['old_imei']}, {cond_badge})"
            new_txt = f"{row['new_product_name']} ({row['new_imei']})"
            reason_note = " • ".join(filter(None, [row["reason"], row.get("note", "")]))
            vals = [
                row["exchange_number"],
                date_str,
                row["receipt_number"],
                old_txt,
                new_txt,
                f"{money_str(row['old_price'])} {row['currency']}",
                f"{money_str(row['new_price'])} {row['currency']}",
                f"{money_str(row['price_difference'])} {row['currency']}",
                reason_note,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 2, 5, 6, 7):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7 and row["price_difference"] > 0:
                    cell.setForeground(QColor(theme.GREEN))
                self.history_table.setItem(i, c, cell)

    def _open_history_original_sale(self) -> None:
        row = self.history_table.currentRow()
        if not (0 <= row < len(self.history_rows)):
            show_toast(self, "Çalyşyk taryhy tablisasyndan ýazgy saýlaň.", kind="info")
            return
        sale_id = self.history_rows[row]["original_sale_id"]
        if not sale_id:
            show_toast(
                self,
                "Bu çalyşyk göni enjam kabul ediş boýunça geçirildi (çeksiz Trade-In).",
                kind="info",
            )
            return
        dlg = SaleDetailsDialog(sale_id, self)
        dlg.exec()
        self.refresh_data()
