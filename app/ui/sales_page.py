from datetime import datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.sale_payment import SalePayment
from app.models.stock_item import StockItem
from app.services.sales_service import SalesService, _convert_currency
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.receipt_printer import export_sale_receipt_pdf
from app.ui.selection_dialogs import InventorySelectorDialog
from app.ui.widgets import (
    Card,
    configure_dialog_buttons,
    configure_table,
    make_button,
    money_str,
    show_toast,
    style_combo,
)


class HeldCartsDialog(QDialog):
    """Окно просмотра и восстановления отложенных чеков (черновиков продаж)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Garaşýan çekler")
        self.setMinimumSize(640, 400)
        self.setStyleSheet(theme.STYLE)
        self.carts = SettingsService.get_held_carts()
        self.selected_cart: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        title = QLabel("Garaşýan çekler (garalamalar)")
        title.setObjectName("cardTitle")
        root.addWidget(title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Wagt", "Müşderi / Bellik", "Setirler", "Jemi"])
        configure_table(self.table, stretch_col=1, row_height=42)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._restore_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        del_btn = make_button("Garalamany poz", "danger")
        del_btn.clicked.connect(self._delete_selected)
        footer.addWidget(del_btn)
        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.reject)
        restore_btn = make_button("Çeki kassa gaýtar", "primary")
        restore_btn.clicked.connect(self._restore_selected)
        footer.addWidget(close_btn)
        footer.addWidget(restore_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, restore_btn, close_btn)
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.carts))
        for r, c in enumerate(self.carts):
            items = c.get("items", [])
            total = sum(
                Decimal(str(i.get("quantity", 1))) * Decimal(str(i.get("unit_price", "0")))
                for i in items
            )
            cur = c.get("currency", "TMT")
            label = c.get("customer_name") or c.get("comment") or "Atsyz müşderi"
            vals = [
                c.get("created_at", "—"),
                label,
                f"{len(items)} setir",
                f"{money_str(total)} {cur}",
            ]
            for col, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if col in (0, 2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, cell)
        if self.carts:
            self.table.selectRow(0)

    def _restore_selected(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.carts)):
            return
        self.selected_cart = self.carts.pop(row)
        SettingsService.save_held_carts(self.carts)
        self.accept()

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.carts)):
            return
        self.carts.pop(row)
        SettingsService.save_held_carts(self.carts)
        self._refresh_table()


class SaleDetailsDialog(QDialog):
    """Просмотр чека продажи, печать PDF, история платежей, долг клиента и отмена."""

    def __init__(self, sale_id: int, parent=None) -> None:
        super().__init__(parent)
        self.sale_id = sale_id

        self.setWindowTitle(f"Çek №{sale_id}")
        self.resize(860, 720)
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

        top_bar = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        top_bar.addWidget(self.title_label, 1)

        print_btn = make_button("🖨 Çap et / PDF çek", "primary")
        print_btn.clicked.connect(lambda: export_sale_receipt_pdf(self.sale_id, self))
        top_bar.addWidget(print_btn)
        root.addLayout(top_bar)

        self.info_label = QLabel()
        self.info_label.setObjectName("mutedText")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        self.status_label = QLabel()
        root.addWidget(self.status_label)

        self.debt_label = QLabel()
        root.addWidget(self.debt_label)

        self.cancel_info_label = QLabel()
        self.cancel_info_label.setObjectName("mutedText")
        self.cancel_info_label.setWordWrap(True)
        root.addWidget(self.cancel_info_label)

        items_title = QLabel("Çekiň setirleri")
        items_title.setObjectName("cardTitle")
        root.addWidget(items_title)

        self.items_table = QTableWidget(0, 6)
        self.items_table.setHorizontalHeaderLabels([
            "Haryt", "IMEI", "Sany", "Baha", "Öz bahasy", "Jemi",
        ])
        configure_table(self.items_table, stretch_col=0, row_height=42)
        self.items_table.setMinimumHeight(130)
        root.addWidget(self.items_table)

        payments_title = QLabel("Tölegler we hasaplaşyklar taryhy")
        payments_title.setObjectName("cardTitle")
        root.addWidget(payments_title)

        self.payments_table = QTableWidget(0, 5)
        self.payments_table.setHorizontalHeaderLabels([
            "Sene", "Görnüş", "Walýuta", "Jemi", "Kurs",
        ])
        configure_table(self.payments_table, stretch_col=1, row_height=40)
        self.payments_table.setMinimumHeight(110)
        root.addWidget(self.payments_table)

        self.pay_debt_section = QWidget()
        p_layout = QVBoxLayout(self.pay_debt_section)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(8)

        p_title = QLabel("Müşderiniň bergisinden töleg kabul etmek")
        p_title.setObjectName("cardTitle")
        p_layout.addWidget(p_title)

        p_row = QHBoxLayout()
        self.pay_curr_combo = style_combo(QComboBox())
        self.pay_curr_combo.addItems(["TMT", "USD"])
        self.pay_amt_spin = QDoubleSpinBox()
        self.pay_amt_spin.setRange(0, 10000000)
        self.pay_amt_spin.setDecimals(2)
        self.pay_rate_spin = QDoubleSpinBox()
        self.pay_rate_spin.setRange(0.0001, 100000)
        self.pay_rate_spin.setDecimals(4)
        self.pay_rate_spin.setValue(19.5)

        add_pay_btn = make_button("Tölegi kabul et", "primary")
        add_pay_btn.clicked.connect(self._add_customer_payment)

        p_row.addWidget(QLabel("Walýuta:"))
        p_row.addWidget(self.pay_curr_combo)
        p_row.addWidget(QLabel("Jemi:"))
        p_row.addWidget(self.pay_amt_spin, 1)
        p_row.addWidget(QLabel("Kurs:"))
        p_row.addWidget(self.pay_rate_spin)
        p_row.addWidget(add_pay_btn)
        p_layout.addLayout(p_row)
        root.addWidget(self.pay_debt_section)

        self.settle_store_debt_section = QWidget()
        s_layout = QVBoxLayout(self.settle_store_debt_section)
        s_layout.setContentsMargins(0, 0, 0, 0)
        s_layout.setSpacing(8)

        s_title = QLabel("Dükanyň müşderä bergisini tölemek (ýatyrylan çek)")
        s_title.setObjectName("cardTitle")
        s_layout.addWidget(s_title)

        s_row = QHBoxLayout()
        self.settle_curr_combo = style_combo(QComboBox())
        self.settle_curr_combo.addItems(["TMT", "USD"])
        self.settle_amt_spin = QDoubleSpinBox()
        self.settle_amt_spin.setRange(0, 10000000)
        self.settle_amt_spin.setDecimals(2)
        self.settle_rate_spin = QDoubleSpinBox()
        self.settle_rate_spin.setRange(0.0001, 100000)
        self.settle_rate_spin.setDecimals(4)
        self.settle_rate_spin.setValue(19.5)

        settle_btn = make_button("Tölegi hasaba al", "primary")
        settle_btn.clicked.connect(self._settle_store_debt)

        s_row.addWidget(QLabel("Walýuta:"))
        s_row.addWidget(self.settle_curr_combo)
        s_row.addWidget(QLabel("Jemi:"))
        s_row.addWidget(self.settle_amt_spin, 1)
        s_row.addWidget(QLabel("Kurs:"))
        s_row.addWidget(self.settle_rate_spin)
        s_row.addWidget(settle_btn)
        s_layout.addLayout(s_row)
        root.addWidget(self.settle_store_debt_section)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        footer_bar = QWidget()
        footer_bar.setObjectName("dialogFooter")
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(24, 12, 24, 12)
        footer.addStretch()

        self.cancel_sale_btn = make_button("Çeki ýatyr", "danger")
        self.cancel_sale_btn.clicked.connect(self._cancel_sale)
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)

        footer.addWidget(self.cancel_sale_btn)
        footer.addWidget(close_btn)
        outer.addWidget(footer_bar)
        configure_dialog_buttons(self, add_pay_btn, close_btn)

    def _load_data(self) -> None:
        with SessionLocal() as session:
            sale = session.get(Sale, self.sale_id)
            if sale is None:
                QMessageBox.warning(self, "Tapylmady", "Çek tapylmady.")
                self.reject()
                return

            self.title_label.setText(f"Çek {sale.receipt_number}")
            customer_str = sale.customer_name or "Bölek müşderi"
            if sale.customer_phone:
                customer_str += f" ({sale.customer_phone})"

            simurg_str = ""
            if getattr(sale, "is_simurg", False):
                p_dt = getattr(sale, "simurg_payout_date", None)
                p_str = p_dt.strftime("%d.%m.%Y") if p_dt else "—"
                simurg_str = f"   |   🏦 Simurg (aljak güni: {p_str})"

            self.info_label.setText(
                f"Sene: {sale.sale_date:%d.%m.%Y %H:%M}   |   "
                f"Müşderi: {customer_str}   |   "
                f"Walýuta: {sale.currency} (Kurs: {sale.exchange_rate})   |   "
                f"Çekiň jemi: {money_str(sale.total_amount)} {sale.currency}{simurg_str}"
            )

            self.pay_rate_spin.setValue(float(Decimal(str(sale.exchange_rate or 19.5))))
            self.settle_rate_spin.setValue(float(Decimal(str(sale.exchange_rate or 19.5))))

            item_rows = session.execute(
                select(SaleItem, Product.name)
                .join(Product, SaleItem.product_id == Product.id)
                .where(SaleItem.sale_id == sale.id)
            ).all()

            self.items_table.setRowCount(len(item_rows))
            for idx, (s_item, p_name) in enumerate(item_rows):
                line_sum = Decimal(str(s_item.unit_price)) * s_item.quantity - Decimal(str(s_item.discount))
                cost_txt = f"{money_str(s_item.unit_cost)} {s_item.cost_currency}"
                vals = [
                    p_name,
                    s_item.imei or "—",
                    str(s_item.quantity),
                    f"{money_str(s_item.unit_price)} {s_item.currency}",
                    cost_txt,
                    f"{money_str(line_sum)} {s_item.currency}",
                ]
                for c, val in enumerate(vals):
                    cell = QTableWidgetItem(val)
                    if c >= 2:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.items_table.setItem(idx, c, cell)

            payments = session.scalars(
                select(SalePayment)
                .where(SalePayment.sale_id == sale.id)
                .order_by(SalePayment.payment_date)
            ).all()
            self.payments_table.setRowCount(len(payments))
            type_labels = {
                "payment": "Müşderiniň tölegi",
                "reversal": "Ýatyrmada yzyna gaýtarma",
                "customer_debt_settlement": "Dükanyň bergisini ýapmak",
            }
            for idx, pay in enumerate(payments):
                p_date = pay.payment_date.strftime("%d.%m.%Y %H:%M") if pay.payment_date else "—"
                vals = [
                    p_date,
                    type_labels.get(pay.payment_type, pay.payment_type),
                    pay.currency,
                    money_str(pay.amount),
                    f"{Decimal(str(pay.exchange_rate)):,.4f}",
                ]
                for c, val in enumerate(vals):
                    cell = QTableWidgetItem(val)
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.payments_table.setItem(idx, c, cell)

            customer_debt = SalesService.get_customer_debt(session, sale)
            store_debt = SalesService.get_store_debt_to_customer(session, sale)
            paid_amt = SalesService.get_sale_paid_amount(session, sale)

            if sale.status == "cancelled":
                self.status_label.setText("Status: Ýatyryldy")
                self.status_label.setStyleSheet(
                    "font-weight: 700; color: #737B86; background: #F0F1F3; padding: 8px 12px; border-radius: 8px;"
                )
                self.debt_label.setText(
                    f"Dükanyň müşderä bergisi: {money_str(store_debt)} {sale.currency}"
                )
                self.debt_label.setStyleSheet(
                    f"font-size: 15pt; font-weight: 700; color: {theme.RED if store_debt > 0 else theme.GREEN};"
                )
                c_date = sale.cancelled_at.strftime("%d.%m.%Y %H:%M") if sale.cancelled_at else "—"
                self.cancel_info_label.setText(
                    f"Ýatyrylan senesi: {c_date}   |   Sebäbi: {sale.cancellation_reason or '—'}"
                )
                self.pay_debt_section.hide()
                self.cancel_sale_btn.hide()
                self.settle_store_debt_section.setVisible(store_debt > Decimal("0.00"))
            else:
                self.status_label.setText(
                    "Status: Doly tölendi"
                    if customer_debt == Decimal("0.00")
                    else f"Status: Bölekleýin töleg / Bergä (tölendi: {money_str(paid_amt)} {sale.currency})"
                )
                self.status_label.setStyleSheet(
                    f"font-weight: 700; color: {theme.GREEN if customer_debt == 0 else theme.ACCENT}; "
                    "background: #EAF7EF; padding: 8px 12px; border-radius: 8px;"
                )
                self.debt_label.setText(
                    f"Müşderiniň galan bergisi: {money_str(customer_debt)} {sale.currency}"
                )
                self.debt_label.setStyleSheet(
                    f"font-size: 15pt; font-weight: 700; color: {theme.ACCENT if customer_debt > 0 else theme.GREEN};"
                )
                self.cancel_info_label.clear()
                self.pay_debt_section.setVisible(customer_debt > Decimal("0.00"))
                self.settle_store_debt_section.hide()
                self.cancel_sale_btn.show()

    def _add_customer_payment(self) -> None:
        amt = Decimal(f"{self.pay_amt_spin.value():.2f}")
        if amt <= 0:
            QMessageBox.warning(self, "Ýalňyşlyk", "Noldan uly töleg mukdaryny giriziň.")
            return
        try:
            with SessionLocal() as session:
                SalesService.add_sale_payment(
                    session=session,
                    sale_id=self.sale_id,
                    currency=self.pay_curr_combo.currentText(),
                    amount=amt,
                    exchange_rate=Decimal(f"{self.pay_rate_spin.value():.4f}"),
                )
                session.commit()
            self.pay_amt_spin.setValue(0)
            self._load_data()
            show_toast(self, "Töleg üstünlikli kabul edildi.", kind="success")
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))

    def _settle_store_debt(self) -> None:
        amt = Decimal(f"{self.settle_amt_spin.value():.2f}")
        if amt <= 0:
            QMessageBox.warning(self, "Ýalňyşlyk", "Noldan uly töleg mukdaryny giriziň.")
            return
        try:
            with SessionLocal() as session:
                SalesService.settle_store_debt_to_customer(
                    session=session,
                    sale_id=self.sale_id,
                    currency=self.settle_curr_combo.currentText(),
                    amount=amt,
                    exchange_rate=Decimal(f"{self.settle_rate_spin.value():.4f}"),
                )
                session.commit()
            self.settle_amt_spin.setValue(0)
            self._load_data()
            show_toast(self, "Müşderä bergi tölegi hasaba alyndy.", kind="success")
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))

    def _cancel_sale(self) -> None:
        reason, ok = QInputDialog.getText(self, "Çeki ýatyrmak", "Ýatyrmagyň sebäbini görkeziň:")
        if not ok or not reason.strip():
            return
        confirm = QMessageBox.question(
            self,
            "Ýatyrmagy tassyklamak",
            "Satyş çekini ýatyrmalymy?\n\n"
            "Harytlar sklada gaýdyp geler. Tölenmedik bergi nollanar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            with SessionLocal() as session:
                SalesService.cancel_sale(session, self.sale_id, reason)
                session.commit()
            self._load_data()
            show_toast(self, "Satyş üstünlikli ýatyryldy.", kind="success")
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))


class SalesPage(QWidget):
    """Скоростная страница «Продажи и Касса» — продажа в 1 ввод цены торга с автооплатой и расчётом прибыли."""

    COL_ID = 0
    COL_NAME = 1
    COL_IMEI = 2
    COL_QTY = 3
    COL_COST = 4
    COL_PRICE = 5
    COL_SUM_PROFIT = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.cart_items: list[dict] = []
        self.register_map: dict[str, int] = {}
        self.auto_full_payment: bool = True
        self._updating_table: bool = False
        self.last_created_sale_id: int | None = None
        self._window_filter_installed: bool = False

        self._build_ui()
        self._setup_shortcuts()
        self.refresh_data()

    def hideEvent(self, event) -> None:
        self._hide_live_search_popup()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._window_filter_installed:
            win = self.window()
            if win is not None and win is not self:
                win.installEventFilter(self)
                self._window_filter_installed = True

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "search_input", None):
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(140, self._check_hide_live_search_popup)
            elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._hide_live_search_popup()
        elif obj is self.window() and event.type() in (
            QEvent.Type.WindowDeactivate,
            QEvent.Type.Move,
            QEvent.Type.Resize,
        ):
            self._hide_live_search_popup()
        return super().eventFilter(obj, event)

    def _check_hide_live_search_popup(self) -> None:
        if not hasattr(self, "live_search_popup") or not self.live_search_popup.isVisible():
            return
        fw = QApplication.focusWidget()
        if (
            fw is self.search_input
            or fw is self.live_search_popup
            or (fw is not None and self.live_search_popup.isAncestorOf(fw))
        ):
            return
        if not self.isVisible() or not self.search_input.hasFocus():
            self._hide_live_search_popup()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("F2"), self, activated=lambda: self._open_inventory_selector(""))
        QShortcut(QKeySequence("F3"), self, activated=self._focus_search)
        QShortcut(QKeySequence("F4"), self, activated=self._edit_selected_price)
        QShortcut(QKeySequence("F6"), self, activated=self._hold_current_cart)
        QShortcut(QKeySequence("F8"), self, activated=self._open_held_carts_dialog)
        QShortcut(QKeySequence("F9"), self, activated=self._process_checkout)
        QShortcut(QKeySequence("Delete"), self, activated=self._remove_cart_item)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self._hold_current_cart)
        QShortcut(QKeySequence("Escape"), self, activated=self._hide_live_search_popup)

    def _focus_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(12)

        top_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Satyş we kassa")
        title.setObjectName("pageTitle")
        sub = QLabel(
            "Haryt saýlaň → tablisada satyş bahasyny giriziň → «Satyşy geçir (F9)» basyň"
        )
        sub.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        top_layout.addLayout(title_col, 1)

        self.hold_btn = make_button("⏸ Çeki goý")
        self.hold_btn.clicked.connect(self._hold_current_cart)
        top_layout.addWidget(self.hold_btn)

        self.held_list_btn = make_button("📂 Garaşýanlar (0)")
        self.held_list_btn.clicked.connect(self._open_held_carts_dialog)
        top_layout.addWidget(self.held_list_btn)

        self.balances_label = QLabel("Ýüklenýär...")
        self.balances_label.setObjectName("datePill")
        self.balances_label.setStyleSheet(f"font-weight: 700; color: {theme.NAVY};")
        top_layout.addWidget(self.balances_label)
        root.addLayout(top_layout)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_pos_tab(), "Täze satyş")
        self.tabs.addTab(self._create_history_tab(), "Çekler taryhy")
        self.tabs.currentChanged.connect(lambda _idx: self._hide_live_search_popup())
        root.addWidget(self.tabs, 1)

    def _create_pos_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        # Çep tarap: gözleg, çalt harytlar, tablisa
        left = QVBoxLayout()
        left.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Harydyň ady, kategoriýa, brend, model, referens, ştrihkod ýa-da IMEI (F3)..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self._add_product_by_search)
        self.search_input.textChanged.connect(self._schedule_live_search)
        self.search_input.installEventFilter(self)

        self._live_search_timer = QTimer(self)
        self._live_search_timer.setSingleShot(True)
        self._live_search_timer.timeout.connect(self._run_live_search)

        self.live_search_popup = QListWidget(self)
        self.live_search_popup.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.live_search_popup.setStyleSheet(
            f"QListWidget {{ background: white; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px; }}"
            "QListWidget::item { padding: 6px 10px; border-radius: 6px; }"
            f"QListWidget::item:hover, QListWidget::item:selected {{ background: #EFF6FF; color: {theme.NAVY}; }}"
        )
        self.live_search_popup.itemClicked.connect(self._on_live_search_item_clicked)
        self.live_search_popup.hide()

        search_btn = make_button("Skladdan tap / Saýla (F2)…", "primary")
        search_btn.setMinimumHeight(40)
        search_btn.clicked.connect(self._add_product_by_search)

        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_btn)
        left.addLayout(search_row)

        # Çalt harytlar paneli
        self.quick_products_bar = QHBoxLayout()
        self.quick_products_bar.setSpacing(6)
        left.addLayout(self.quick_products_bar)

        self.cart_table = QTableWidget(0, 7)
        self.cart_table.setHorizontalHeaderLabels([
            "ID",
            "Haryt",
            "IMEI",
            "Sany ✎",
            "Öz bahasy ✎",
            "Satyş bahasy ✎",
            "Jemi (Peýda)",
        ])
        configure_table(self.cart_table, stretch_col=1, row_height=46)
        self.cart_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        self.cart_table.itemChanged.connect(self._on_cart_item_changed)
        left.addWidget(self.cart_table, 1)

        cart_actions = QHBoxLayout()
        cart_actions.setSpacing(8)

        price_btn = make_button("✎ Satyş bahasyny giriz (F4)", "primary")
        price_btn.clicked.connect(self._edit_selected_price)
        cart_actions.addWidget(price_btn)

        clear_btn = make_button("Çeki arassala")
        clear_btn.clicked.connect(self._clear_cart)
        cart_actions.addWidget(clear_btn)

        cart_actions.addStretch()

        remove_btn = make_button("Saýlanan setiri poz (Del)", "danger")
        remove_btn.clicked.connect(self._remove_cart_item)
        cart_actions.addWidget(remove_btn)
        left.addLayout(cart_actions)

        layout.addLayout(left, 3)

        # Sag tarap: jemi, arassa peýda we töleg usuly
        right = Card(margins=(18, 16, 18, 16), spacing=10)
        rl = right.body

        title = QLabel("Satyş jemi we resmileşdiriş")
        title.setObjectName("cardTitle")
        rl.addWidget(title)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Çekiň walýutasy:"), 0, 0)
        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["TMT", "USD"])
        self.currency_combo.setCurrentText(SettingsService.get("default_currency", "TMT"))
        self.currency_combo.currentTextChanged.connect(self._on_currency_changed)
        grid.addWidget(self.currency_combo, 0, 1)

        grid.addWidget(QLabel("Kurs (1 USD = X TMT):"), 1, 0)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.setDecimals(4)
        self.rate_spin.valueChanged.connect(self._on_rate_changed)
        grid.addWidget(self.rate_spin, 1, 1)

        grid.addWidget(QLabel("JEMI (SATYŞ BAHASY):"), 2, 0)
        self.total_label = QLabel("0.00")
        self.total_label.setStyleSheet(
            f"font-size: 16.5pt; font-weight: 800; color: {theme.ACCENT};"
        )
        grid.addWidget(self.total_label, 2, 1)

        grid.addWidget(QLabel("Arassa peýda:"), 3, 0)
        self.profit_label = QLabel("+0.00")
        self.profit_label.setStyleSheet(
            f"font-size: 12.5pt; font-weight: 700; color: {theme.GREEN};"
        )
        grid.addWidget(self.profit_label, 3, 1)
        rl.addLayout(grid)

        mode_label = QLabel("Töleg usuly:")
        mode_label.setStyleSheet("font-weight: 600;")
        rl.addWidget(mode_label)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self.mode_group = QButtonGroup(self)

        self.full_pay_mode_btn = QPushButton("✔ Nagt (doly töleg)")
        self.full_pay_mode_btn.setObjectName("chip")
        self.full_pay_mode_btn.setCheckable(True)
        self.full_pay_mode_btn.setAutoDefault(False)
        self.full_pay_mode_btn.setChecked(True)
        self.full_pay_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full_pay_mode_btn.clicked.connect(lambda: self._set_payment_mode(True))

        self.simurg_mode_btn = QPushButton("🏦 Simurg (+5 gün)")
        self.simurg_mode_btn.setObjectName("chip")
        self.simurg_mode_btn.setCheckable(True)
        self.simurg_mode_btn.setAutoDefault(False)
        self.simurg_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.simurg_mode_btn.clicked.connect(lambda: self._set_payment_mode(False))

        self.mode_group.addButton(self.full_pay_mode_btn)
        self.mode_group.addButton(self.simurg_mode_btn)
        mode_row.addWidget(self.full_pay_mode_btn, 1)
        mode_row.addWidget(self.simurg_mode_btn, 1)
        rl.addLayout(mode_row)

        self.auto_pay_banner = QLabel(
            "✔ Nagt satyş: doly jemi şol wagtda kassa geçýär."
        )
        self.auto_pay_banner.setWordWrap(True)
        self.auto_pay_banner.setStyleSheet(
            f"padding: 8px 10px; border-radius: 8px; background: #EAF7EF; color: {theme.GREEN}; font-weight: 600; font-size: 9pt;"
        )
        rl.addWidget(self.auto_pay_banner)

        self.simurg_box = QWidget()
        sb_layout = QVBoxLayout(self.simurg_box)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(8)

        self.simurg_banner = QLabel(
            "🏦 Simurg garaşaryna: kassaga 0 geçýär, doly jemi (peýda bilen) "
            "Simurg bergisine ýazylýar we 5 günden soň almaga taýýar bolýar."
        )
        self.simurg_banner.setWordWrap(True)
        self.simurg_banner.setStyleSheet(
            "padding: 8px 10px; border-radius: 8px; background: #FFF8F1; "
            "border: 1px solid #FDBA74; color: #9A3412; font-weight: 600; font-size: 9pt;"
        )
        sb_layout.addWidget(self.simurg_banner)

        payout_row = QHBoxLayout()
        payout_row.addWidget(QLabel("Aljak güni (+5 gün):"))
        self.simurg_payout_date = QDateEdit(QDate.currentDate().addDays(5))
        self.simurg_payout_date.setCalendarPopup(True)
        self.simurg_payout_date.setDisplayFormat("dd.MM.yyyy")
        self.simurg_payout_date.setMinimumHeight(36)
        self.simurg_payout_date.dateChanged.connect(self._recalculate_totals)
        payout_row.addWidget(self.simurg_payout_date, 1)
        sb_layout.addLayout(payout_row)

        self.simurg_box.hide()
        rl.addWidget(self.simurg_box)

        self.customer_name_input = QLineEdit()
        self.customer_name_input.setPlaceholderText("Müşderiniň ady / Simurg arza (hökmany däl)...")
        rl.addWidget(self.customer_name_input)

        self.customer_phone_input = QLineEdit()
        self.customer_phone_input.setPlaceholderText("Müşderiniň telefony (hökmany däl)...")
        rl.addWidget(self.customer_phone_input)

        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Çeke bellik / arza № (hökmany däl)...")
        rl.addWidget(self.comment_input)

        rl.addStretch()

        self.checkout_btn = make_button("SATYŞY GEÇIR (F9)", "primary")
        self.checkout_btn.setMinimumHeight(48)
        self.checkout_btn.clicked.connect(self._process_checkout)
        rl.addWidget(self.checkout_btn)

        self.print_last_btn = make_button("🖨 Soňky çeki çap et / PDF")
        self.print_last_btn.setEnabled(False)
        self.print_last_btn.clicked.connect(self._print_last_receipt)
        rl.addWidget(self.print_last_btn)

        layout.addWidget(right, 2)
        return widget

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Çek belgisi, müşderi ýa-da bellik boýunça gözleg...")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.setMinimumHeight(38)
        self.history_search.textChanged.connect(self._filter_history)
        header.addWidget(self.history_search, 1)

        print_btn = make_button("🖨 Çap et / PDF çek")
        print_btn.clicked.connect(self._print_selected_history_sale)
        header.addWidget(print_btn)

        open_btn = make_button("Çeki aç / Bergi tölegi", "primary")
        open_btn.clicked.connect(self._open_selected_sale_button)
        header.addWidget(open_btn)

        refresh_btn = make_button("↻ Täzele")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)

        cancel_btn = make_button("Saýlanan çeki ýatyr", "danger")
        cancel_btn.clicked.connect(self._cancel_selected_sale)
        header.addWidget(cancel_btn)
        layout.addLayout(header)

        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels([
            "ID", "Çek", "Sene", "Müşderi", "Walýuta", "Jemi", "Bergi / Status", "Bellik",
        ])
        configure_table(self.history_table, stretch_col=[1, 3], row_height=44)
        self.history_table.cellDoubleClicked.connect(self._open_sale_details)
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.history_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_sale_button)
        layout.addWidget(self.history_table, 1)

        hint = QLabel("Jikme-jik görmek, PDF çap etmek ýa-da goşmaça töleg almak üçin çeki iki gezek ýa-da Enter basyň.")
        hint.setObjectName("mutedText")
        layout.addWidget(hint)
        return widget

    def _set_payment_mode(self, auto_full: bool) -> None:
        self.auto_full_payment = auto_full
        self.full_pay_mode_btn.setChecked(auto_full)
        self.simurg_mode_btn.setChecked(not auto_full)
        self.auto_pay_banner.setVisible(auto_full)
        self.simurg_box.setVisible(not auto_full)
        if not auto_full:
            self.simurg_payout_date.setDate(QDate.currentDate().addDays(5))
            self.checkout_btn.setText("🏦 SIMURG SATYŞY GEÇIR (F9)")
        else:
            self.checkout_btn.setText("SATYŞY GEÇIR (F9)")
        self._recalculate_totals()

    def _update_held_button_count(self) -> None:
        carts = SettingsService.get_held_carts()
        self.held_list_btn.setText(f"📂 Garaşýanlar ({len(carts)})")

    def _hold_current_cart(self) -> None:
        if not self.cart_items:
            show_toast(self, "Çeki goýmazdan öň oňa haryt goşuň.", kind="info")
            return
        carts = SettingsService.get_held_carts()
        serializable_items = [
            {
                "product_id": it["product_id"],
                "name": it["name"],
                "imei": it["imei"],
                "quantity": it["quantity"],
                "unit_price": str(it["unit_price"]),
                "unit_cost": str(it["unit_cost"]),
                "cost_currency": it["cost_currency"],
                "cost_exchange_rate": str(it["cost_exchange_rate"]),
                "currency": it["currency"],
            }
            for it in self.cart_items
        ]
        carts.insert(0, {
            "created_at": datetime.now().strftime("%d.%m %H:%M"),
            "currency": self.currency_combo.currentText(),
            "exchange_rate": f"{self.rate_spin.value():.4f}",
            "customer_name": self.customer_name_input.text().strip(),
            "customer_phone": self.customer_phone_input.text().strip(),
            "comment": self.comment_input.text().strip(),
            "items": serializable_items,
        })
        SettingsService.save_held_carts(carts)
        self._clear_cart()
        self._update_held_button_count()

    def _open_held_carts_dialog(self) -> None:
        dlg = HeldCartsDialog(self)
        if dlg.exec() and dlg.selected_cart:
            c = dlg.selected_cart
            self.currency_combo.setCurrentText(c.get("currency", "TMT"))
            try:
                self.rate_spin.setValue(float(c.get("exchange_rate", 19.5)))
            except ValueError:
                pass
            self.customer_name_input.setText(c.get("customer_name", ""))
            self.customer_phone_input.setText(c.get("customer_phone", ""))
            self.comment_input.setText(c.get("comment", ""))
            self.cart_items = [
                {
                    "product_id": it["product_id"],
                    "name": it["name"],
                    "imei": it.get("imei"),
                    "quantity": int(it.get("quantity", 1)),
                    "unit_price": Decimal(str(it.get("unit_price", "0.00"))),
                    "unit_cost": Decimal(str(it.get("unit_cost", "0.00"))),
                    "cost_currency": it.get("cost_currency", "USD"),
                    "cost_exchange_rate": Decimal(str(it.get("cost_exchange_rate", "19.5000"))),
                    "currency": c.get("currency", "TMT"),
                }
                for it in c.get("items", [])
            ]
            self._update_cart_table()
        self._update_held_button_count()

    def _rebuild_quick_products_bar(self) -> None:
        while self.quick_products_bar.count():
            item = self.quick_products_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        with SessionLocal() as session:
            # Топ-5 доступных количественных товаров (аксессуаров/частых позиций)
            top_rows = session.execute(
                select(Product, func.coalesce(func.sum(SaleItem.quantity), 0).label("sold_cnt"))
                .outerjoin(SaleItem, SaleItem.product_id == Product.id)
                .where(Product.is_active.is_(True), Product.stock_quantity > 0)
                .group_by(Product.id)
                .order_by(func.coalesce(func.sum(SaleItem.quantity), 0).desc(), Product.name.asc())
                .limit(5)
            ).all()

        if not top_rows:
            return

        lbl = QLabel("Çalt:")
        lbl.setObjectName("mutedText")
        self.quick_products_bar.addWidget(lbl)

        for prod, _cnt in top_rows:
            btn = QPushButton(f"+ {prod.name} ({prod.stock_quantity})")
            btn.setObjectName("chip")
            btn.setAutoDefault(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, pid=prod.id: self._quick_add_product_id(pid))
            self.quick_products_bar.addWidget(btn)
        self.quick_products_bar.addStretch()

    def _quick_add_product_id(self, product_id: int) -> None:
        with SessionLocal() as session:
            prod = session.get(Product, product_id)
            if not prod or prod.stock_quantity <= 0:
                return
            in_stock_imeis = session.scalars(
                select(StockItem).where(
                    StockItem.product_id == prod.id,
                    StockItem.status == "in_stock",
                )
            ).all()
            if len(in_stock_imeis) == 1 and prod.stock_quantity == 1:
                self._append_to_cart(prod, in_stock_imeis[0].imei1)
            elif len(in_stock_imeis) > 0:
                self._open_inventory_selector(prod.name)
            else:
                self._append_to_cart(prod)

    def refresh_data(self) -> None:
        self._update_held_button_count()
        self._rebuild_quick_products_bar()
        self._all_sales_rows: list[dict] = []
        with SessionLocal() as session:
            registers_by_curr = SalesService.ensure_default_registers(session)
            session.commit()
            self.register_map = {cur: reg.id for cur, reg in registers_by_curr.items()}
            usd = registers_by_curr["USD"].balance if "USD" in registers_by_curr else Decimal("0.00")
            tmt = registers_by_curr["TMT"].balance if "TMT" in registers_by_curr else Decimal("0.00")
            self.balances_label.setText(f"Kassalar: USD ${usd:,.2f}  |  TMT {tmt:,.2f} m.")

            sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc()).limit(200)).all()
            for s in sales:
                date_str = s.sale_date.strftime("%d.%m.%Y %H:%M") if s.sale_date else "—"
                if s.status == "cancelled":
                    store_debt = SalesService.get_store_debt_to_customer(session, s)
                    status_text = (
                        f"Ýatyryldy (dükanyň bergisi: {money_str(store_debt)})"
                        if store_debt > 0
                        else "Ýatyryldy"
                    )
                    status_color = theme.RED
                else:
                    cust_debt = SalesService.get_customer_debt(session, s)
                    if cust_debt > 0:
                        prefix = "🏦 Simurg" if getattr(s, "is_simurg", False) else "Bergi"
                        status_text = f"{prefix}: {money_str(cust_debt)}"
                        status_color = theme.ACCENT
                    else:
                        status_text = "🏦 Simurg (tölendi)" if getattr(s, "is_simurg", False) else "Tölendi"
                        status_color = theme.GREEN

                self._all_sales_rows.append({
                    "id": s.id,
                    "receipt": s.receipt_number,
                    "date": date_str,
                    "customer": s.customer_name or "—",
                    "currency": s.currency,
                    "total": money_str(s.total_amount),
                    "status_text": status_text,
                    "status_color": status_color,
                    "info": s.comment or s.cancellation_reason or "",
                })

        self._filter_history()

    def _filter_history(self, *_args) -> None:
        q = self.history_search.text().strip().lower() if hasattr(self, "history_search") else ""
        rows = [
            r
            for r in getattr(self, "_all_sales_rows", [])
            if not q or q in f"{r['receipt']} {r['customer']} {r['info']}".lower()
        ]
        self.history_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [
                str(r["id"]),
                r["receipt"],
                r["date"],
                r["customer"],
                r["currency"],
                r["total"],
                r["status_text"],
                r["info"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 6:
                    cell.setForeground(QColor(r["status_color"]))
                self.history_table.setItem(i, c, cell)

    def _open_inventory_selector(self, initial_query: str = "") -> None:
        dlg = InventorySelectorDialog(
            title="Çeke skladdan haryt ýa-da enjam saýlamak",
            initial_query=initial_query,
            parent=self,
        )
        if dlg.exec() and dlg.selected_item:
            sel = dlg.selected_item
            with SessionLocal() as session:
                product = session.get(Product, sel["product_id"])
                if product:
                    self._append_to_cart(product, sel["imei"])
            self.search_input.clear()

    def _hide_live_search_popup(self) -> None:
        if hasattr(self, "_live_search_timer") and self._live_search_timer is not None:
            self._live_search_timer.stop()
        if hasattr(self, "live_search_popup") and self.live_search_popup is not None:
            self.live_search_popup.hide()

    def _schedule_live_search(self, text: str) -> None:
        if len(text.strip()) < 2:
            self._hide_live_search_popup()
            return
        self._live_search_timer.start(160)

    @staticmethod
    def _translate_ru_to_en(text: str) -> str:
        ru_layout = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
        en_layout = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
        ru_layout_up = "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
        en_layout_up = "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~"
        trans_map = {ord(r): ord(e) for r, e in zip(ru_layout, en_layout)}
        trans_map.update({ord(r): ord(e) for r, e in zip(ru_layout_up, en_layout_up)})
        return text.translate(trans_map)

    @staticmethod
    def _matches_multiword(hay: str, words: list[str], words_en: list[str]) -> bool:
        return all(w in hay or w_en in hay for w, w_en in zip(words, words_en))

    def _run_live_search(self) -> None:
        if not self.isVisible() or self.tabs.currentIndex() != 0 or not self.search_input.hasFocus():
            self._hide_live_search_popup()
            return
        text = self.search_input.text().strip()
        if len(text) < 2:
            self._hide_live_search_popup()
            return

        text_en = self._translate_ru_to_en(text)
        words = [w for w in text.lower().split() if w]
        words_en = [w for w in text_en.lower().split() if w]
        if not words:
            self._hide_live_search_popup()
            return

        fallback_curr = self.currency_combo.currentText()
        fallback_rate = Decimal(f"{self.rate_spin.value():.4f}")

        self.live_search_popup.clear()
        with SessionLocal() as session:
            imei_rows = session.execute(
                select(StockItem, Product, Category.name)
                .join(Product, StockItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(
                    StockItem.status == "in_stock",
                    Product.is_active.is_(True),
                    Product.stock_quantity > 0,
                )
                .order_by(StockItem.id.desc())
            ).all()

            latest_stock_by_prod: dict[int, StockItem] = {}
            for st, _prod, _cat in imei_rows:
                if st.product_id not in latest_stock_by_prod and st.unit_cost is not None:
                    latest_stock_by_prod[st.product_id] = st

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
                        ],
                    )
                ).lower()
                if not self._matches_multiword(hay, words, words_en):
                    continue
                cat_label = cat_name or "—"
                bm = " / ".join(filter(None, [prod.brand, prod.model])) or "—"
                cond = "Täze" if st.condition == "new" else "B/U"
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=prod.id,
                    stock_item=st,
                    fallback_currency=fallback_curr,
                    fallback_rate=fallback_rate,
                )
                cost_str = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"
                item = QListWidgetItem(
                    f"📱 {prod.name}  •  {cat_label}  •  {bm}  •  IMEI: {st.imei1} ({cond})  •  Öz bahasy: {cost_str}"
                )
                item.setData(Qt.ItemDataRole.UserRole, {"product_id": prod.id, "imei": st.imei1})
                self.live_search_popup.addItem(item)
                imei_added += 1
                if imei_added >= 6:
                    break

            prod_rows = session.execute(
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(
                    Product.is_active.is_(True),
                    Product.stock_quantity > 0,
                )
                .order_by(Product.name.asc())
            ).all()
            prod_added = 0
            for p, cat_name in prod_rows:
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
                if not self._matches_multiword(hay, words, words_en):
                    continue
                cat_label = cat_name or "—"
                bm = " / ".join(filter(None, [p.brand, p.model])) or "—"
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=p.id,
                    stock_item=latest_stock_by_prod.get(p.id),
                    fallback_currency=fallback_curr,
                    fallback_rate=fallback_rate,
                )
                cost_str = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"
                item = QListWidgetItem(
                    f"📦 {p.name}  •  {cat_label}  •  {bm}  •  Öz bahasy: {cost_str}  •  Bar: {p.stock_quantity}"
                )
                item.setData(Qt.ItemDataRole.UserRole, {"product_id": p.id, "imei": None})
                self.live_search_popup.addItem(item)
                prod_added += 1
                if prod_added >= 8:
                    break

        if self.live_search_popup.count() == 0:
            self._hide_live_search_popup()
            return

        pos = self.search_input.mapToGlobal(QPoint(0, self.search_input.height() + 2))
        self.live_search_popup.move(pos)
        self.live_search_popup.setFixedWidth(max(580, self.search_input.width()))
        h = min(300, self.live_search_popup.count() * 34 + 12)
        self.live_search_popup.setFixedHeight(h)
        self.live_search_popup.show()

    def _on_live_search_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        self._hide_live_search_popup()
        pid = data.get("product_id")
        imei = data.get("imei")
        if pid is None:
            return
        with SessionLocal() as session:
            prod = session.get(Product, int(pid))
            if not prod or not prod.is_active or prod.stock_quantity <= 0:
                return
            if imei:
                self._append_to_cart(prod, imei)
                self.search_input.clear()
                return
            in_stock_imeis = session.scalars(
                select(StockItem).where(
                    StockItem.product_id == prod.id,
                    StockItem.status == "in_stock",
                )
            ).all()
            if len(in_stock_imeis) == 0:
                self._append_to_cart(prod)
                self.search_input.clear()
            elif len(in_stock_imeis) == 1 and prod.stock_quantity == 1:
                self._append_to_cart(prod, in_stock_imeis[0].imei1)
                self.search_input.clear()
            else:
                self._open_inventory_selector(prod.name)

    def _add_product_by_search(self) -> None:
        self._hide_live_search_popup()
        text = self.search_input.text().strip()
        if not text:
            self._open_inventory_selector("")
            return

        text_en = self._translate_ru_to_en(text)
        words = [w for w in text.lower().split() if w]
        words_en = [w for w in text_en.lower().split() if w]

        with SessionLocal() as session:
            # 1. Точный или частичный поиск по IMEI (включая последние 4+ цифр)
            exact_imei = session.scalar(
                select(StockItem).where(
                    (StockItem.imei1 == text)
                    | (StockItem.imei1 == text_en)
                    | (StockItem.imei2 == text)
                    | (StockItem.imei2 == text_en)
                )
            )
            if exact_imei:
                if exact_imei.status != "in_stock":
                    QMessageBox.warning(self, "Elýeterli däl", "Bu IMEI-li enjam eýýäm satyldy.")
                    return
                product = session.get(Product, exact_imei.product_id)
                if not product or not product.is_active or product.stock_quantity <= 0:
                    QMessageBox.warning(self, "Elýeterli däl", "Bu IMEI üçin haryt elýeterli däl.")
                    return
                self._append_to_cart(product, exact_imei.imei1)
                self.search_input.clear()
                return

            # Частичный IMEI (если ввели >= 4 цифр)
            if len(text) >= 4 and text.isdigit():
                partial_imeis = session.scalars(
                    select(StockItem).where(
                        StockItem.status == "in_stock",
                        (StockItem.imei1.ilike(f"%{text}%")) | (StockItem.imei2.ilike(f"%{text}%")),
                    )
                ).all()
                if len(partial_imeis) == 1:
                    st = partial_imeis[0]
                    product = session.get(Product, st.product_id)
                    if product and product.is_active and product.stock_quantity > 0:
                        self._append_to_cart(product, st.imei1)
                        self.search_input.clear()
                        return

            # 2. Точный поиск по штрихкоду (Barcode)
            exact_barcode = session.scalar(
                select(Product).where(
                    Product.is_active.is_(True),
                    Product.stock_quantity > 0,
                    (func.lower(Product.barcode) == text.lower())
                    | (func.lower(Product.barcode) == text_en.lower()),
                )
            )
            if exact_barcode is not None:
                self._append_to_cart(exact_barcode)
                self.search_input.clear()
                return

            # 3. Многословный поиск по названию, категории, бренду, модели, референсу и штрихкоду (без SKU)
            prod_rows = session.execute(
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(
                    Product.is_active.is_(True),
                    Product.stock_quantity > 0,
                )
                .order_by(Product.name.asc())
            ).all()
            matches = [
                p
                for p, cat_name in prod_rows
                if self._matches_multiword(
                    " ".join(
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
                    ).lower(),
                    words,
                    words_en,
                )
            ]

            if len(matches) == 1:
                prod = matches[0]
                in_stock_imeis = session.scalars(
                    select(StockItem).where(
                        StockItem.product_id == prod.id,
                        StockItem.status == "in_stock",
                    )
                ).all()
                if len(in_stock_imeis) == 1 and prod.stock_quantity == 1:
                    self._append_to_cart(prod, in_stock_imeis[0].imei1)
                    self.search_input.clear()
                    return
                if len(in_stock_imeis) == 0:
                    self._append_to_cart(prod)
                    self.search_input.clear()
                    return

        self._open_inventory_selector(text)

    def _get_cart_product_quantity(self, product_id: int, exclude_row: int | None = None) -> int:
        total_qty = 0
        for idx, it in enumerate(self.cart_items):
            if exclude_row is not None and idx == exclude_row:
                continue
            if it["product_id"] == product_id:
                total_qty += int(it["quantity"])
        return total_qty

    def has_imei_in_cart(self, imei: str) -> bool:
        clean = (imei or "").strip()
        if not clean:
            return False
        return any((it.get("imei") or "").strip() == clean for it in self.cart_items)

    def add_item_from_mobile(self, item_data: dict) -> tuple[bool, str, dict | None]:
        """Добавляет подтверждённый на Android-сканере товар с выторгованной ценой в текущий черновик чека."""
        product_id = int(item_data["product_id"])
        imei = (str(item_data.get("imei")).strip() or None) if item_data.get("imei") else None
        qty = 1 if imei else max(1, int(item_data.get("quantity", 1)))
        raw_price = Decimal(str(item_data["unit_price"])).quantize(Decimal("0.01"))
        item_curr = str(item_data.get("currency") or self.currency_combo.currentText()).strip().upper()

        if imei and self.has_imei_in_cart(imei):
            return False, f"IMEI {imei} enjam eýýäm häzirki satyşa goşuldy.", None

        with SessionLocal() as session:
            product = session.get(Product, product_id)
            if product is None or not product.is_active:
                return False, "Haryt tapylmady ýa-da öçürilen.", None

            current_in_cart = self._get_cart_product_quantity(product.id)
            if current_in_cart + qty > product.stock_quantity:
                return (
                    False,
                    f"Skladda «{product.name}» harydy ýeterlik däl (bar: {product.stock_quantity}, çekde: {current_in_cart}).",
                    None,
                )

            st_item = None
            if imei:
                st_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == product.id,
                        (StockItem.imei1 == imei) | (StockItem.imei2 == imei),
                    )
                )
                if st_item is None:
                    return False, f"IMEI {imei} enjam skladda tapylmady.", None
                if st_item.status != "in_stock":
                    return False, f"IMEI {imei} enjam eýýäm satyldy.", None

            # Если корзина пуста, подстраиваем валюту чека под выбранную на смартфоне
            if not self.cart_items and item_curr in ("USD", "TMT"):
                self.currency_combo.blockSignals(True)
                self.currency_combo.setCurrentText(item_curr)
                self.currency_combo.blockSignals(False)

            receipt_curr = self.currency_combo.currentText()
            rate = Decimal(f"{self.rate_spin.value():.4f}")
            unit_price_doc = _convert_currency(raw_price, item_curr, receipt_curr, rate)

            unit_cost, cost_curr, cost_rate = SalesService._resolve_item_cost_basis(
                session=session,
                product_id=product.id,
                stock_item=st_item,
                fallback_currency=receipt_curr,
                fallback_rate=rate,
            )

        self.tabs.setCurrentIndex(0)
        self.cart_items.append({
            "product_id": product.id,
            "name": product.name,
            "imei": imei,
            "quantity": qty,
            "unit_price": unit_price_doc,
            "unit_cost": unit_cost,
            "cost_currency": cost_curr,
            "cost_exchange_rate": cost_rate,
            "currency": receipt_curr,
        })
        self._update_cart_table()
        self.cart_table.selectRow(len(self.cart_items) - 1)

        cart_total = sum(
            (int(it["quantity"]) * Decimal(str(it["unit_price"])) for it in self.cart_items),
            Decimal("0.00"),
        )
        msg = f"«{product.name}» harydy häzirki satyşa goşuldy ({money_str(unit_price_doc)} {receipt_curr})"
        return True, msg, {
            "cart_items_count": len(self.cart_items),
            "cart_total": f"{cart_total:.2f}",
            "currency": receipt_curr,
        }

    def _append_to_cart(self, product: Product, imei: str | None = None) -> None:
        if imei:
            for it in self.cart_items:
                if it.get("imei") == imei:
                    QMessageBox.warning(self, "Eýýäm çekde", f"IMEI {imei} enjam eýýäm çeke goşuldy.")
                    return

        current_in_cart = self._get_cart_product_quantity(product.id)
        if current_in_cart + 1 > product.stock_quantity:
            QMessageBox.warning(
                self,
                "Skladda ýeterlik däl",
                f"Skladda «{product.name}» harydy ýeterlik däl (elýeterli: {product.stock_quantity}).",
            )
            return

        if not imei:
            for idx, it in enumerate(self.cart_items):
                if it["product_id"] == product.id and not it["imei"]:
                    it["quantity"] += 1
                    self._update_cart_table()
                    self._focus_price_cell(idx)
                    return

        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")

        with SessionLocal() as session:
            st_item = None
            if imei:
                st_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == product.id,
                        (StockItem.imei1 == imei) | (StockItem.imei2 == imei),
                    )
                )
            unit_cost, cost_curr, cost_rate = SalesService._resolve_item_cost_basis(
                session=session,
                product_id=product.id,
                stock_item=st_item,
                fallback_currency=cur,
                fallback_rate=rate,
            )

        self.cart_items.append({
            "product_id": product.id,
            "name": product.name,
            "imei": imei,
            "quantity": 1,
            "unit_price": Decimal("0.00"),
            "unit_cost": unit_cost,
            "cost_currency": cost_curr,
            "cost_exchange_rate": cost_rate,
            "currency": cur,
        })
        self._update_cart_table()
        self._focus_price_cell(len(self.cart_items) - 1)

    def _focus_price_cell(self, row: int) -> None:
        """Сразу переводит курсор в ячейку «Цена торга» для мгновенного ввода с клавиатуры."""
        if not (0 <= row < self.cart_table.rowCount()):
            return
        self.cart_table.setCurrentCell(row, self.COL_PRICE)
        item = self.cart_table.item(row, self.COL_PRICE)
        if item is not None:
            QTimer.singleShot(10, lambda: self.cart_table.editItem(item))

    def _item_cost_in_receipt_currency(self, item: dict) -> Decimal:
        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        cost_amt = Decimal(str(item.get("unit_cost", "0.00")))
        cost_cur = item.get("cost_currency", cur)
        return _convert_currency(cost_amt, cost_cur, cur, rate)

    def _on_currency_changed(self, new_currency: str) -> None:
        for it in self.cart_items:
            it["currency"] = new_currency
        self._update_cart_table()

    def _on_rate_changed(self) -> None:
        self._update_cart_table()

    def _update_cart_table(self) -> None:
        self._updating_table = True
        self.cart_table.blockSignals(True)
        self.cart_table.setRowCount(len(self.cart_items))
        cur = self.currency_combo.currentText()

        for i, item in enumerate(self.cart_items):
            qty = int(item["quantity"])
            unit_price = Decimal(str(item["unit_price"]))
            unit_cost_doc = self._item_cost_in_receipt_currency(item)
            line_sum = unit_price * qty
            line_profit = (unit_price - unit_cost_doc) * qty
            sign = "+" if line_profit >= 0 else "−"
            sum_profit_str = f"{money_str(line_sum)} ({sign}{money_str(abs(line_profit))})"

            read_only_flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            editable_flags = read_only_flags | Qt.ItemFlag.ItemIsEditable

            c_id = QTableWidgetItem(str(item["product_id"]))
            c_id.setFlags(read_only_flags)
            c_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            c_name = QTableWidgetItem(item["name"])
            c_name.setFlags(read_only_flags)

            c_imei = QTableWidgetItem(item["imei"] or "—")
            c_imei.setFlags(read_only_flags)
            c_imei.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            c_qty = QTableWidgetItem(str(qty))
            c_qty.setFlags(read_only_flags if item["imei"] else editable_flags)
            c_qty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            c_cost = QTableWidgetItem(f"{unit_cost_doc:.2f}")
            c_cost.setFlags(editable_flags)
            c_cost.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c_cost.setToolTip(f"1 sanynyň {cur} öz bahasy (şu ýerde üýtgedip bilersiňiz)")
            c_cost.setForeground(QColor(theme.MUTED))

            c_price = QTableWidgetItem(f"{unit_price:.2f}")
            c_price.setFlags(editable_flags)
            c_price.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c_price.setBackground(QColor("#FFF8F1"))
            c_price.setForeground(QColor(theme.NAVY))
            c_price.setToolTip("Ylalaşylan satyş bahasyny giriziň we Enter basyň")

            c_sum = QTableWidgetItem(sum_profit_str)
            c_sum.setFlags(read_only_flags)
            c_sum.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c_sum.setForeground(QColor(theme.GREEN if line_profit >= 0 else theme.RED))

            self.cart_table.setItem(i, self.COL_ID, c_id)
            self.cart_table.setItem(i, self.COL_NAME, c_name)
            self.cart_table.setItem(i, self.COL_IMEI, c_imei)
            self.cart_table.setItem(i, self.COL_QTY, c_qty)
            self.cart_table.setItem(i, self.COL_COST, c_cost)
            self.cart_table.setItem(i, self.COL_PRICE, c_price)
            self.cart_table.setItem(i, self.COL_SUM_PROFIT, c_sum)

        self.cart_table.blockSignals(False)
        self._updating_table = False
        self._recalculate_totals()

    def _on_cart_item_changed(self, cell: QTableWidgetItem) -> None:
        if self._updating_table:
            return
        row = cell.row()
        col = cell.column()
        if not (0 <= row < len(self.cart_items)):
            return

        raw_text = cell.text().strip().replace(",", ".").replace(" ", "")
        item = self.cart_items[row]
        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")

        if col == self.COL_PRICE:
            try:
                val = Decimal(raw_text) if raw_text else Decimal("0.00")
                if val < 0:
                    raise ValueError
                item["unit_price"] = val.quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                QMessageBox.warning(self, "Nädogry baha", "Satyş bahasy üçin san giriziň.")
            self._update_cart_table()

        elif col == self.COL_COST:
            try:
                val = Decimal(raw_text) if raw_text else Decimal("0.00")
                if val < 0:
                    raise ValueError
                new_cost = val.quantize(Decimal("0.01"))
                item["unit_cost"] = new_cost
                item["cost_currency"] = cur
                item["cost_exchange_rate"] = rate
                SettingsService.set_product_default_cost(item["product_id"], new_cost, cur)
            except (InvalidOperation, ValueError):
                QMessageBox.warning(self, "Nädogry öz bahasy", "Öz bahasy üçin san giriziň.")
            self._update_cart_table()

        elif col == self.COL_QTY and not item["imei"]:
            try:
                new_qty = int(raw_text)
                if new_qty <= 0:
                    raise ValueError
                other_qty = self._get_cart_product_quantity(item["product_id"], exclude_row=row)
                with SessionLocal() as session:
                    prod = session.get(Product, item["product_id"])
                    max_allowed = max(1, (prod.stock_quantity if prod else 1) - other_qty)
                if new_qty > max_allowed:
                    QMessageBox.warning(
                        self,
                        "Skladda ýeterlik däl",
                        f"Skladda iň köp {max_allowed} sany elýeterli.",
                    )
                    new_qty = max_allowed
                item["quantity"] = new_qty
            except ValueError:
                QMessageBox.warning(self, "Nädogry mukdar", "Sany 0-dan uly bitin san bolmaly.")
            self._update_cart_table()

    def _edit_selected_price(self) -> None:
        row = self.cart_table.currentRow()
        if not (0 <= row < len(self.cart_items)):
            if self.cart_items:
                row = len(self.cart_items) - 1
            else:
                show_toast(self, "Ilki çeke haryt goşuň.", kind="info")
                return
        self._focus_price_cell(row)

    def _clear_cart(self) -> None:
        self.cart_items = []
        self.customer_name_input.clear()
        self.customer_phone_input.clear()
        self.comment_input.clear()
        self.simurg_payout_date.setDate(QDate.currentDate().addDays(5))
        self._update_cart_table()

    def _remove_cart_item(self) -> None:
        row = self.cart_table.currentRow()
        if 0 <= row < len(self.cart_items):
            self.cart_items.pop(row)
            self._update_cart_table()

    def _recalculate_totals(self) -> None:
        cur = self.currency_combo.currentText()

        total = Decimal("0.00")
        total_cost = Decimal("0.00")
        for it in self.cart_items:
            it["currency"] = cur
            qty = int(it["quantity"])
            total += qty * Decimal(str(it["unit_price"]))
            total_cost += qty * self._item_cost_in_receipt_currency(it)

        profit = total - total_cost
        self.total_label.setText(f"{total:,.2f} {cur}")

        p_sign = "+" if profit >= 0 else "−"
        self.profit_label.setText(f"{p_sign}{abs(profit):,.2f} {cur}")
        self.profit_label.setStyleSheet(
            f"font-size: 12.5pt; font-weight: 700; color: {theme.GREEN if profit >= 0 else theme.RED};"
        )

        if self.auto_full_payment:
            self.auto_pay_banner.setText(
                f"✔ Nagt satyş: {total:,.2f} {cur} şol wagtda kassa geçýär."
            )
        else:
            p_date = self.simurg_payout_date.date().toString("dd.MM.yyyy")
            self.simurg_banner.setText(
                f"🏦 Simurg garaşaryna: {total:,.2f} {cur} Simurg bergisine ýazylýar "
                f"(aljak güni: {p_date}, kassa: 0.00)."
            )

    def _process_checkout(self) -> None:
        if not self.cart_items:
            QMessageBox.warning(self, "Sebet boş", "Çeke iň bolmanda bir haryt goşuň.")
            return

        cur = self.currency_combo.currentText()

        # Проверка нулевой цены или цены ниже себестоимости
        for idx, it in enumerate(self.cart_items):
            u_price = Decimal(str(it["unit_price"]))
            u_cost = self._item_cost_in_receipt_currency(it)
            if u_price <= Decimal("0.00"):
                ans = QMessageBox.question(
                    self,
                    "Satyş bahasy görkezilmedik",
                    f"«{it['name']}» harydynyň satyş bahasy 0.00 {cur}.\n\n"
                    "Baha girizmek üçin «No», haryt hakykatdan mugt bolsa «Yes» basyň.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    self._focus_price_cell(idx)
                    return
            elif u_cost > Decimal("0.00") and u_price < u_cost:
                loss = (u_cost - u_price) * int(it["quantity"])
                ans = QMessageBox.question(
                    self,
                    "Baha öz bahasyndan pes",
                    f"Üns beriň! «{it['name']}» harydynyň satyş bahasy ({u_price:,.2f} {cur}) "
                    f"öz bahasyndan ({u_cost:,.2f} {cur}) pes.\n"
                    f"Bu setir boýunça zyýan: −{loss:,.2f} {cur}.\n\n"
                    "Öz bahasyndan pes satyşy tassyklamalymy?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    self._focus_price_cell(idx)
                    return

        with SessionLocal() as session:
            try:
                if "USD" not in self.register_map or "TMT" not in self.register_map:
                    regs = SalesService.ensure_default_registers(session)
                    self.register_map = {c: r.id for c, r in regs.items()}

                rate = Decimal(str(self.rate_spin.value()))
                total = Decimal("0.00")
                for it in self.cart_items:
                    it["currency"] = cur
                    total += int(it["quantity"]) * Decimal(str(it["unit_price"]))

                raw_customer = self.customer_name_input.text().strip()
                customer_phone = self.customer_phone_input.text().strip() or None
                is_simurg = not self.auto_full_payment

                if is_simurg:
                    pays = []
                    customer_name = f"Simurg — {raw_customer}" if raw_customer else "Simurg"
                    payout_dt = datetime.combine(
                        self.simurg_payout_date.date().toPython(),
                        datetime.min.time(),
                    )
                else:
                    pays = []
                    if total > Decimal("0.00"):
                        pays.append({
                            "cash_register_id": self.register_map[cur],
                            "amount": total,
                            "currency": cur,
                            "exchange_rate": rate,
                        })
                    customer_name = raw_customer or None
                    payout_dt = None

                sale = SalesService.create_sale(
                    session=session,
                    items=self.cart_items,
                    payments=pays,
                    currency=cur,
                    exchange_rate=rate,
                    comment=self.comment_input.text(),
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    allow_credit=is_simurg or total == Decimal("0.00"),
                    is_simurg=is_simurg,
                    simurg_payout_date=payout_dt,
                )
                self.last_created_sale_id = sale.id
                rec_num = sale.receipt_number
                session.commit()

                self.print_last_btn.setEnabled(True)
                self.print_last_btn.setText(f"🖨 Çeki çap et / PDF ({rec_num})")
                self._clear_cart()
                self._set_payment_mode(True)
                self.refresh_data()
                self._focus_search()
                if is_simurg:
                    show_toast(
                        self,
                        f"🏦 Simurg satyşy geçirildi ({rec_num}): {total:,.2f} {cur}",
                        kind="success",
                        duration_ms=3200,
                    )
                else:
                    show_toast(
                        self,
                        f"✔ Satyş geçirildi ({rec_num}): {total:,.2f} {cur}",
                        kind="success",
                        duration_ms=2600,
                    )
            except (ValueError, TypeError, KeyError, SQLAlchemyError) as e:
                session.rollback()
                QMessageBox.critical(self, "Ýalňyşlyk", str(e))

    def _print_last_receipt(self) -> None:
        if self.last_created_sale_id is not None:
            export_sale_receipt_pdf(self.last_created_sale_id, self)

    def _print_selected_history_sale(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            show_toast(self, "Satyş taryhy tablisasyndan çek saýlaň.", kind="info")
            return
        item = self.history_table.item(row, 0)
        if item is not None:
            export_sale_receipt_pdf(int(item.text()), self)

    def _open_selected_sale_button(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            show_toast(self, "Satyş taryhy tablisasyndan çek saýlaň.", kind="info")
            return
        self._open_sale_details(row, 0)

    def _open_sale_details(self, row: int, _col: int) -> None:
        item = self.history_table.item(row, 0)
        if item is None:
            return
        sid = int(item.text())
        dlg = SaleDetailsDialog(sid, self)
        dlg.exec()
        self.refresh_data()

    def _cancel_selected_sale(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            show_toast(self, "Ýatyrmak üçin çek saýlaň.", kind="info")
            return
        item = self.history_table.item(row, 0)
        if item is None:
            return
        sid = int(item.text())
        reason, ok = QInputDialog.getText(self, "Çeki ýatyrmak", "Ýatyrmagyň sebäbi:")
        if not ok or not reason.strip():
            return

        with SessionLocal() as session:
            try:
                SalesService.cancel_sale(session, sid, reason)
                session.commit()
                self.refresh_data()
                show_toast(self, "Satyş üstünlikli ýatyryldy.", kind="success")
            except (ValueError, TypeError, KeyError, SQLAlchemyError) as e:
                session.rollback()
                QMessageBox.critical(self, "Ýalňyşlyk", str(e))
