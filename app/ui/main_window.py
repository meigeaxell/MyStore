
from PySide6.QtCore import QEvent, QSettings
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.services.backup_service import BackupService
from app.services.incoming_queue_service import count_queue_items
from app.services.mobile_ws_server import MobileWebSocketServer
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.dashboard_page import DashboardPage
from app.ui.exchange_page import ExchangePage
from app.ui.finance_page import FinancePage
from app.ui.incoming_queue_page import IncomingQueuePage
from app.ui.purchase_page import PurchasePage
from app.ui.reports_page import ReportsPage
from app.ui.sales_page import SalesPage
from app.ui.settings_page import SettingsPage
from app.ui.sidebar import SIDEBAR_COLLAPSED_W, SIDEBAR_EXPANDED_W, SlidingSidebar
from app.ui.stock_page import StockPage
from app.ui.widgets import make_button, show_toast

NAV_SECTIONS = [
    ("Harytlar", [
        ("Harytlar we sklad", "stock"),
        ("Alyşlar", "purchases"),
        ("Kabul ediş nobaty", "queue"),
    ]),
    ("Satyş", [
        ("Satyş we kassa", "sales"),
        ("Trade-in", "tradein"),
    ]),
    ("Maliýe", [
        ("Maliýe", "finance"),
    ]),
    ("Analitika", [
        ("Hasabatlar", "reports"),
    ]),
]

NAV_BOTTOM_ITEM = ("Sazlamalar", "settings")


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

        self._central = QWidget()
        self._central.installEventFilter(self)
        root = QHBoxLayout(self._central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Резервируем место под рельс сайдбара (72px в hover/collapsed или 248px в expanded)
        self._sidebar_rail = QWidget(self._central)
        self._sidebar_rail.setFixedWidth(SIDEBAR_COLLAPSED_W)
        root.addWidget(self._sidebar_rail)

        right = QVBoxLayout()
        right.setSpacing(0)

        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)

        root.addLayout(right, 1)
        self.setCentralWidget(self._central)

        # Боковой сайдбар с 3 режимами (hover / expanded / collapsed)
        self.sidebar = self._build_sidebar()
        self.sidebar.modeChanged.connect(lambda m: self.apply_sidebar_mode(m, persist=True))
        self.apply_sidebar_mode(SettingsService.get_sidebar_mode(), persist=False)

        self.mobile_server = MobileWebSocketServer(
            add_to_sale_callback=self._handle_mobile_add_to_sale,
            is_imei_in_cart_callback=self._is_imei_in_cart,
            parent=self,
        )
        self.dashboard_page: DashboardPage | None = None
        self.stock_page: StockPage | None = None
        self.purchase_page: PurchasePage | None = None
        self.incoming_queue_page: IncomingQueuePage | None = None
        self.incoming_queue_button: QPushButton | None = None
        self.sales_page: SalesPage | None = None
        self.settings_page: SettingsPage | None = None

        self._register_pages()
        self._update_incoming_queue_badge()
        self._restore_ui_state()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._focus_current_page_search)
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_current_page)
        for idx in range(min(9, len(self.nav_buttons))):
            QShortcut(
                QKeySequence(f"Ctrl+{idx + 1}"),
                self,
                activated=lambda i=idx: self._switch_page(i),
            )
        BackupService.run_auto_backup_if_due()

        self.rate_status_btn = make_button("Kurs: —", "link")
        self.rate_status_btn.setToolTip("Kursy üýtgetmek üçin Sazlamalary açyň")
        self.rate_status_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 0; color: {theme.NAVY}; "
            f"font-weight: 600; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {theme.ACCENT}; text-decoration: underline; }}"
        )
        self.rate_status_btn.clicked.connect(lambda: self.navigate_to_title("Sazlamalar"))
        self.statusBar().addPermanentWidget(self.rate_status_btn)

        self.backup_status_label = QLabel("Nusga: —")
        self.backup_status_label.setStyleSheet(f"padding: 0 8px; color: {theme.MUTED};")
        self.statusBar().addPermanentWidget(self.backup_status_label)

        self.scanner_status_label = QLabel("Skaner: öçük")
        self.scanner_status_label.setStyleSheet("padding: 0 10px; font-weight: 600;")
        self.statusBar().addPermanentWidget(self.scanner_status_label)

        self._update_status_bar_meta()

        self.mobile_server.devicesChanged.connect(self._on_mobile_devices_changed)
        self.mobile_server.serverStateChanged.connect(self._on_mobile_server_state_changed)
        self.mobile_server.dataMutated.connect(self._on_mobile_data_mutated)
        self.mobile_server.incomingQueued.connect(self._on_mobile_incoming_queued)

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
        if self.sales_page is not None:
            self.sales_page._hide_live_search_popup()
        self.mobile_server.stop()
        qs = QSettings("MobileStore", "MobileStore")
        qs.setValue("main_window/geometry", self.saveGeometry())
        qs.setValue("main_window/last_page_index", self.pages.currentIndex())
        super().closeEvent(event)

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and getattr(self, "sales_page", None) is not None
        ):
            self.sales_page._hide_live_search_popup()
        super().changeEvent(event)

    def moveEvent(self, event) -> None:
        if getattr(self, "sales_page", None) is not None:
            self.sales_page._hide_live_search_popup()
        super().moveEvent(event)

    def resizeEvent(self, event) -> None:
        if getattr(self, "sales_page", None) is not None:
            self.sales_page._hide_live_search_popup()
        super().resizeEvent(event)
        if getattr(self, "sidebar", None) is not None:
            self.sidebar.sync_geometry()

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is getattr(self, "_central", None)
            and event.type() == QEvent.Type.Resize
            and getattr(self, "sidebar", None) is not None
        ):
            self.sidebar.sync_geometry()
        return super().eventFilter(obj, event)

    def _register_pages(self) -> None:
        for index, button in enumerate(self.nav_buttons):
            name = button.property("title")

            if name in ("MobileStore", "Esasy panel"):
                page = DashboardPage()
                page.navigateRequested.connect(self.navigate_to_title)
                self.dashboard_page = page
            elif name == "Harytlar we sklad":
                page = StockPage()
                self.stock_page = page
            elif name == "Satyş we kassa":
                page = SalesPage()
                self.sales_page = page
            elif name == "Trade-in":
                page = ExchangePage()
            elif name == "Alyşlar":
                page = PurchasePage()
                self.purchase_page = page
            elif name == "Kabul ediş nobaty":
                page = IncomingQueuePage()
                self.incoming_queue_page = page
                self.incoming_queue_button = button
                page.queueChanged.connect(self._update_incoming_queue_badge)
                page.stockCommitted.connect(self._on_incoming_queue_committed)
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
            self.statusBar().showMessage(f"{msg}", 8000)
        return ok, msg, details

    def _on_mobile_devices_changed(self, _devices: list) -> None:
        self._update_scanner_status_badge()

    def _on_mobile_server_state_changed(self, _running: bool, _message: str) -> None:
        self._update_scanner_status_badge()

    def _update_scanner_status_badge(self) -> None:
        if not self.mobile_server.is_running():
            self.scanner_status_label.setText("Skaner: öçük")
            self.scanner_status_label.setStyleSheet(
                f"padding: 0 10px; font-weight: 600; color: {theme.MUTED};"
            )
            return
        auth_devices = [d for d in self.mobile_server.get_connected_devices() if d.get("authenticated")]
        cnt = len(auth_devices)
        port = self.mobile_server.port
        color = theme.GREEN if cnt > 0 else theme.TEAL
        self.scanner_status_label.setText(f"Skanerler: {cnt} (port {port})")
        self.scanner_status_label.setStyleSheet(
            f"padding: 0 10px; font-weight: 600; color: {color};"
        )

    def _on_mobile_data_mutated(self, action_type: str) -> None:
        if action_type == "queue_incoming_item":
            return
        widget = self.pages.currentWidget()
        if widget is None or widget is self.settings_page:
            return
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()
        self.statusBar().showMessage(
            f"Maglumatlar mobil skanerden täzelendi ({action_type})",
            6000,
        )

    def _update_incoming_queue_badge(self, count: int | None = None) -> None:
        if self.incoming_queue_button is None:
            return
        if count is None:
            try:
                count = int(count_queue_items().get("total", 0))
            except SQLAlchemyError:
                count = 0
        n = max(0, int(count))
        if hasattr(self.incoming_queue_button, "set_badge_count"):
            self.incoming_queue_button.set_badge_count(n)
        elif n > 0:
            self.incoming_queue_button.setText(f"Kabul ediş nobaty ({n})")
        else:
            self.incoming_queue_button.setText("Kabul ediş nobaty")

    def _on_mobile_incoming_queued(self, data: dict) -> None:
        counts = data.get("counts") if isinstance(data, dict) else None
        if isinstance(counts, dict) and "total" in counts:
            self._update_incoming_queue_badge(int(counts["total"]))
        else:
            self._update_incoming_queue_badge()

        if self.incoming_queue_page is not None:
            self.incoming_queue_page.refresh_data()

        msg = (
            str(data.get("message") or "").strip()
            if isinstance(data, dict)
            else ""
        ) or "Täze haryt kabul ediş nobatyna goşuldy"
        show_toast(self, f"{msg}", kind="info", duration_ms=4200)
        self.statusBar().showMessage(f"{msg}", 8000)

    def _on_incoming_queue_committed(self) -> None:
        for page in (
            self.dashboard_page,
            self.stock_page,
            self.purchase_page,
            self.sales_page,
        ):
            if page is None:
                continue
            if hasattr(page, "refresh_data"):
                page.refresh_data()
            elif hasattr(page, "_load_data"):
                page._load_data()
        self._update_incoming_queue_badge()

    def _switch_page(self, index: int) -> None:
        if self.sales_page is not None:
            self.sales_page._hide_live_search_popup()
        self.pages.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        widget = self.pages.widget(index)
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()

    def navigate_to_title(self, title: str) -> None:
        if title in ("Esasy panel", "MobileStore", "Главная"):
            self._switch_page(0)
            return
        if title == "Simurg":
            for index, button in enumerate(self.nav_buttons):
                if button.property("title") == "Maliýe":
                    self._switch_page(index)
                    widget = self.pages.widget(index)
                    if hasattr(widget, "open_simurg_tab"):
                        widget.open_simurg_tab()
                    return
        target = "Harytlar we sklad" if title in ("Sklad", "Haryt katalogi", "Склад", "Каталог товаров") else title
        for index, button in enumerate(self.nav_buttons):
            if button.property("title") == target:
                self._switch_page(index)
                return

    def _update_status_bar_meta(self) -> None:
        rate = SettingsService.get_default_exchange_rate()
        self.rate_status_btn.setText(f"1 USD = {rate:.2f} TMT")
        last_at = (SettingsService.get("last_backup_at", "") or "").strip()
        if last_at:
            short = last_at[:16].replace("T", " ")
            self.backup_status_label.setText(f"Nusga: {short}")
            self.backup_status_label.setStyleSheet(f"padding: 0 8px; color: {theme.MUTED};")
        else:
            self.backup_status_label.setText("Nusga: ýok")
            self.backup_status_label.setStyleSheet(
                f"padding: 0 8px; color: {theme.ACCENT}; font-weight: 600;"
            )

    def _refresh_current_page(self) -> None:
        widget = self.pages.currentWidget()
        if hasattr(widget, "refresh_data"):
            widget.refresh_data()
        elif hasattr(widget, "_load_data"):
            widget._load_data()
        self._update_status_bar_meta()
        show_toast(self, "Maglumatlar täzelendi (F5)", kind="info", duration_ms=1600)
        self.statusBar().showMessage("Täzelendi (F5)", 2500)

    def _focus_current_page_search(self) -> None:
        """Переводит фокус (Ctrl+K) на поле поиска текущей открытой вкладки."""
        page = self.pages.currentWidget()
        if page is None:
            return
        scope: QWidget = page
        tabs = getattr(page, "tabs", None)
        if isinstance(tabs, QTabWidget) and tabs.currentWidget() is not None:
            scope = tabs.currentWidget()

        # 1. Приоритет — известные поля поиска на активной вкладке
        known_names = (
            "search_input",
            "history_search",
            "journal_search",
            "simurg_search",
            "sup_search",
            "prod_search",
            "glossary_test_input",
        )
        for attr in known_names:
            w = getattr(page, attr, None)
            if isinstance(w, QLineEdit) and w.isVisible() and w.isEnabled():
                w.setFocus()
                w.selectAll()
                return

        # 2. Иначе ищем любое видимое поле поиска внутри текущей вкладки
        for edit in scope.findChildren(QLineEdit):
            if not edit.isVisible() or not edit.isEnabled():
                continue
            ph = (edit.placeholderText() or "").lower()
            if edit.isClearButtonEnabled() or any(k in ph for k in ("gözleg", "skan", "imei", "synag")):
                edit.setFocus()
                edit.selectAll()
                return

    def apply_sidebar_mode(self, mode: str, persist: bool = True) -> None:
        clean = mode if mode in ("hover", "expanded", "collapsed") else "hover"
        self.sidebar.set_mode(clean)
        self._sidebar_rail.setFixedWidth(
            SIDEBAR_EXPANDED_W if clean == "expanded" else SIDEBAR_COLLAPSED_W
        )
        self.sidebar.sync_geometry()
        if persist:
            SettingsService.set_sidebar_mode(clean)
            if getattr(self, "settings_page", None) is not None and hasattr(
                self.settings_page, "sync_sidebar_mode_combo"
            ):
                self.settings_page.sync_sidebar_mode_combo(clean)

    def _build_sidebar(self) -> SlidingSidebar:
        sidebar = SlidingSidebar(
            sections=NAV_SECTIONS,
            bottom_item=NAV_BOTTOM_ITEM,
            parent=self._central,
        )
        self.nav_buttons: list[QPushButton] = sidebar.nav_buttons
        return sidebar
