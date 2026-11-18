from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QComboBox,
    QDoubleSpinBox,
    QMessageBox,
    QInputDialog,
    QTabWidget,
    QHeaderView,
    QGridLayout,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.models.product import Product
from app.models.stock_item import StockItem
from app.models.cash_register import CashRegister
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.sales_service import SalesService
from app.ui import theme
from app.ui.widgets import Card


def money_str(value) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except Exception:
        return "0.00"


def configure_table(table: QTableWidget) -> None:
    table.setStyleSheet(f"""
        QTableWidget {{
            background: white;
            color: {theme.TEXT};
            border: 1px solid {theme.BORDER};
            border-radius: 12px;
            gridline-color: transparent;
            selection-background-color: {theme.ACCENT_BG};
            selection-color: {theme.TEXT};
            alternate-background-color: #FAFBFC;
            outline: none;
        }}
        QHeaderView::section {{
            background: #F8F9FB;
            color: {theme.MUTED};
            padding: 11px 10px;
            border: none;
            border-bottom: 1px solid {theme.BORDER};
            font-weight: 600;
        }}
        QTableWidget::item {{
            padding: 10px;
            border: none;
            border-bottom: 1px solid #F0F1F3;
        }}
        QTableWidget::item:selected {{
            background: {theme.ACCENT_BG};
            color: {theme.TEXT};
        }}
    """)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(46)


class SalesPage(QWidget):
    """Страница «Продажи и Касса»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cart_items = []
        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # Верхняя панель
        top_layout = QHBoxLayout()
        title = QLabel("Продажи и Касса")
        title.setObjectName("pageTitle")
        top_layout.addWidget(title)
        top_layout.addStretch()

        self.balances_label = QLabel("Загрузка...")
        self.balances_label.setStyleSheet(f"font-weight: 600; color: {theme.TEXT};")
        top_layout.addWidget(self.balances_label)
        root.addLayout(top_layout)

        # Вкладки
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_pos_tab(), "Новая продажа")
        self.tabs.addTab(self._create_history_tab(), "История чеков")
        root.addWidget(self.tabs, 1)

    def _create_pos_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Левая часть: поиск и корзина
        left = QVBoxLayout()
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по IMEI, SKU или названию...")
        self.search_input.setMinimumHeight(42)
        self.search_input.returnPressed.connect(self._add_product_by_search)
        
        search_btn = QPushButton("Найти / Добавить")
        search_btn.setObjectName("primaryBtn")
        search_btn.setMinimumHeight(42)
        search_btn.clicked.connect(self._add_product_by_search)
        
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_btn)
        left.addLayout(search_row)

        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(6)
        self.cart_table.setHorizontalHeaderLabels(["ID", "Товар", "IMEI", "Кол-во", "Цена", "Сумма"])
        configure_table(self.cart_table)
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.cart_table.cellDoubleClicked.connect(self._edit_cart_cell)
        left.addWidget(self.cart_table, 1)

        remove_btn = QPushButton("Удалить выбранную позицию")
        remove_btn.clicked.connect(self._remove_cart_item)
        left.addWidget(remove_btn)
        layout.addLayout(left, 3)

        # Правая часть: оплата
        right = Card()
        rl = QVBoxLayout(right)
        
        title = QLabel("Оформление чека")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        rl.addWidget(title)

        grid = QGridLayout()
        grid.addWidget(QLabel("Валюта чека:"), 0, 0)
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["TMT", "USD"])
        self.currency_combo.currentTextChanged.connect(self._recalculate_totals)
        grid.addWidget(self.currency_combo, 0, 1)

        grid.addWidget(QLabel("Курс TMT/USD:"), 1, 0)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 1000)
        self.rate_spin.setValue(19.5)
        self.rate_spin.setDecimals(4)
        self.rate_spin.valueChanged.connect(self._recalculate_totals)
        grid.addWidget(self.rate_spin, 1, 1)

        grid.addWidget(QLabel("ИТОГО:"), 2, 0)
        self.total_label = QLabel("0.00")
        self.total_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {theme.ACCENT};")
        grid.addWidget(self.total_label, 2, 1)
        rl.addLayout(grid)

        rl.addSpacing(10)
        rl.addWidget(QLabel("Оплата:"))
        self.pay_usd_spin = QDoubleSpinBox()
        self.pay_usd_spin.setRange(0, 1000000)
        self.pay_usd_spin.setPrefix("USD: ")
        self.pay_usd_spin.setMinimumHeight(38)
        self.pay_usd_spin.valueChanged.connect(self._recalculate_totals)
        rl.addWidget(self.pay_usd_spin)

        self.pay_tmt_spin = QDoubleSpinBox()
        self.pay_tmt_spin.setRange(0, 1000000)
        self.pay_tmt_spin.setPrefix("TMT: ")
        self.pay_tmt_spin.setMinimumHeight(38)
        self.pay_tmt_spin.valueChanged.connect(self._recalculate_totals)
        rl.addWidget(self.pay_tmt_spin)

        self.change_label = QLabel("Сдача: 0.00")
        self.change_label.setStyleSheet("font-weight: 600; color: #10B981;")
        rl.addWidget(self.change_label)

        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Комментарий к чеку...")
        rl.addWidget(self.comment_input)

        rl.addStretch()
        self.checkout_btn = QPushButton("ПОДТВЕРДИТЬ И СОХРАНИТЬ ЧЕК")
        self.checkout_btn.setObjectName("primaryBtn")
        self.checkout_btn.setMinimumHeight(50)
        self.checkout_btn.setStyleSheet(f"background: {theme.ACCENT}; color: white; font-weight: bold; font-size: 14px;")
        self.checkout_btn.clicked.connect(self._process_checkout)
        rl.addWidget(self.checkout_btn)

        layout.addWidget(right, 2)
        return widget

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        header = QHBoxLayout()
        header.addWidget(QLabel("История продаж"))
        header.addStretch()
        
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)
        
        cancel_btn = QPushButton("Отменить выбранный чек")
        cancel_btn.setStyleSheet(f"background: {theme.RED}; color: white; border-radius: 6px; padding: 6px 12px;")
        cancel_btn.clicked.connect(self._cancel_selected_sale)
        header.addWidget(cancel_btn)
        layout.addLayout(header)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels(["ID", "Чек", "Дата", "Валюта", "Сумма", "Статус", "Инфо"])
        configure_table(self.history_table)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history_table)
        
        return widget

    def refresh_data(self):
        with SessionLocal() as session:
            registers = session.scalars(select(CashRegister)).all()
            self.register_map = {r.currency: r.id for r in registers}
            usd = next((r.balance for r in registers if r.currency == "USD"), 0)
            tmt = next((r.balance for r in registers if r.currency == "TMT"), 0)
            self.balances_label.setText(f"Кассы: USD: ${usd:,.2f} | TMT: {tmt:,.2f} m.")

            sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc()).limit(50)).all()
            self.history_table.setRowCount(len(sales))
            for i, s in enumerate(sales):
                self.history_table.setItem(i, 0, QTableWidgetItem(str(s.id)))
                self.history_table.setItem(i, 1, QTableWidgetItem(s.receipt_number))
                self.history_table.setItem(i, 2, QTableWidgetItem(s.sale_date.strftime("%d.%m %H:%M")))
                self.history_table.setItem(i, 3, QTableWidgetItem(s.currency))
                self.history_table.setItem(i, 4, QTableWidgetItem(money_str(s.total_amount)))
                st = QTableWidgetItem(s.status)
                if s.status == "cancelled": st.setForeground(theme.RED)
                self.history_table.setItem(i, 5, st)
                self.history_table.setItem(i, 6, QTableWidgetItem(s.comment or s.cancellation_reason or ""))

    def _add_product_by_search(self):
        text = self.search_input.text().strip()
        if not text:
            return

        # Layout mapping (Safe version)
        ru_layout = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
        en_layout = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
        ru_layout_up = "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
        en_layout_up = "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~"
        
        # Build transliteration table
        trans_map = {}
        for r, e in zip(ru_layout, en_layout):
            trans_map[ord(r)] = ord(e)
        for r, e in zip(ru_layout_up, en_layout_up):
            trans_map[ord(r)] = ord(e)
            
        text_en = text.translate(trans_map)

        with SessionLocal() as session:
            # 1. Search by IMEI (both layouts)
            item = session.scalar(select(StockItem).where(
                (StockItem.imei1 == text) | (StockItem.imei1 == text_en) |
                (StockItem.imei2 == text) | (StockItem.imei2 == text_en)
            ))

            if item:
                if item.status != "in_stock":
                    QMessageBox.warning(self, "Ошибка", "Товар с этим IMEI уже продан или недоступен.")
                    return
                product = session.get(Product, item.product_id)
                self._append_to_cart(product, item.imei1)
            else:
                # 2. Search by SKU or Name
                product = session.scalar(select(Product).where(
                    (Product.sku.ilike(f"%{text}%")) | (Product.sku.ilike(f"%{text_en}%")) |
                    (Product.name.ilike(f"%{text}%")) | (Product.name.ilike(f"%{text_en}%"))
                ))
                if product:
                    if product.stock_quantity <= 0:
                        QMessageBox.warning(self, "Ошибка", f"Товара '{product.name}' нет в наличии.")
                        return
                    self._append_to_cart(product)
                else:
                    QMessageBox.warning(self, "Не найдено", f"Товар или IMEI '{text}' не найден.")

        self.search_input.clear()

    def _append_to_cart(self, product, imei=None):
        # Если без IMEI, проверим нет ли уже в корзине
        if not imei:
            for it in self.cart_items:
                if it["product_id"] == product.id and not it["imei"]:
                    it["quantity"] += 1
                    self._update_cart_table()
                    return

        self.cart_items.append({
            "product_id": product.id,
            "name": product.name,
            "imei": imei,
            "quantity": 1,
            "unit_price": Decimal("0.00"),
            "currency": self.currency_combo.currentText()
        })
        self._update_cart_table()

    def _update_cart_table(self):
        self.cart_table.setRowCount(len(self.cart_items))
        for i, item in enumerate(self.cart_items):
            self.cart_table.setItem(i, 0, QTableWidgetItem(str(item["product_id"])))
            self.cart_table.setItem(i, 1, QTableWidgetItem(item["name"]))
            self.cart_table.setItem(i, 2, QTableWidgetItem(item["imei"] or "—"))
            self.cart_table.setItem(i, 3, QTableWidgetItem(str(item["quantity"])))
            self.cart_table.setItem(i, 4, QTableWidgetItem(money_str(item["unit_price"])))
            self.cart_table.setItem(i, 5, QTableWidgetItem(money_str(item["quantity"] * item["unit_price"])))
        self._recalculate_totals()

    def _edit_cart_cell(self, row, col):
        if col == 4: # Цена
            val, ok = QInputDialog.getDouble(self, "Цена", "Введите цену продажи:", float(self.cart_items[row]["unit_price"]), 0, 1000000, 2)
            if ok:
                self.cart_items[row]["unit_price"] = Decimal(str(val))
                self._update_cart_table()
        elif col == 3: # Кол-во
            if self.cart_items[row]["imei"]: return
            val, ok = QInputDialog.getInt(self, "Количество", "Введите количество:", self.cart_items[row]["quantity"], 1, 1000)
            if ok:
                self.cart_items[row]["quantity"] = val
                self._update_cart_table()

    def _remove_cart_item(self):
        row = self.cart_table.currentRow()
        if 0 <= row < len(self.cart_items):
            self.cart_items.pop(row)
            self._update_cart_table()

    def _recalculate_totals(self):
        cur = self.currency_combo.currentText()
        rate = Decimal(str(self.rate_spin.value()))
        
        total = Decimal("0.00")
        for it in self.cart_items:
            amt = it["quantity"] * it["unit_price"]
            # Если валюта позиции отличается от валюты чека (но в POS мы обычно ставим валюту чека)
            total += amt
        
        self.total_label.setText(f"{total:,.2f} {cur}")
        
        p_usd = Decimal(str(self.pay_usd_spin.value()))
        p_tmt = Decimal(str(self.pay_tmt_spin.value()))
        
        paid = p_usd if cur == "USD" else p_usd * rate
        paid += p_tmt if cur == "TMT" else p_tmt / rate
        
        change = paid - total
        self.change_label.setText(f"Сдача: {max(0, change):,.2f} {cur}")

    def _process_checkout(self):
        if not self.cart_items:
            QMessageBox.warning(self, "Ошибка", "Корзина пуста.")
            return
        
        with SessionLocal() as session:
            try:
                rate = Decimal(str(self.rate_spin.value()))
                pays = []
                if self.pay_usd_spin.value() > 0:
                    pays.append({"cash_register_id": self.register_map["USD"], "amount": Decimal(str(self.pay_usd_spin.value())), "currency": "USD", "exchange_rate": rate})
                if self.pay_tmt_spin.value() > 0:
                    pays.append({"cash_register_id": self.register_map["TMT"], "amount": Decimal(str(self.pay_tmt_spin.value())), "currency": "TMT", "exchange_rate": rate})
                
                if not pays:
                    QMessageBox.warning(self, "Ошибка", "Введите сумму оплаты.")
                    return

                SalesService.create_sale(
                    session=session,
                    items=self.cart_items,
                    payments=pays,
                    currency=self.currency_combo.currentText(),
                    exchange_rate=rate,
                    comment=self.comment_input.text()
                )
                session.commit()
                QMessageBox.information(self, "Успех", "Чек успешно подтвержден и сохранен.")
                self.cart_items = []
                self.pay_usd_spin.setValue(0)
                self.pay_tmt_spin.setValue(0)
                self.comment_input.clear()
                self._update_cart_table()
                self.refresh_data()
            except Exception as e:
                session.rollback()
                QMessageBox.critical(self, "Ошибка", str(e))

    def _cancel_selected_sale(self):
        row = self.history_table.currentRow()
        if row < 0: return
        sid = int(self.history_table.item(row, 0).text())
        reason, ok = QInputDialog.getText(self, "Отмена", "Причина отмены:")
        if not ok or not reason: return

        with SessionLocal() as session:
            try:
                # Берем кассу TMT для возврата по умолчанию или ту что в базе
                reg_id = self.register_map.get("TMT") or self.register_map.get("USD")
                SalesService.cancel_sale(session, sid, reason, reg_id)
                session.commit()
                self.refresh_data()
                QMessageBox.information(self, "ОК", "Продажа отменена.")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
