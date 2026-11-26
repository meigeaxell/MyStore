
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.sale import Sale
from app.models.stock_item import StockItem
from app.services.backup_service import BackupService
from app.services.incoming_queue_service import count_queue_items
from app.services.mobile_ws_server import MobileWebSocketServer
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.dashboard_page import DashboardPage
from app.ui.exchange_page import ExchangePage
from app.ui.finance_page import FinancePage
from app.ui.incoming_queue_page import IncomingQueuePage
from app.ui.purchase_page import PurchasePage
from app.ui.quick_search_dialog import QuickSearchDialog
from app.ui.reports_page import ReportsPage
from app.ui.sales_page import SalesPage
from app.ui.settings_page import SettingsPage
from app.ui.sidebar import SIDEBAR_COLLAPSED_W, SlidingSidebar
from app.ui.stock_page import StockPage
from app.ui.widgets import SearchResultPopup, make_button, make_icon_button, money_str, show_toast

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

        # Резервируем место под свёрнутый рельс сайдбара (72px), чтобы контент не дёргался при раскрытии
        sidebar_rail = QWidget(self._central)
        sidebar_rail.setFixedWidth(SIDEBAR_COLLAPSED_W)
        root.addWidget(sidebar_rail)

        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)

        root.addLayout(right, 1)
        self.setCentralWidget(self._central)

        # Выдвижной оверлей-сайдбар поверх левого края окна
        self.sidebar = self._build_sidebar()
        self.sidebar.sync_geometry()

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
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_quick_search)
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
        self._hide_top_search_popup()
        if self.sales_page is not None:
            self.sales_page._hide_live_search_popup()
        self.mobile_server.stop()
        qs = QSettings("MobileStore", "MobileStore")
        qs.setValue("main_window/geometry", self.saveGeometry())
        qs.setValue("main_window/last_page_index", self.pages.currentIndex())
        super().closeEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowDeactivate:
            self._hide_top_search_popup()
            if getattr(self, "sales_page", None) is not None:
                self.sales_page._hide_live_search_popup()
        super().changeEvent(event)

    def moveEvent(self, event) -> None:
        self._hide_top_search_popup()
        if getattr(self, "sales_page", None) is not None:
            self.sales_page._hide_live_search_popup()
        super().moveEvent(event)

    def resizeEvent(self, event) -> None:
        self._hide_top_search_popup()
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
        if obj is getattr(self, "top_search", None):
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(160, self._check_hide_top_search_popup)
            elif event.type() == QEvent.Type.KeyPress:
                key = event.key()
                popup = getattr(self, "top_search_popup", None)
                if key == Qt.Key.Key_Escape:
                    self._hide_top_search_popup()
                    return True
                if popup is not None and popup.isVisible():
                    if key == Qt.Key.Key_Down:
                        popup.step_selection(1)
                        return True
                    if key == Qt.Key.Key_Up:
                        popup.step_selection(-1)
                        return True
                    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                        cur = popup.currentItem()
                        if cur is not None:
                            self._on_top_live_item_clicked(cur)
                            return True
        return super().eventFilter(obj, event)

    def _check_hide_top_search_popup(self) -> None:
        if not hasattr(self, "top_search_popup") or not self.top_search_popup.isVisible():
            return
        if self.top_search.hasFocus() or self.top_search_popup.is_interacting():
            return
        if not self.isActiveWindow() or not self.top_search.hasFocus():
            self._hide_top_search_popup()

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
        self._hide_top_search_popup()
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
        if hasattr(self, "_top_search_timer") and self._top_search_timer is not None:
            self._top_search_timer.stop()
        if hasattr(self, "top_search_popup") and self.top_search_popup is not None:
            self.top_search_popup.hide()

    def _schedule_top_live_search(self, text: str) -> None:
        if len(text.strip()) < 2:
            self._hide_top_search_popup()
            return
        self._top_search_timer.start(180)

    def _run_top_live_search(self) -> None:
        if not self.isActiveWindow() or not self.top_search.hasFocus():
            self._hide_top_search_popup()
            return
        q = self.top_search.text().strip()
        if len(q) < 2:
            self._hide_top_search_popup()
            return
        words = [w for w in q.lower().split() if w]
        if not words:
            self._hide_top_search_popup()
            return

        default_curr = SettingsService.get("default_currency", "TMT")
        default_rate = SettingsService.get_default_exchange_rate()

        self.top_search_popup.clear()
        with SessionLocal() as session:
            in_stock_rows = session.scalars(
                select(StockItem)
                .where(StockItem.status == "in_stock")
                .order_by(StockItem.id.desc())
            ).all()
            latest_stock_by_prod: dict[int, StockItem] = {}
            for st in in_stock_rows:
                if st.product_id not in latest_stock_by_prod and st.unit_cost is not None:
                    latest_stock_by_prod[st.product_id] = st

            prod_rows = session.execute(
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(Product.is_active.is_(True))
                .order_by(Product.stock_quantity.desc(), Product.name.asc())
            ).all()
            prod_added = 0
            for p, cat_name in prod_rows:
                if getattr(p, "is_phone_unit", False):
                    continue
                hay = " ".join(
                    filter(
                        None,
                        [
                            p.name,
                            cat_name,
                            p.brand,
                            p.model,
                            p.specification,
                            p.barcode,
                        ],
                    )
                ).lower()
                if not all(w in hay for w in words):
                    continue
                cat_label = cat_name or "—"
                bm = " / ".join(filter(None, [p.brand, p.model])) or "—"
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=p.id,
                    stock_item=latest_stock_by_prod.get(p.id),
                    fallback_currency=default_curr,
                    fallback_rate=default_rate,
                )
                cost_str = f"Öz bahasy: {money_str(u_cost)} {c_curr}" if u_cost > 0 else ""
                qty_val = int(p.stock_quantity or 0)
                self.top_search_popup.add_result_card(
                    title=p.name,
                    category=cat_label,
                    subtitle=bm if not p.specification else f"{bm}  •  {p.specification}",
                    cost_text=cost_str,
                    badge_text=f"Skladda: {qty_val}" if qty_val > 0 else "Ýok",
                    badge_tone="green" if qty_val > 0 else "red",
                    icon_kind="product",
                    payload={"kind": "product", "product_id": p.id, "imei": None},
                )
                prod_added += 1
                if prod_added >= 50:
                    break

            imei_rows = session.execute(
                select(StockItem, Product, Category.name)
                .join(Product, StockItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .order_by(StockItem.status.asc(), StockItem.id.desc())
            ).all()
            imei_added = 0
            for st, prod, cat_name in imei_rows:
                hay = " ".join(
                    filter(
                        None,
                        [
                            prod.name,
                            cat_name,
                            prod.brand,
                            prod.model,
                            prod.specification,
                            prod.barcode,
                            st.imei1,
                            st.imei2,
                            st.serial_number,
                            st.memory,
                            st.color,
                        ],
                    )
                ).lower()
                if not all(w in hay for w in words):
                    continue
                cat_label = cat_name or "—"
                spec_parts = [x for x in (st.memory, st.color) if x]
                if not spec_parts:
                    bm = " / ".join(filter(None, [prod.brand, prod.model]))
                    if bm:
                        spec_parts.append(bm)
                spec_parts.append(f"IMEI: {st.imei1}")
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=prod.id,
                    stock_item=st,
                    fallback_currency=default_curr,
                    fallback_rate=default_rate,
                )
                cost_str = f"Öz bahasy: {money_str(u_cost)} {c_curr}" if u_cost > 0 else ""
                is_in = st.status == "in_stock"
                cond_lbl = "Täze" if st.condition == "new" else "B/U"
                self.top_search_popup.add_result_card(
                    title=prod.name,
                    category=cat_label,
                    subtitle=" • ".join(spec_parts),
                    cost_text=cost_str,
                    badge_text=f"Bar ({cond_lbl})" if is_in else "Satyldy",
                    badge_tone=("blue" if st.condition == "new" else "orange") if is_in else "muted",
                    icon_kind="imei",
                    payload={"kind": "imei", "product_id": prod.id, "imei": st.imei1, "in_stock": is_in},
                )
                imei_added += 1
                if imei_added >= 40:
                    break

            sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc())).all()
            sale_added = 0
            for s in sales:
                hay = " ".join(
                    filter(None, [s.receipt_number, s.customer_name, s.customer_phone])
                ).lower()
                if not all(w in hay for w in words):
                    continue
                cust = s.customer_name or "Bölek müşderi"
                date_s = s.sale_date.strftime("%d.%m.%Y %H:%M") if s.sale_date else ""
                self.top_search_popup.add_result_card(
                    title=f"Çek {s.receipt_number}",
                    category="Satyş çeki",
                    subtitle=f"{cust}  •  {date_s}",
                    cost_text=f"{money_str(s.total_amount)} {s.currency}",
                    badge_text="Ýatyryldy" if s.status == "cancelled" else "Çek",
                    badge_tone="red" if s.status == "cancelled" else "muted",
                    icon_kind="sale",
                    payload={"kind": "sale", "sale_id": s.id},
                )
                sale_added += 1
                if sale_added >= 12:
                    break

        if self.top_search_popup.count() == 0:
            self._hide_top_search_popup()
            return

        self.top_search_popup.show_below(self.top_search, min_width=680, max_height=420)

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
        self.top_search.setPlaceholderText(
            "Harytlar, kategoriýa, brend, model, ştrihkod, IMEI, müşderiler (Ctrl+K)…"
        )
        self.top_search.returnPressed.connect(self._on_global_search)
        self.top_search.textChanged.connect(self._schedule_top_live_search)
        self.top_search.installEventFilter(self)
        row.addWidget(self.top_search)

        self._top_search_timer = QTimer(self)
        self._top_search_timer.setSingleShot(True)
        self._top_search_timer.timeout.connect(self._run_top_live_search)

        self.top_search_popup = SearchResultPopup(self)
        self.top_search_popup.itemClicked.connect(self._on_top_live_item_clicked)
        self.top_search_popup.hide()

        search_btn = make_icon_button("Gözleg (Ctrl+K)", "search")
        search_btn.clicked.connect(lambda: self._open_quick_search())
        row.addWidget(search_btn)

        row.addStretch()

        sale = make_button("+  Täze satyş", "primary")
        sale.clicked.connect(lambda: self.navigate_to_title("Satyş we kassa"))

        cash = make_button("Kassa we Maliýe", "dark")
        cash.clicked.connect(lambda: self.navigate_to_title("Maliýe"))

        row.addWidget(sale)
        row.addWidget(cash)

        return bar

    def _build_sidebar(self) -> SlidingSidebar:
        sidebar = SlidingSidebar(
            sections=NAV_SECTIONS,
            bottom_item=NAV_BOTTOM_ITEM,
            parent=self._central,
        )
        self.nav_buttons: list[QPushButton] = sidebar.nav_buttons
        return sidebar
