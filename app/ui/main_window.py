
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.product import Product
from app.models.sale import Sale
from app.models.stock_item import StockItem
from app.services.backup_service import BackupService
from app.services.mobile_ws_server import MobileWebSocketServer
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.dashboard_page import DashboardPage
from app.ui.exchange_page import ExchangePage
from app.ui.finance_page import FinancePage
from app.ui.purchase_page import PurchasePage
from app.ui.quick_search_dialog import QuickSearchDialog
from app.ui.reports_page import ReportsPage
from app.ui.sales_page import SalesPage
from app.ui.settings_page import SettingsPage
from app.ui.stock_page import StockPage

NAV = [
    ("Esasy", [
        ("Esasy panel", "⌂"),
    ]),
    ("Harytlar", [
        ("Harytlar we sklad", "▦"),
        ("Alyşlar", "⇩"),
    ]),
    ("Satyş", [
        ("Satyş we kassa", "◉"),
        ("Trade-in", "⇄"),
    ]),
    ("Maliýe", [
        ("Maliýe", "₮"),
    ]),
    ("Analitika", [
        ("Hasabatlar", "▥"),
    ]),
    ("Ulgam", [
        ("Sazlamalar", "⚙"),
    ]),
]


class PlaceholderPage(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)

        head = QLabel(title)
        head.setObjectName("pageTitle")

        note = QLabel("Bölüm taýýarlanýar")
        note.setObjectName("mutedText")

        layout.addWidget(head)
        layout.addWidget(note)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MobileStore")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(theme.STYLE)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)

        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self.mobile_server = MobileWebSocketServer(
            add_to_sale_callback=self._handle_mobile_add_to_sale,
            is_imei_in_cart_callback=self._is_imei_in_cart,
            parent=self,
        )
        self.sales_page: SalesPage | None = None
        self.settings_page: SettingsPage | None = None

        self._register_pages()
        self._restore_ui_state()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_quick_search)
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_current_page)
        for idx in range(min(8, len(self.nav_buttons))):
            QShortcut(
                QKeySequence(f"Ctrl+{idx + 1}"),
                self,
                activated=lambda i=idx: self._switch_page(i),
            )
        BackupService.run_auto_backup_if_due()

        self.scanner_status_label = QLabel("📱 Skaner: öçük")
        self.scanner_status_label.setStyleSheet("padding: 0 10px; font-weight: 600;")
        self.statusBar().addPermanentWidget(self.scanner_status_label)

        self.mobile_server.devicesChanged.connect(self._on_mobile_devices_changed)
        self.mobile_server.serverStateChanged.connect(self._on_mobile_server_state_changed)
        self.mobile_server.dataMutated.connect(self._on_mobile_data_mutated)

        if SettingsService.get("mobile_server_enabled", "1") == "1":
            self.mobile_server.start()
        self._update_scanner_status_badge()

        self.statusBar().showMessage("Taýýar • Ýerli maglumat bazasy  |  Çalt gözleg: Ctrl+K")

    def _restore_ui_state(self) -> None:
        qs = QSettings("MobileStore", "MobileStore")
        geom = qs.value("main_window/geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        last_idx = qs.value("main_window/last_page_index", 0)
        try:
            idx = int(last_idx)
            if 0 <= idx < self.pages.count():
                self._switch_page(idx)
        except (ValueError, TypeError):
            pass

    def closeEvent(self, event) -> None:
        self.mobile_server.stop()
        qs = QSettings("MobileStore", "MobileStore")
        qs.setValue("main_window/geometry", self.saveGeometry())
        qs.setValue("main_window/last_page_index", self.pages.currentIndex())
        super().closeEvent(event)

    def _register_pages(self) -> None:
        for index, button in enumerate(self.nav_buttons):
            name = button.property("title")

            if name == "Esasy panel":
                page = DashboardPage()
                page.navigateRequested.connect(self.navigate_to_title)
            elif name == "Harytlar we sklad":
                page = StockPage()
            elif name == "Satyş we kassa":
                page = SalesPage()
                self.sales_page = page
            elif name == "Trade-in":
                page = ExchangePage()
            elif name == "Alyşlar":
                page = PurchasePage()
            elif name == "Maliýe":
                page = FinancePage()
            elif name == "Hasabatlar":
                page = ReportsPage()
            elif name == "Sazlamalar":
                page = SettingsPage(mobile_server=self.mobile_server)
                self.settings_page = page
            else:
                page = PlaceholderPage(name)

            self.pages.addWidget(page)
            button.clicked.connect(
                lambda _=False, idx=index: self._switch_page(idx)
            )

        self.nav_buttons[0].setChecked(True)

    def _is_imei_in_cart(self, imei: str) -> bool:
        if self.sales_page is None:
            return False
        return self.sales_page.has_imei_in_cart(imei)

    def _handle_mobile_add_to_sale(self, item_data: dict) -> tuple[bool, str, dict | None]:
        if self.sales_page is None:
            return False, "Kassa bölümi entek açylmadyk.", None
        ok, msg, details = self.sales_page.add_item_from_mobile(item_data)
        if ok:
            if self.pages.currentWidget() is not self.sales_page:
                self.navigate_to_title("Satyş we kassa")
            self.raise_()
            self.activateWindow()
            self.statusBar().showMessage(f"📱 {msg}", 8000)
        return ok, msg, details

    def _on_mobile_devices_changed(self, _devices: list) -> None:
        self._update_scanner_status_badge()

    def _on_mobile_server_state_changed(self, _running: bool, _message: str) -> None:
        self._update_scanner_status_badge()

    def _update_scanner_status_badge(self) -> None:
        if not self.mobile_server.is_running():
            self.scanner_status_label.setText("📱 Skaner: öçük")
            self.scanner_status_label.setStyleSheet(
                f"padding: 0 10px; font-weight: 600; color: {theme.MUTED};"
            )
            return
        auth_devices = [d for d in self.mobile_server.get_connected_devices() if d.get("authenticated")]
        cnt = len(auth_devices)
        port = self.mobile_server.port
        color = theme.GREEN if cnt > 0 else theme.TEAL
        self.scanner_status_label.setText(f"📱 Skanerler: {cnt} (port {port})")
        self.scanner_status_label.setStyleSheet(
            f"padding: 0 10px; font-weight: 600; color: {color};"
        )

    def _on_mobile_data_mutated(self, action_type: str) -> None:
        widget = self.pages.currentWidget()
        if widget is None or widget is self.settings_page:
            return
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()
        self.statusBar().showMessage(
            f"📱 Maglumatlar mobil skanerden täzelendi ({action_type})",
            6000,
        )

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        widget = self.pages.widget(index)
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()

    def navigate_to_title(self, title: str) -> None:
        target = "Harytlar we sklad" if title in ("Sklad", "Haryt katalogi", "Склад", "Каталог товаров") else title
        for index, button in enumerate(self.nav_buttons):
            if button.property("title") == target:
                self._switch_page(index)
                return

    def _refresh_current_page(self) -> None:
        widget = self.pages.currentWidget()
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()
        self.statusBar().showMessage("Täzelendi (F5)", 2500)

    def _open_quick_search(self, initial_text: str = "") -> None:
        self._hide_top_search_popup()
        query = initial_text or self.top_search.text().strip()
        dlg = QuickSearchDialog(initial_query=query, parent=self)
        if dlg.exec() and dlg.selected_for_pos:
            sel = dlg.selected_for_pos
            self.navigate_to_title("Satyş we kassa")
            current = self.pages.currentWidget()
            if hasattr(current, "_append_to_cart"):
                with SessionLocal() as session:
                    prod = session.get(Product, sel["product_id"])
                    if prod:
                        current._append_to_cart(prod, sel.get("imei"))
        self.top_search.clear()

    def _on_global_search(self) -> None:
        q = self.top_search.text().strip()
        self._open_quick_search(q)

    def _hide_top_search_popup(self) -> None:
        if hasattr(self, "top_search_popup") and self.top_search_popup is not None:
            self.top_search_popup.hide()

    def _schedule_top_live_search(self, text: str) -> None:
        if len(text.strip()) < 2:
            self._hide_top_search_popup()
            return
        self._top_search_timer.start(180)

    def _run_top_live_search(self) -> None:
        q = self.top_search.text().strip()
        if len(q) < 2:
            self._hide_top_search_popup()
            return

        self.top_search_popup.clear()
        with SessionLocal() as session:
            prods = session.scalars(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    (Product.name.ilike(f"%{q}%"))
                    | (Product.sku.ilike(f"%{q}%"))
                    | (Product.barcode.ilike(f"%{q}%"))
                    | (Product.brand.ilike(f"%{q}%"))
                    | (Product.model.ilike(f"%{q}%")),
                )
                .order_by(Product.stock_quantity.desc(), Product.name.asc())
                .limit(6)
            ).all()
            for p in prods:
                bc = f" • {p.barcode}" if p.barcode else ""
                item = QListWidgetItem(f"📦 {p.name} ({p.sku}{bc}) — Skladda: {p.stock_quantity} sany")
                item.setData(Qt.ItemDataRole.UserRole, {"kind": "product", "product_id": p.id, "imei": None})
                self.top_search_popup.addItem(item)

            imeis = session.execute(
                select(StockItem, Product)
                .join(Product, StockItem.product_id == Product.id)
                .where(
                    (StockItem.imei1.ilike(f"%{q}%"))
                    | (StockItem.imei2.ilike(f"%{q}%"))
                    | (StockItem.serial_number.ilike(f"%{q}%"))
                )
                .order_by(StockItem.id.desc())
                .limit(5)
            ).all()
            for st, prod in imeis:
                st_lbl = "Bar" if st.status == "in_stock" else "Satyldy"
                item = QListWidgetItem(f"📱 {prod.name} • IMEI: {st.imei1} [{st_lbl}]")
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    {"kind": "imei", "product_id": prod.id, "imei": st.imei1, "in_stock": st.status == "in_stock"},
                )
                self.top_search_popup.addItem(item)

            sales = session.scalars(
                select(Sale)
                .where(
                    (Sale.receipt_number.ilike(f"%{q}%"))
                    | (Sale.customer_name.ilike(f"%{q}%"))
                    | (Sale.customer_phone.ilike(f"%{q}%"))
                )
                .order_by(Sale.sale_date.desc())
                .limit(4)
            ).all()
            for s in sales:
                cust = s.customer_name or "Bölek müşderi"
                item = QListWidgetItem(f"🧾 Çek {s.receipt_number} • {cust} • {s.total_amount} {s.currency}")
                item.setData(Qt.ItemDataRole.UserRole, {"kind": "sale", "sale_id": s.id})
                self.top_search_popup.addItem(item)

        if self.top_search_popup.count() == 0:
            self._hide_top_search_popup()
            return

        pos = self.top_search.mapToGlobal(QPoint(0, self.top_search.height() + 2))
        self.top_search_popup.move(pos)
        self.top_search_popup.setFixedWidth(max(440, self.top_search.width()))
        h = min(320, self.top_search_popup.count() * 34 + 12)
        self.top_search_popup.setFixedHeight(h)
        self.top_search_popup.show()

    def _on_top_live_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        self._hide_top_search_popup()
        self.top_search.clear()
        kind = data.get("kind")
        if kind in ("product", "imei"):
            self.navigate_to_title("Satyş we kassa")
            current = self.pages.currentWidget()
            if hasattr(current, "_append_to_cart"):
                with SessionLocal() as session:
                    prod = session.get(Product, data["product_id"])
                    if prod and prod.stock_quantity > 0:
                        if kind == "imei" and not data.get("in_stock"):
                            from app.ui.stock_page import StockItemDialog

                            StockItemDialog(product_id=prod.id, product_name=prod.name, parent=self).exec()
                            return
                        current._append_to_cart(prod, data.get("imei"))
                    elif prod:
                        from app.ui.stock_page import StockItemDialog

                        StockItemDialog(product_id=prod.id, product_name=prod.name, parent=self).exec()
        elif kind == "sale" and data.get("sale_id"):
            from app.ui.sales_page import SaleDetailsDialog

            SaleDetailsDialog(data["sale_id"], self).exec()

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(64)

        row = QHBoxLayout(bar)
        row.setContentsMargins(28, 0, 28, 0)
        row.setSpacing(10)

        self.top_search = QLineEdit()
        self.top_search.setObjectName("search")
        self.top_search.setClearButtonEnabled(True)
        self.top_search.setPlaceholderText("Harytlar, ştrihkod, IMEI, müşderiler, çekler (Ctrl+K)…")
        self.top_search.returnPressed.connect(self._on_global_search)
        self.top_search.textChanged.connect(self._schedule_top_live_search)
        row.addWidget(self.top_search)

        self._top_search_timer = QTimer(self)
        self._top_search_timer.setSingleShot(True)
        self._top_search_timer.timeout.connect(self._run_top_live_search)

        self.top_search_popup = QListWidget(self)
        self.top_search_popup.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.top_search_popup.setStyleSheet(
            f"QListWidget {{ background: white; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px; }}"
            "QListWidget::item { padding: 6px 10px; border-radius: 6px; }"
            f"QListWidget::item:hover, QListWidget::item:selected {{ background: #EFF6FF; color: {theme.NAVY}; }}"
        )
        self.top_search_popup.itemClicked.connect(self._on_top_live_item_clicked)
        self.top_search_popup.hide()

        search_btn = QPushButton("🔍 Gözleg (Ctrl+K)")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.clicked.connect(lambda: self._open_quick_search())
        row.addWidget(search_btn)

        row.addStretch()

        sale = QPushButton("+  Täze satyş")
        sale.setObjectName("primaryBtn")
        sale.clicked.connect(lambda: self.navigate_to_title("Satyş we kassa"))

        cash = QPushButton("Kassa we Maliýe")
        cash.setObjectName("darkBtn")
        cash.clicked.connect(lambda: self.navigate_to_title("Maliýe"))

        for button in (sale, cash):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button)

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 10)

        mark = QLabel("M")
        mark.setObjectName("brandMark")

        brand = QLabel("MobileStore")
        brand.setObjectName("brand")

        brand_row.addWidget(mark)
        brand_row.addSpacing(8)
        brand_row.addWidget(brand, 1)

        layout.addLayout(brand_row)

        group = QButtonGroup(self)
        group.setExclusive(True)

        self.nav_buttons: list[QPushButton] = []

        for section, items in NAV:
            label = QLabel(section)
            label.setObjectName("navSection")
            layout.addWidget(label)

            for name, icon in items:
                button = QPushButton(f"{icon}   {name}")
                button.setObjectName("navButton")
                button.setProperty("title", name)
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)

                group.addButton(button)
                layout.addWidget(button)
                self.nav_buttons.append(button)

        layout.addStretch()

        footer = QLabel("Wersiýa 0.1.0")
        footer.setObjectName("sideFooter")
        layout.addWidget(footer)

        return sidebar
