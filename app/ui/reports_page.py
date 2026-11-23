import csv
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QKeySequence, QPageLayout, QPageSize, QShortcut, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.services.report_service import ReportService
from app.ui import theme
from app.ui.sales_page import SaleDetailsDialog
from app.ui.widgets import (
    configure_dialog_buttons,
    configure_table,
    make_button,
    money_str,
    show_toast,
    style_combo,
)


class ProductHistoryDialog(QDialog):
    """Окно полной истории движений товара (Фаза V — Product History)."""

    def __init__(self, product_id: int, product_name: str, parent=None) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.setWindowTitle(f"Haryt taryhy — {product_name}")
        self.setMinimumSize(780, 480)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(f"Hereket taryhy: {product_name}")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Sene",
            "Amal",
            "Galyndy üýtgeşmesi",
            "Resminama",
            "Baha / Öz bahasy",
            "Jikme-jik",
        ])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, close_btn)
        self._load()

    def _load(self) -> None:
        with SessionLocal() as session:
            events = ReportService.get_product_history(session, self.product_id)

        self.table.setRowCount(len(events))
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
                    is_pos = val.startswith("+")
                    cell.setForeground(QColor(theme.GREEN if is_pos else theme.RED))
                self.table.setItem(i, c, cell)


class ImeiHistoryDialog(QDialog):
    """Окно полной непрерывной истории устройства по IMEI (Фаза V — IMEI History)."""

    def __init__(self, stock_item_id: int, imei_label: str, model_name: str, parent=None) -> None:
        super().__init__(parent)
        self.stock_item_id = stock_item_id
        self.setWindowTitle(f"IMEI taryhy — {imei_label}")
        self.setMinimumSize(780, 480)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(f"Enjam taryhy: {model_name} (IMEI: {imei_label})")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Sene",
            "Waka",
            "Resminama",
            "Jemi / Baha",
            "Jikme-jik",
        ])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, close_btn)
        self._load()

    def _load(self) -> None:
        with SessionLocal() as session:
            events = ReportService.get_imei_history(session, self.stock_item_id)

        self.table.setRowCount(len(events))
        for i, ev in enumerate(events):
            d_str = ev["date"].strftime("%d.%m.%Y %H:%M") if ev["date"] else "—"
            vals = [
                d_str,
                ev["event"],
                ev["document"],
                ev["amount"],
                ev["details"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, c, cell)


class ReportsPage(QWidget):
    """Модуль «Отчёты и Аналитика» (Фаза III + Фаза V)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")

        self.sales_rows: list[dict] = []
        self.profit_rows: list[dict] = []
        self.product_rows: list[dict] = []
        self.device_rows: list[dict] = []
        self.inventory_rows: list[dict] = []
        self.supplier_rows: list[dict] = []
        self.customer_rows: list[dict] = []

        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Hasabatlar we analitika")
        title.setObjectName("pageTitle")
        sub = QLabel(
            "Hakyky resminamalar we taryhy öz bahasy esasynda hasaplamalar • CSV we PDF eksport"
        )
        sub.setObjectName("mutedText")
        col.addWidget(title)
        col.addWidget(sub)
        header.addLayout(col, 1)

        csv_btn = make_button("⬇ CSV eksport")
        csv_btn.clicked.connect(self._export_current_csv)
        header.addWidget(csv_btn)

        pdf_btn = make_button("📄 PDF eksport")
        pdf_btn.clicked.connect(self._export_current_pdf)
        header.addWidget(pdf_btn)

        refresh_btn = make_button("↻  Täzele", "primary")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        filter_bar.addWidget(QLabel("Döwür:"))
        self.preset_combo = style_combo(QComboBox())
        self.preset_combo.addItem("Ähli wagt", "all_time")
        self.preset_combo.addItem("Şu gün", "today")
        self.preset_combo.addItem("Düýn", "yesterday")
        self.preset_combo.addItem("Şu hepde", "current_week")
        self.preset_combo.addItem("Şu aý", "current_month")
        self.preset_combo.addItem("Geçen aý", "previous_month")
        self.preset_combo.addItem("Saýlanan döwür", "custom")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        filter_bar.addWidget(self.preset_combo)

        today = QDate.currentDate()
        self.date_from_edit = QDateEdit(today.addMonths(-1))
        self.date_from_edit.setCalendarPopup(True)
        self.date_from_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_from_edit.dateChanged.connect(self._on_custom_date_changed)
        filter_bar.addWidget(self.date_from_edit)

        filter_bar.addWidget(QLabel("—"))

        self.date_to_edit = QDateEdit(today)
        self.date_to_edit.setCalendarPopup(True)
        self.date_to_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_to_edit.dateChanged.connect(self._on_custom_date_changed)
        filter_bar.addWidget(self.date_to_edit)

        filter_bar.addWidget(QLabel("Walýuta:"))
        self.curr_filter_combo = style_combo(QComboBox())
        self.curr_filter_combo.addItem("Ähli walýutalar", None)
        self.curr_filter_combo.addItem("USD", "USD")
        self.curr_filter_combo.addItem("TMT", "TMT")
        self.curr_filter_combo.currentIndexChanged.connect(self.refresh_data)
        filter_bar.addWidget(self.curr_filter_combo)

        filter_bar.addStretch()
        root.addLayout(filter_bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_sales_tab(), "1. Satyşlar")
        self.tabs.addTab(self._create_profit_tab(), "2. Peýda (COGS)")
        self.tabs.addTab(self._create_products_tab(), "3. Harytlar we taryh")
        self.tabs.addTab(self._create_devices_tab(), "4. Enjamlar (IMEI)")
        self.tabs.addTab(self._create_inventory_tab(), "5. Sklad hasabaty")
        self.tabs.addTab(self._create_suppliers_tab(), "6. Üpjün edijiler")
        self.tabs.addTab(self._create_customers_tab(), "7. Müşderiler")
        root.addWidget(self.tabs, 1)

    def _on_preset_changed(self) -> None:
        preset = self.preset_combo.currentData()
        if preset != "custom":
            d_from, d_to = ReportService.resolve_date_range(preset)
            if d_from and d_to:
                self.date_from_edit.blockSignals(True)
                self.date_to_edit.blockSignals(True)
                self.date_from_edit.setDate(QDate(d_from.year, d_from.month, d_from.day))
                self.date_to_edit.setDate(QDate(d_to.year, d_to.month, d_to.day))
                self.date_from_edit.blockSignals(False)
                self.date_to_edit.blockSignals(False)
        self.refresh_data()

    def _on_custom_date_changed(self) -> None:
        if self.preset_combo.currentData() != "custom":
            idx = self.preset_combo.findData("custom")
            if idx >= 0:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(idx)
                self.preset_combo.blockSignals(False)
        self.refresh_data()

    def _get_date_range(self) -> tuple[datetime | None, datetime | None]:
        preset = self.preset_combo.currentData()
        d1 = self.date_from_edit.date().toPython()
        d2 = self.date_to_edit.date().toPython()
        return ReportService.resolve_date_range(preset, d1, d2)

    def _create_sales_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.sales_summary_label = QLabel()
        self.sales_summary_label.setWordWrap(True)
        self.sales_summary_label.setStyleSheet(
            "padding: 10px 14px; background: white; border: 1px solid #E8EBF0; border-radius: 10px; font-weight: 600;"
        )
        layout.addWidget(self.sales_summary_label)

        self.sales_table = QTableWidget(0, 9)
        self.sales_table.setHorizontalHeaderLabels([
            "ID",
            "Çek",
            "Sene",
            "Müşderi",
            "Sany",
            "Walýuta",
            "Girdeji",
            "Tölendi",
            "Müşderiniň bergisi / Status",
        ])
        configure_table(self.sales_table)
        self.sales_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.sales_table.cellDoubleClicked.connect(self._open_sales_report_receipt)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.sales_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(
                lambda: self._open_sales_report_receipt(self.sales_table.currentRow(), 0)
            )
        layout.addWidget(self.sales_table, 1)

        return widget

    def _create_profit_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.profit_summary_label = QLabel()
        self.profit_summary_label.setWordWrap(True)
        self.profit_summary_label.setStyleSheet(
            "padding: 10px 14px; background: white; border: 1px solid #E8EBF0; border-radius: 10px; font-weight: 600;"
        )
        layout.addWidget(self.profit_summary_label)

        self.profit_table = QTableWidget(0, 9)
        self.profit_table.setHorizontalHeaderLabels([
            "Çek",
            "Sene",
            "Haryt",
            "IMEI",
            "Sany",
            "Walýuta",
            "Satyş bahasy",
            "Öz bahasy (COGS)",
            "Jemi peýda (Marža)",
        ])
        configure_table(self.profit_table)
        self.profit_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.profit_table, 1)

        return widget

    def _create_products_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.prod_cat_combo = style_combo(QComboBox())
        self.prod_cat_combo.addItem("Ähli kategoriýalar", None)
        self.prod_cat_combo.currentIndexChanged.connect(self._load_products_report)
        top.addWidget(self.prod_cat_combo)

        self.prod_search = QLineEdit()
        self.prod_search.setPlaceholderText("Haryt ýa-da SKU boýunça gözleg...")
        self.prod_search.setClearButtonEnabled(True)
        self.prod_search.textChanged.connect(self._load_products_report)
        top.addWidget(self.prod_search, 1)

        hist_btn = make_button("📜 Saýlanan harydyň hereket taryhy", "primary")
        hist_btn.clicked.connect(self._open_selected_product_history)
        top.addWidget(hist_btn)
        layout.addLayout(top)

        self.products_table = QTableWidget(0, 10)
        self.products_table.setHorizontalHeaderLabels([
            "SKU",
            "Haryt",
            "Kategoriýa",
            "Galyndy",
            "Alyndy",
            "Satyldy",
            "Girdeji (USD / TMT)",
            "COGS (USD / TMT)",
            "Peýda (USD / TMT)",
            "Soňky satyş",
        ])
        configure_table(self.products_table)
        self.products_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.products_table.cellDoubleClicked.connect(
            lambda _r, _c: self._open_selected_product_history()
        )
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.products_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_product_history)
        layout.addWidget(self.products_table, 1)

        return widget

    def _create_devices_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.dev_status_combo = style_combo(QComboBox())
        self.dev_status_combo.addItem("Ähli statuslar", None)
        self.dev_status_combo.addItem("Skladda bar (in_stock)", "in_stock")
        self.dev_status_combo.addItem("Satyldy (sold)", "sold")
        self.dev_status_combo.currentIndexChanged.connect(self._load_devices_report)
        top.addWidget(self.dev_status_combo)

        self.dev_search = QLineEdit()
        self.dev_search.setPlaceholderText("IMEI, seriýa belgisi ýa-da model boýunça gözleg...")
        self.dev_search.setClearButtonEnabled(True)
        self.dev_search.textChanged.connect(self._load_devices_report)
        top.addWidget(self.dev_search, 1)

        imei_hist_btn = make_button("📱 Saýlanan IMEI-niň doly taryhy", "primary")
        imei_hist_btn.clicked.connect(self._open_selected_imei_history)
        top.addWidget(imei_hist_btn)
        layout.addLayout(top)

        self.devices_table = QTableWidget(0, 10)
        self.devices_table.setHorizontalHeaderLabels([
            "IMEI 1",
            "Model",
            "Ýagdaýy",
            "Alyş senesi",
            "Üpjün ediji",
            "Öz bahasy",
            "Satyş senesi",
            "Satyş bahasy",
            "Peýda",
            "Status",
        ])
        configure_table(self.devices_table)
        self.devices_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.devices_table.cellDoubleClicked.connect(
            lambda _r, _c: self._open_selected_imei_history()
        )
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.devices_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_imei_history)
        layout.addWidget(self.devices_table, 1)

        return widget

    def _create_inventory_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.inv_summary_label = QLabel()
        self.inv_summary_label.setWordWrap(True)
        self.inv_summary_label.setStyleSheet(
            "padding: 10px 14px; background: white; border: 1px solid #E8EBF0; border-radius: 10px; font-weight: 600;"
        )
        layout.addWidget(self.inv_summary_label)

        self.inventory_table = QTableWidget(0, 8)
        self.inventory_table.setHorizontalHeaderLabels([
            "SKU",
            "Ady",
            "Kategoriýa",
            "Model",
            "Skladda jemi",
            "IMEI enjamlar",
            "Aksessuar / Sanly",
            "Galyndy ýagdaýy",
        ])
        configure_table(self.inventory_table)
        self.inventory_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.inventory_table, 1)

        return widget

    def _create_suppliers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.sup_rep_search = QLineEdit()
        self.sup_rep_search.setPlaceholderText("Üpjün edijiniň ady boýunça gözleg...")
        self.sup_rep_search.setClearButtonEnabled(True)
        self.sup_rep_search.textChanged.connect(self._load_suppliers_report)
        top.addWidget(self.sup_rep_search, 1)
        layout.addLayout(top)

        self.suppliers_table = QTableWidget(0, 8)
        self.suppliers_table.setHorizontalHeaderLabels([
            "Üpjün ediji",
            "Alyşlar (Işjeň / Ýatyr.)",
            "Getirilen sany",
            "Alyş jemi (USD / TMT)",
            "Tölendi (USD / TMT)",
            "Dükanyň bergisi (USD / TMT)",
            "Üpjün edijiniň bergisi (USD / TMT)",
            "Hasaplaşyk statusy",
        ])
        configure_table(self.suppliers_table)
        self.suppliers_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.suppliers_table, 1)

        return widget

    def _create_customers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.cust_rep_search = QLineEdit()
        self.cust_rep_search.setPlaceholderText("Müşderiniň ady ýa-da telefony boýunça gözleg...")
        self.cust_rep_search.setClearButtonEnabled(True)
        self.cust_rep_search.textChanged.connect(self._load_customers_report)
        top.addWidget(self.cust_rep_search, 1)
        layout.addLayout(top)

        self.customers_table = QTableWidget(0, 8)
        self.customers_table.setHorizontalHeaderLabels([
            "Müşderi",
            "Satyşlar (Işjeň / Ýatyr.)",
            "Çalyşyklar",
            "Satyş jemi (USD / TMT)",
            "Tölendi (USD / TMT)",
            "Müşderiniň bergisi (USD / TMT)",
            "Dükanyň müşderä bergisi (USD / TMT)",
            "Hasaplaşyk statusy",
        ])
        configure_table(self.customers_table)
        self.customers_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.customers_table, 1)

        return widget

    def refresh_data(self, *_args) -> None:
        self._reload_category_combo()
        self._load_sales_report()
        self._load_profit_report()
        self._load_products_report()
        self._load_devices_report()
        self._load_inventory_report()
        self._load_suppliers_report()
        self._load_customers_report()

    def _reload_category_combo(self) -> None:
        cur_data = self.prod_cat_combo.currentData()
        self.prod_cat_combo.blockSignals(True)
        self.prod_cat_combo.clear()
        self.prod_cat_combo.addItem("Ähli kategoriýalar", None)
        with SessionLocal() as session:
            cats = session.scalars(select(Category).order_by(Category.name.asc())).all()
            for c in cats:
                self.prod_cat_combo.addItem(c.name, c.id)
        idx = self.prod_cat_combo.findData(cur_data)
        if idx >= 0:
            self.prod_cat_combo.setCurrentIndex(idx)
        self.prod_cat_combo.blockSignals(False)

    def _load_sales_report(self) -> None:
        d_from, d_to = self._get_date_range()
        curr = self.curr_filter_combo.currentData()
        with SessionLocal() as session:
            data = ReportService.get_sales_report(session, d_from, d_to, curr)

        u = data["by_currency"]["USD"]
        t = data["by_currency"]["TMT"]
        self.sales_summary_label.setText(
            f"Işjeň çekler: {data['active_receipts_count']}  |  Satylan sany: {data['units_sold']}  |  "
            f"Ýatyrylan çekler (aýratyn): {data['cancelled_receipts_count']} "
            f"(jemi ${u['cancelled_value']:,.2f} USD / {t['cancelled_value']:,.2f} TMT)\n"
            f"• USD — Girdeji: ${u['revenue']:,.2f}  |  Tölendi: ${u['paid']:,.2f}  |  Müşderi bergisi: ${u['customer_debt']:,.2f}\n"
            f"• TMT — Girdeji: {t['revenue']:,.2f} m.  |  Tölendi: {t['paid']:,.2f} m.  |  Müşderi bergisi: {t['customer_debt']:,.2f} m."
        )

        self.sales_rows = data["rows"]
        self.sales_table.setRowCount(len(self.sales_rows))
        for i, r in enumerate(self.sales_rows):
            d_str = r["sale_date"].strftime("%d.%m.%Y %H:%M") if r["sale_date"] else "—"
            if r["status"] == "cancelled":
                st_txt = "Ýatyryldy (girdejide ýok)"
            elif r["customer_debt"] > 0:
                st_txt = f"Bergi: {money_str(r['customer_debt'])} {r['currency']}"
            else:
                st_txt = "Tölendi"

            vals = [
                str(r["sale_id"]),
                r["receipt_number"],
                d_str,
                r["customer_name"],
                str(r["units"]),
                r["currency"],
                money_str(r["total_amount"]),
                money_str(r["paid_amount"]),
                st_txt,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 4, 5, 6, 7, 8):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r["status"] == "cancelled":
                    cell.setForeground(QColor(theme.RED))
                elif c == 8 and r["customer_debt"] > 0:
                    cell.setForeground(QColor(theme.ACCENT))
                self.sales_table.setItem(i, c, cell)

    def _load_profit_report(self) -> None:
        d_from, d_to = self._get_date_range()
        curr = self.curr_filter_combo.currentData()
        with SessionLocal() as session:
            data = ReportService.get_profit_report(session, d_from, d_to, curr)

        u = data["by_currency"]["USD"]
        t = data["by_currency"]["TMT"]
        self.profit_summary_label.setText(
            f"Satyş wagtyndaky taryhy öz bahasy boýunça hasaplama (ýatyrylan satyşlar aýryldy):\n"
            f"• USD — Girdeji: ${u['revenue']:,.2f}  |  Öz bahasy (COGS): ${u['cogs']:,.2f}  |  "
            f"Jemi peýda: ${u['gross_profit']:,.2f}  |  Kassa gelen: ${u['cash_received']:,.2f}\n"
            f"• TMT — Girdeji: {t['revenue']:,.2f} m.  |  Öz bahasy (COGS): {t['cogs']:,.2f} m.  |  "
            f"Jemi peýda: {t['gross_profit']:,.2f} m.  |  Kassa gelen: {t['cash_received']:,.2f} m."
        )

        self.profit_rows = data["rows"]
        self.profit_table.setRowCount(len(self.profit_rows))
        for i, r in enumerate(self.profit_rows):
            d_str = r["sale_date"].strftime("%d.%m.%Y %H:%M") if r["sale_date"] else "—"
            prof_str = f"{money_str(r['gross_profit'])} ({r['margin_pct']}%)"
            vals = [
                r["receipt_number"],
                d_str,
                r["product_name"],
                r["imei"],
                str(r["quantity"]),
                r["currency"],
                money_str(r["selling_price"]),
                money_str(r["cogs"]),
                prof_str,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (4, 5, 6, 7, 8):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 8:
                    cell.setForeground(
                        QColor(theme.GREEN if r["gross_profit"] >= 0 else theme.RED)
                    )
                self.profit_table.setItem(i, c, cell)

    def _load_products_report(self, *_args) -> None:
        cat_id = self.prod_cat_combo.currentData()
        query = self.prod_search.text().strip()
        with SessionLocal() as session:
            self.product_rows = ReportService.get_product_report(session, cat_id, query)

        self.products_table.setRowCount(len(self.product_rows))
        for i, r in enumerate(self.product_rows):
            last_str = (
                r["last_sale_date"].strftime("%d.%m.%Y %H:%M")
                if r["last_sale_date"]
                else "—"
            )
            vals = [
                r["sku"],
                r["name"],
                r["category"],
                str(r["current_stock"]),
                str(r["quantity_purchased"]),
                str(r["quantity_sold"]),
                f"${money_str(r['revenue_usd'])} / {money_str(r['revenue_tmt'])} m.",
                f"${money_str(r['cogs_usd'])} / {money_str(r['cogs_tmt'])} m.",
                f"${money_str(r['profit_usd'])} / {money_str(r['profit_tmt'])} m.",
                last_str,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c >= 3:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.products_table.setItem(i, c, cell)

    def _load_devices_report(self, *_args) -> None:
        st_filter = self.dev_status_combo.currentData()
        query = self.dev_search.text().strip()
        with SessionLocal() as session:
            self.device_rows = ReportService.get_device_report(session, query, st_filter)

        self.devices_table.setRowCount(len(self.device_rows))
        for i, r in enumerate(self.device_rows):
            p_date = (
                r["purchase_date"].strftime("%d.%m.%Y")
                if r["purchase_date"]
                else "—"
            )
            s_date = (
                r["sale_date"].strftime("%d.%m.%Y %H:%M")
                if r["sale_date"]
                else "—"
            )
            sell_txt = (
                f"{money_str(r['selling_price'])} {r['sale_currency']}"
                if r["selling_price"] is not None
                else "—"
            )
            prof_txt = (
                f"{money_str(r['profit'])} {r['sale_currency']}"
                if r["profit"] is not None
                else "—"
            )
            vals = [
                r["imei1"],
                r["model_name"],
                "Täze" if r["condition"] == "new" else "B/U",
                p_date,
                r["supplier"],
                f"{money_str(r['purchase_cost'])} {r['cost_currency']}",
                s_date,
                sell_txt,
                prof_txt,
                r["status_label"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (2, 3, 5, 6, 7, 8, 9):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 9:
                    cell.setForeground(
                        QColor(theme.GREEN if r["status"] == "in_stock" else theme.MUTED)
                    )
                self.devices_table.setItem(i, c, cell)

    def _load_inventory_report(self) -> None:
        with SessionLocal() as session:
            data = ReportService.get_inventory_report(session)

        cats_summary = ", ".join(
            f"{k}: {v} sany" for k, v in data["by_category"].items()
        ) or "maglumat ýok"
        self.inv_summary_label.setText(
            f"Skladda jemi: {data['total_units']} sany  |  "
            f"IMEI enjamlar: {data['total_devices']} sany  |  "
            f"Aksessuarlar we sanly harytlar: {data['total_accessories']} sany\n"
            f"Az galyndy: {data['low_stock_count']} setir  |  "
            f"Skladda ýok: {data['out_of_stock_count']} setir  |  "
            f"Kategoriýalar boýunça: {cats_summary}"
        )

        self.inventory_rows = data["rows"]
        self.inventory_table.setRowCount(len(self.inventory_rows))
        for i, r in enumerate(self.inventory_rows):
            vals = [
                r["sku"],
                r["name"],
                r["category"],
                r["model"],
                str(r["stock_quantity"]),
                str(r["imei_devices"]),
                str(r["quantitative_units"]),
                r["state"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (4, 5, 6, 7):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7:
                    color = (
                        theme.RED
                        if r["state"] == "Skladda ýok"
                        else (theme.ACCENT if r["state"] == "Az galyndy" else theme.GREEN)
                    )
                    cell.setForeground(QColor(color))
                self.inventory_table.setItem(i, c, cell)

    def _load_suppliers_report(self, *_args) -> None:
        query = self.sup_rep_search.text().strip()
        with SessionLocal() as session:
            self.supplier_rows = ReportService.get_supplier_report(session, query)

        self.suppliers_table.setRowCount(len(self.supplier_rows))
        for i, r in enumerate(self.supplier_rows):
            has_debt = (
                r["debt_usd"] > 0
                or r["debt_tmt"] > 0
                or r["supplier_owes_usd"] > 0
                or r["supplier_owes_tmt"] > 0
            )
            status = "Açyk balans bar" if has_debt else "Hasaplaşyk ýapyldy"
            vals = [
                r["supplier_name"],
                f"{r['active_purchases']} / {r['cancelled_purchases']}",
                str(r["units_supplied"]),
                f"${money_str(r['total_usd'])} / {money_str(r['total_tmt'])} m.",
                f"${money_str(r['paid_usd'])} / {money_str(r['paid_tmt'])} m.",
                f"${money_str(r['debt_usd'])} / {money_str(r['debt_tmt'])} m.",
                f"${money_str(r['supplier_owes_usd'])} / {money_str(r['supplier_owes_tmt'])} m.",
                status,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c >= 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7:
                    cell.setForeground(QColor(theme.ACCENT if has_debt else theme.GREEN))
                self.suppliers_table.setItem(i, c, cell)

    def _load_customers_report(self, *_args) -> None:
        query = self.cust_rep_search.text().strip()
        with SessionLocal() as session:
            self.customer_rows = ReportService.get_customer_report(session, query)

        self.customers_table.setRowCount(len(self.customer_rows))
        for i, r in enumerate(self.customer_rows):
            has_debt = (
                r["debt_usd"] > 0
                or r["debt_tmt"] > 0
                or r["store_owes_usd"] > 0
                or r["store_owes_tmt"] > 0
            )
            status = "Açyk balans bar" if has_debt else "Hasaplaşyk ýapyldy"
            vals = [
                r["customer_label"],
                f"{r['active_sales']} / {r['cancelled_sales']}",
                str(r["exchanges_count"]),
                f"${money_str(r['total_usd'])} / {money_str(r['total_tmt'])} m.",
                f"${money_str(r['paid_usd'])} / {money_str(r['paid_tmt'])} m.",
                f"${money_str(r['debt_usd'])} / {money_str(r['debt_tmt'])} m.",
                f"${money_str(r['store_owes_usd'])} / {money_str(r['store_owes_tmt'])} m.",
                status,
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c >= 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7:
                    cell.setForeground(QColor(theme.ACCENT if has_debt else theme.GREEN))
                self.customers_table.setItem(i, c, cell)

    def _open_sales_report_receipt(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self.sales_rows)):
            return
        sale_id = self.sales_rows[row]["sale_id"]
        dlg = SaleDetailsDialog(sale_id, self)
        dlg.exec()
        self.refresh_data()

    def _open_selected_product_history(self) -> None:
        row = self.products_table.currentRow()
        if not (0 <= row < len(self.product_rows)):
            show_toast(self, "Hereket taryhyny açmak üçin tablisadan haryt saýlaň.", kind="info")
            return
        p = self.product_rows[row]
        dlg = ProductHistoryDialog(p["product_id"], p["name"], self)
        dlg.exec()

    def _open_selected_imei_history(self) -> None:
        row = self.devices_table.currentRow()
        if not (0 <= row < len(self.device_rows)):
            show_toast(self, "IMEI-niň doly taryhyny açmak üçin tablisadan enjam saýlaň.", kind="info")
            return
        d = self.device_rows[row]
        dlg = ImeiHistoryDialog(d["stock_item_id"], d["imei1"], d["model_name"], self)
        dlg.exec()

    def _current_report_meta(self) -> tuple[str, str, QTableWidget]:
        idx = self.tabs.currentIndex()
        mapping = [
            ("sales_report", "Satyş hasabaty", self.sales_table),
            ("profit_report", "Peýda hasabaty (COGS)", self.profit_table),
            ("product_report", "Haryt hasabaty", self.products_table),
            ("device_imei_report", "Enjam hasabaty (IMEI)", self.devices_table),
            ("inventory_report", "Sklad hasabaty", self.inventory_table),
            ("supplier_report", "Üpjün edijiler hasabaty", self.suppliers_table),
            ("customer_report", "Müşderiler hasabaty", self.customers_table),
        ]
        return mapping[idx]

    def _default_export_filename(self, slug: str, ext: str) -> str:
        d_from, d_to = self._get_date_range()
        if d_from and d_to:
            period_str = f"{d_from:%Y%m%d}_{d_to:%Y%m%d}"
        else:
            period_str = f"all_{datetime.now():%Y%m%d}"
        return f"mobilestore_{slug}_{period_str}.{ext}"

    def _export_current_csv(self) -> None:
        slug, title, table = self._current_report_meta()
        default_name = self._default_export_filename(slug, "csv")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"«{title}» CSV eksporty",
            str(Path.home() / default_name),
            "CSV Files (*.csv)",
        )
        if not file_path:
            return

        try:
            headers = [
                table.horizontalHeaderItem(c).text()
                for c in range(table.columnCount())
            ]
            with Path(file_path).open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for r in range(table.rowCount()):
                    row_vals = [
                        table.item(r, c).text() if table.item(r, c) else ""
                        for c in range(table.columnCount())
                    ]
                    writer.writerow(row_vals)

            show_toast(
                self,
                f"CSV hasabat ýatda saklandy: {file_path}",
                kind="success",
                duration_ms=4000,
            )
        except OSError as e:
            QMessageBox.critical(self, "Eksport ýalňyşlygy", f"CSV ýatda saklap bolmady:\n{e}")

    def _export_current_pdf(self) -> None:
        slug, title, table = self._current_report_meta()
        default_name = self._default_export_filename(slug, "pdf")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"«{title}» PDF eksporty",
            str(Path.home() / default_name),
            "PDF Files (*.pdf)",
        )
        if not file_path:
            return

        try:
            headers = [
                escape(table.horizontalHeaderItem(c).text())
                for c in range(table.columnCount())
            ]
            th_html = "".join(
                f"<th style='padding:6px;background:#F2F4F7;border:1px solid #D0D5DD;'>{h}</th>"
                for h in headers
            )
            rows_html = []
            for r in range(table.rowCount()):
                tds = "".join(
                    f"<td style='padding:5px;border:1px solid #E8EBF0;'>"
                    f"{escape(table.item(r, c).text() if table.item(r, c) else '')}</td>"
                    for c in range(table.columnCount())
                )
                rows_html.append(f"<tr>{tds}</tr>")

            body_rows = "".join(rows_html)
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            html = f"""
            <html>
            <head><meta charset="utf-8"></head>
            <body style="font-family: sans-serif; font-size: 9pt; color: #1D2939;">
                <h2 style="margin-bottom:4px;">MobileStore — {escape(title)}</h2>
                <p style="color:#667085; margin-top:0;">Taýýarlandy: {now_str} | Döwür: {escape(self.preset_combo.currentText())}</p>
                <table width="100%" cellspacing="0" cellpadding="3" style="border-collapse:collapse;">
                    <thead><tr>{th_html}</tr></thead>
                    <tbody>{body_rows}</tbody>
                </table>
            </body>
            </html>
            """

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)

            doc = QTextDocument()
            doc.setHtml(html)
            doc.print_(printer)

            show_toast(
                self,
                f"PDF hasabat ýatda saklandy: {file_path}",
                kind="success",
                duration_ms=4000,
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "PDF eksport ýalňyşlygy", f"PDF döredip bolmady:\n{e}")
