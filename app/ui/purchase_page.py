
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund
from app.services.purchase_service import (
    add_purchase_payment,
    add_purchase_refund,
    cancel_purchase,
    create_purchase,
    get_purchase_balance,
    get_supplier_debt,
)
from app.ui import theme
from app.ui.widgets import Card


def money(value) -> str:
    return f"{Decimal(str(value)):,.2f}"


def convert_currency(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    rate: Decimal,
) -> Decimal:
    if source_currency == target_currency:
        return amount

    if source_currency == "TMT" and target_currency == "USD":
        return amount / rate

    if source_currency == "USD" and target_currency == "TMT":
        return amount * rate

    return amount


def styled_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)

    if primary:
        button.setObjectName("primaryBtn")
    else:
        button.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {theme.ACCENT_BG};
                border-color: {theme.ACCENT};
            }}
        """)

    return button


def configure_table(table: QTableWidget) -> None:
    table.setStyleSheet(f"""
        QTableWidget {{
            background: white;
            color: {theme.TEXT};
            border: none;
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
            padding: 13px 10px;
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
            background: #FFF0E1;
            color: {theme.TEXT};
        }}
    """)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(
        QTableWidget.SelectionBehavior.SelectRows
    )
    table.setSelectionMode(
        QTableWidget.SelectionMode.SingleSelection
    )
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(46)


def money_input(maximum: float = 999999999) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(0, maximum)
    field.setDecimals(2)
    field.setSingleStep(10)
    field.setMinimumHeight(38)
    return field


def rate_input() -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(0.0001, 999999.9999)
    field.setDecimals(4)
    field.setValue(19.5)
    field.setSingleStep(0.1)
    field.setMinimumHeight(38)
    return field


def fill_table(table, rows):
    table.setRowCount(len(rows))

    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if column > 0:
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, column, cell)


class PurchaseDialog(QDialog):
    """Создание закупки с несколькими товарами и платежами."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая закупка")
        self.setMinimumSize(850, 700)
        self.setStyleSheet(theme.STYLE)

        self.items = []
        self.payments = []
        self.products = []

        self._load_products()
        self._build_ui()

    def _load_products(self):
        with SessionLocal() as session:
            self.products = session.scalars(
                select(Product)
                .where(Product.is_active.is_(True))
                .order_by(Product.name)
            ).all()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel("Новая закупка")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        document_form = QFormLayout()
        document_form.setSpacing(10)

        self.currency_input = QComboBox()
        self.currency_input.addItems(["USD", "TMT"])
        self.rate_input = rate_input()

        document_form.addRow("Валюта документа", self.currency_input)
        document_form.addRow("Курс (1 USD = X TMT)", self.rate_input)
        root.addLayout(document_form)

        section = QLabel("Товары")
        section.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(section)

        product_row = QHBoxLayout()

        self.product_input = QComboBox()
        self.product_input.setMinimumHeight(40)
        self.product_input.setMinimumWidth(260)

        for product in self.products:
            self.product_input.addItem(
                f"{product.name}  •  {product.sku}",
                product.id,
            )

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 100000)
        self.quantity_input.setValue(1)
        self.quantity_input.setMinimumHeight(40)

        self.price_input = money_input()
        self.price_input.setMinimumWidth(120)

        add_item_button = styled_button("+ Добавить товар", True)
        add_item_button.clicked.connect(self._add_item)

        product_row.addWidget(self.product_input, 1)
        product_row.addWidget(QLabel("Кол-во"))
        product_row.addWidget(self.quantity_input)
        product_row.addWidget(QLabel("Цена"))
        product_row.addWidget(self.price_input)
        product_row.addWidget(add_item_button)
        root.addLayout(product_row)

        self.items_table = QTableWidget(0, 5)
        self.items_table.setHorizontalHeaderLabels([
            "Товар", "Количество", "Цена за шт.", "Сумма", "",
        ])
        configure_table(self.items_table)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.horizontalHeader().setSectionResizeMode(
            0,
            self.items_table.horizontalHeader().ResizeMode.Stretch,
        )
        self.items_table.setMaximumHeight(190)
        root.addWidget(self.items_table)

        remove_item_button = styled_button("Удалить выбранную позицию")
        remove_item_button.clicked.connect(self._remove_item)
        root.addWidget(
            remove_item_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        self.total_label = QLabel("Итого: 0.00")
        self.total_label.setStyleSheet(
            f"font-size: 15pt; font-weight: 700; color: {theme.NAVY};"
        )
        root.addWidget(self.total_label)

        payment_title = QLabel("Первоначальная оплата")
        payment_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(payment_title)

        payment_row = QHBoxLayout()

        self.payment_currency = QComboBox()
        self.payment_currency.addItems(["USD", "TMT"])
        self.payment_amount = money_input()
        self.payment_amount.setMinimumWidth(130)
        self.payment_rate = rate_input()

        add_payment_button = styled_button("+ Добавить оплату")
        add_payment_button.clicked.connect(self._add_payment)

        payment_row.addWidget(QLabel("Валюта"))
        payment_row.addWidget(self.payment_currency)
        payment_row.addWidget(QLabel("Сумма"))
        payment_row.addWidget(self.payment_amount)
        payment_row.addWidget(QLabel("Курс"))
        payment_row.addWidget(self.payment_rate)
        payment_row.addWidget(add_payment_button)
        root.addLayout(payment_row)

        self.payments_table = QTableWidget(0, 3)
        self.payments_table.setHorizontalHeaderLabels([
            "Валюта", "Сумма", "Курс",
        ])
        configure_table(self.payments_table)
        self.payments_table.horizontalHeader().setStretchLastSection(True)
        self.payments_table.setMaximumHeight(120)
        root.addWidget(self.payments_table)

        remove_payment_button = styled_button("Удалить выбранную оплату")
        remove_payment_button.clicked.connect(self._remove_payment)
        root.addWidget(
            remove_payment_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        note_form = QFormLayout()
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Необязательно")
        note_form.addRow("Примечание", self.note_input)
        root.addLayout(note_form)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_button = styled_button("Отмена")
        cancel_button.clicked.connect(self.reject)

        save_button = styled_button("Сохранить закупку", True)
        save_button.clicked.connect(self._save)

        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

    def _add_item(self):
        product_id = self.product_input.currentData()

        if product_id is None:
            QMessageBox.warning(
                self,
                "Нет товаров",
                "Сначала добавьте товар в каталог.",
            )
            return

        quantity = self.quantity_input.value()
        unit_cost = Decimal(str(self.price_input.value()))

        existing = next(
            (
                item for item in self.items
                if item["product_id"] == product_id
                and item["unit_cost"] == unit_cost
            ),
            None,
        )

        if existing:
            existing["quantity"] += quantity
        else:
            product_name = self.product_input.currentText().split("  •")[0]
            self.items.append({
                "product_id": product_id,
                "name": product_name,
                "quantity": quantity,
                "unit_cost": unit_cost,
            })

        self._refresh_items()

    def _remove_item(self):
        row = self.items_table.currentRow()
        if row < 0:
            return

        self.items.pop(row)
        self._refresh_items()

    def _refresh_items(self):
        self.items_table.setRowCount(len(self.items))
        total = Decimal("0.00")

        for row, item in enumerate(self.items):
            line_total = item["unit_cost"] * item["quantity"]
            total += line_total

            values = [
                item["name"],
                str(item["quantity"]),
                money(item["unit_cost"]),
                money(line_total),
                "×",
            ]

            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.items_table.setItem(row, column, cell)

        self.total_label.setText(
            f"Итого: {money(total)} {self.currency_input.currentText()}"
        )

    def _add_payment(self):
        amount = Decimal(str(self.payment_amount.value()))

        if amount <= 0:
            QMessageBox.warning(
                self,
                "Некорректная сумма",
                "Укажи сумму платежа больше нуля.",
            )
            return

        self.payments.append({
            "currency": self.payment_currency.currentText(),
            "amount": amount,
            "exchange_rate": Decimal(str(self.payment_rate.value())),
        })
        self._refresh_payments()
        self.payment_amount.setValue(0)

    def _remove_payment(self):
        row = self.payments_table.currentRow()
        if row < 0:
            return

        self.payments.pop(row)
        self._refresh_payments()

    def _refresh_payments(self):
        self.payments_table.setRowCount(len(self.payments))

        for row, payment in enumerate(self.payments):
            values = [
                payment["currency"],
                money(payment["amount"]),
                money(payment["exchange_rate"]),
            ]

            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.payments_table.setItem(row, column, cell)

    def _save(self):
        if not self.items:
            QMessageBox.warning(
                self,
                "Нет товаров",
                "Добавь хотя бы одну товарную позицию.",
            )
            return

        try:
            purchase_id = create_purchase(
                items=[
                    {
                        "product_id": item["product_id"],
                        "quantity": item["quantity"],
                        "unit_cost": item["unit_cost"],
                    }
                    for item in self.items
                ],
                currency=self.currency_input.currentText(),
                exchange_rate=self.rate_input.value(),
                payments=self.payments,
                note=self.note_input.text().strip() or None,
            )

            QMessageBox.information(
                self,
                "Закупка сохранена",
                f"Закупка №{purchase_id} успешно создана.",
            )
            self.accept()

        except (ValueError, TypeError, KeyError) as error:
            QMessageBox.warning(self, "Проверь данные", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить закупку:\n{error}",
            )


class RefundDialog(QDialog):
    """Регистрация возврата денег от поставщика."""

    def __init__(self, purchase_currency: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Возврат денег от поставщика")
        self.setMinimumWidth(440)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel("Регистрация возврата")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        info = QLabel(
            f"Валюта закупки: {purchase_currency}\n"
            "Укажи фактически полученную сумму и курс на дату возврата."
        )
        info.setObjectName("mutedText")
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(12)

        self.currency_input = QComboBox()
        self.currency_input.addItems(["USD", "TMT"])

        self.amount_input = money_input()
        self.rate_input = rate_input()

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText(
            "Необязательно"
        )

        form.addRow("Валюта возврата", self.currency_input)
        form.addRow("Сумма возврата", self.amount_input)
        form.addRow("Курс (1 USD = X TMT)", self.rate_input)
        form.addRow("Примечание", self.description_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_button = styled_button("Отмена")
        cancel_button.clicked.connect(self.reject)

        save_button = styled_button("Зарегистрировать возврат", True)
        save_button.clicked.connect(self._validate)

        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

    def _validate(self):
        if self.amount_input.value() <= 0:
            QMessageBox.warning(
                self,
                "Некорректная сумма",
                "Сумма возврата должна быть больше нуля.",
            )
            return

        self.accept()

    def get_data(self) -> dict:
        return {
            "currency": self.currency_input.currentText(),
            "amount": Decimal(str(self.amount_input.value())),
            "exchange_rate": Decimal(str(self.rate_input.value())),
            "description": self.description_input.text().strip() or None,
        }


class PurchaseDetailsDialog(QDialog):
    """Просмотр закупки, платежей, аннулирования и возвратов."""

    def __init__(self, purchase_id: int, parent=None):
        super().__init__(parent)
        self.purchase_id = purchase_id

        self.setWindowTitle(f"Закупка №{purchase_id}")
        self.setMinimumSize(820, 820)
        self.resize(900, 900)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        self.title_label = QLabel(f"Закупка №{self.purchase_id}")
        self.title_label.setObjectName("pageTitle")
        root.addWidget(self.title_label)

        self.info_label = QLabel()
        self.info_label.setObjectName("mutedText")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            "font-weight: 700; padding: 8px 12px; "
            "background: #F2F3F5; border-radius: 8px;"
        )
        root.addWidget(self.status_label)

        self.balance_label = QLabel()
        self.balance_label.setStyleSheet(
            f"font-size: 16pt; font-weight: 700; color: {theme.ACCENT};"
        )
        root.addWidget(self.balance_label)

        self.cancellation_label = QLabel()
        self.cancellation_label.setWordWrap(True)
        self.cancellation_label.setObjectName("mutedText")
        root.addWidget(self.cancellation_label)

        items_title = QLabel("Состав закупки")
        items_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(items_title)

        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels([
            "Товар", "Количество", "Цена", "Сумма",
        ])
        configure_table(self.items_table)
        self.items_table.horizontalHeader().setSectionResizeMode(
            0,
            self.items_table.horizontalHeader().ResizeMode.Stretch,
        )
        self.items_table.setMaximumHeight(170)
        root.addWidget(self.items_table)

        payments_title = QLabel("История платежей")
        payments_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(payments_title)

        self.payments_table = QTableWidget(0, 4)
        self.payments_table.setHorizontalHeaderLabels([
            "Дата", "Валюта", "Сумма", "Курс",
        ])
        configure_table(self.payments_table)
        self.payments_table.horizontalHeader().setStretchLastSection(True)
        self.payments_table.setMaximumHeight(135)
        root.addWidget(self.payments_table)

        self.payment_section = QWidget()
        payment_layout = QVBoxLayout(self.payment_section)
        payment_layout.setContentsMargins(0, 0, 0, 0)
        payment_layout.setSpacing(8)

        payment_title = QLabel("Добавить платёж")
        payment_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        payment_layout.addWidget(payment_title)

        payment_row = QHBoxLayout()

        self.payment_currency = QComboBox()
        self.payment_currency.addItems(["USD", "TMT"])
        self.payment_amount = money_input()
        self.payment_rate = rate_input()

        add_payment_button = styled_button("Добавить платёж", True)
        add_payment_button.clicked.connect(self._add_payment)

        payment_row.addWidget(QLabel("Валюта"))
        payment_row.addWidget(self.payment_currency)
        payment_row.addWidget(QLabel("Сумма"))
        payment_row.addWidget(self.payment_amount)
        payment_row.addWidget(QLabel("Курс"))
        payment_row.addWidget(self.payment_rate)
        payment_row.addWidget(add_payment_button)
        payment_layout.addLayout(payment_row)

        root.addWidget(self.payment_section)

        refunds_title = QLabel("История возвратов")
        refunds_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(refunds_title)

        self.refunds_table = QTableWidget(0, 4)
        self.refunds_table.setHorizontalHeaderLabels([
            "Дата", "Валюта", "Сумма", "Примечание",
        ])
        configure_table(self.refunds_table)
        self.refunds_table.horizontalHeader().setSectionResizeMode(
            3,
            self.refunds_table.horizontalHeader().ResizeMode.Stretch,
        )
        self.refunds_table.setMaximumHeight(130)
        root.addWidget(self.refunds_table)

        self.refund_section = QWidget()
        refund_layout = QVBoxLayout(self.refund_section)
        refund_layout.setContentsMargins(0, 0, 0, 0)

        self.refund_hint = QLabel()
        self.refund_hint.setObjectName("mutedText")
        self.refund_hint.setWordWrap(True)
        refund_layout.addWidget(self.refund_hint)

        self.refund_button = styled_button(
            "Зарегистрировать возврат",
            True,
        )
        self.refund_button.clicked.connect(self._open_refund)
        refund_layout.addWidget(
            self.refund_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

        root.addWidget(self.refund_section)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.cancel_purchase_button = styled_button(
            "Аннулировать закупку"
        )
        self.cancel_purchase_button.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {theme.RED};
                border: 1px solid {theme.RED};
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #FFF0F0;
            }}
        """)
        self.cancel_purchase_button.clicked.connect(
            self._cancel_purchase
        )

        close_button = styled_button("Закрыть")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(self.cancel_purchase_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def _load_data(self):
        with SessionLocal() as session:
            purchase = session.get(Purchase, self.purchase_id)

            if purchase is None:
                QMessageBox.warning(
                    self,
                    "Закупка не найдена",
                    "Документ не существует.",
                )
                self.reject()
                return

            self.currency = purchase.currency
            self.total_amount = Decimal(str(purchase.total_amount))
            self.status = purchase.status
            self.document_rate = Decimal(str(purchase.exchange_rate))

            self.info_label.setText(
                f"Дата: {purchase.purchase_date:%d.%m.%Y %H:%M}   "
                f"Валюта: {purchase.currency}   "
                f"Курс: {purchase.exchange_rate}"
            )

            if purchase.status == "cancelled":
                self.cancelled_at = purchase.cancelled_at
                self.cancellation_reason = purchase.cancellation_reason
            else:
                self.cancelled_at = None
                self.cancellation_reason = None

            items = session.execute(
                select(PurchaseItem, Product.name)
                .join(Product, PurchaseItem.product_id == Product.id)
                .where(PurchaseItem.purchase_id == self.purchase_id)
            ).all()

            payments = session.scalars(
                select(PurchasePayment)
                .where(PurchasePayment.purchase_id == self.purchase_id)
                .order_by(PurchasePayment.payment_date)
            ).all()

            refunds = session.scalars(
                select(PurchaseRefund)
                .where(PurchaseRefund.purchase_id == self.purchase_id)
                .order_by(PurchaseRefund.refund_date)
            ).all()

            item_rows = [
                (
                    name,
                    item.quantity,
                    money(item.unit_cost),
                    money(item.total_cost),
                )
                for item, name in items
            ]

            payment_rows = [
                (
                    payment.payment_date.strftime("%d.%m.%Y %H:%M"),
                    payment.currency,
                    money(payment.amount),
                    money(payment.exchange_rate),
                )
                for payment in payments
            ]

            refund_rows = [
                (
                    refund.refund_date.strftime("%d.%m.%Y %H:%M"),
                    refund.currency,
                    money(refund.amount),
                    refund.description or "—",
                )
                for refund in refunds
            ]

            paid = Decimal("0.00")
            for payment in payments:
                paid += convert_currency(
                    Decimal(str(payment.amount)),
                    payment.currency,
                    purchase.currency,
                    Decimal(str(payment.exchange_rate)),
                )

        fill_table(self.items_table, item_rows)
        fill_table(self.payments_table, payment_rows)
        fill_table(self.refunds_table, refund_rows)

        if self.status == "cancelled":
            debt = get_supplier_debt(self.purchase_id)

            self.status_label.setText("Аннулирована")
            self.status_label.setStyleSheet(
                "font-weight: 700; color: #737B86; "
                "background: #F0F1F3; padding: 8px 12px; "
                "border-radius: 8px;"
            )

            self.balance_label.setText(
                f"Задолженность поставщика: "
                f"{money(debt)} {self.currency}"
            )
            self.balance_label.setStyleSheet(
                f"font-size: 16pt; font-weight: 700; color: {theme.RED};"
            )

            cancelled_text = "Дата аннулирования: "
            if self.cancelled_at:
                cancelled_text += (
                    self.cancelled_at.strftime("%d.%m.%Y %H:%M")
                )
            cancelled_text += (
                f"\nПричина: {self.cancellation_reason or '—'}"
            )
            self.cancellation_label.setText(cancelled_text)

            self.payment_section.hide()
            self.cancel_purchase_button.hide()
            self.refund_section.show()

            self.refund_hint.setText(
                f"Поставщик должен вернуть: {money(debt)} "
                f"{self.currency}. Возвраты могут быть частичными."
            )
            self.refund_button.setEnabled(debt > 0)

        else:
            balance = get_purchase_balance(self.purchase_id)

            self.status_label.setText(
                "Оплачено" if balance == 0 else "Активная закупка"
            )
            self.status_label.setStyleSheet(
                f"font-weight: 700; color: {theme.GREEN}; "
                "background: #EAF7EF; padding: 8px 12px; "
                "border-radius: 8px;"
            )

            self.balance_label.setText(
                f"Остаток долга магазина: "
                f"{money(balance)} {self.currency}"
            )
            self.balance_label.setStyleSheet(
                f"font-size: 16pt; font-weight: 700; color: {theme.ACCENT};"
            )

            self.cancellation_label.clear()
            self.payment_section.show()
            self.cancel_purchase_button.show()
            self.refund_section.hide()

            self.payment_rate.setValue(float(self.document_rate))

        self._update_table_height(self.items_table, 170)
        self._update_table_height(self.payments_table, 135)
        self._update_table_height(self.refunds_table, 130)

    @staticmethod
    def _update_table_height(table, maximum):
        row_height = table.verticalHeader().defaultSectionSize()
        header_height = table.horizontalHeader().height()
        height = header_height + table.rowCount() * row_height + 4
        table.setFixedHeight(min(maximum, max(65, height)))

    def _add_payment(self):
        amount = Decimal(str(self.payment_amount.value()))

        if amount <= 0:
            QMessageBox.warning(
                self,
                "Некорректная сумма",
                "Сумма платежа должна быть больше нуля.",
            )
            return

        try:
            add_purchase_payment(
                purchase_id=self.purchase_id,
                currency=self.payment_currency.currentText(),
                amount=amount,
                exchange_rate=self.payment_rate.value(),
            )
            self.payment_amount.setValue(0)
            self._load_data()

        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Проверь данные", str(error))
        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка платежа",
                f"Не удалось добавить платёж:\n{error}",
            )

    def _cancel_purchase(self):
        reason, accepted = QInputDialog.getText(
            self,
            "Аннулирование закупки",
            "Укажи причину аннулирования:",
        )

        if not accepted:
            return

        if not reason.strip():
            QMessageBox.warning(
                self,
                "Не указана причина",
                "Для аннулирования необходимо указать причину.",
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Подтверждение аннулирования",
            "Аннулировать закупку?\n\n"
            "Товары будут списаны со склада. "
            "Неоплаченный долг магазина будет обнулён, "
            "а уже выплаченные деньги станут задолженностью "
            "поставщика перед магазином.\n\n"
            "Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        try:
            cancel_purchase(
                self.purchase_id,
                reason,
            )

            QMessageBox.information(
                self,
                "Закупка аннулирована",
                "Закупка успешно аннулирована.",
            )
            self._load_data()

        except (ValueError, TypeError) as error:
            QMessageBox.warning(
                self,
                "Невозможно аннулировать закупку",
                str(error),
            )
        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось аннулировать закупку:\n{error}",
            )

    def _open_refund(self):
        dialog = RefundDialog(self.currency, self)

        if not dialog.exec():
            return

        data = dialog.get_data()

        try:
            add_purchase_refund(
                purchase_id=self.purchase_id,
                currency=data["currency"],
                amount=data["amount"],
                exchange_rate=data["exchange_rate"],
                description=data["description"],
            )

            QMessageBox.information(
                self,
                "Возврат зарегистрирован",
                "Деньги добавлены в кассовый журнал.",
            )
            self._load_data()

        except (ValueError, TypeError) as error:
            QMessageBox.warning(
                self,
                "Невозможно зарегистрировать возврат",
                str(error),
            )
        except SQLAlchemyError as error:
            QMessageBox.critical(
                self,
                "Ошибка возврата",
                f"Не удалось зарегистрировать возврат:\n{error}",
            )


class PurchasePage(QWidget):
    """Журнал закупок."""

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.purchases = []

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()

        title = QLabel("Закупки")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()

        self.count_label = QLabel("Документов: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        refresh_button = styled_button("↻  Обновить")
        refresh_button.clicked.connect(self._load_data)
        header.addWidget(refresh_button)

        add_button = styled_button("+ Новая закупка", True)
        add_button.clicked.connect(self._open_new_purchase)
        header.addWidget(add_button)

        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)

        self.total_value = QLabel("0")
        self.debt_usd_value = QLabel("0.00 USD")
        self.debt_tmt_value = QLabel("0.00 TMT")

        stats.addWidget(self._stat_card(
            "Всего закупок",
            self.total_value,
            theme.NAVY,
        ))
        stats.addWidget(self._stat_card(
            "Долг в USD",
            self.debt_usd_value,
            theme.ACCENT,
        ))
        stats.addWidget(self._stat_card(
            "Долг в TMT",
            self.debt_tmt_value,
            theme.RED,
        ))

        root.addLayout(stats)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Поиск по номеру закупки или примечанию..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(42)
        self.search_input.textChanged.connect(self._filter_data)
        root.addWidget(self.search_input)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "№",
            "Дата",
            "Валюта",
            "Сумма",
            "Оплачено",
            "Остаток долга",
            "Состояние",
        ])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            1,
            self.table.horizontalHeader().ResizeMode.Stretch,
        )
        self.table.cellDoubleClicked.connect(self._open_selected)
        root.addWidget(self.table, 1)

        hint = QLabel("Дважды щёлкни по закупке, чтобы открыть документ.")
        hint.setObjectName("mutedText")
        root.addWidget(hint)

    def _stat_card(self, title: str, value: QLabel, color: str) -> Card:
        card = Card(margins=(18, 14, 18, 14), spacing=6)

        label = QLabel(title)
        label.setObjectName("mutedText")
        value.setStyleSheet(
            f"font-size: 20pt; font-weight: 700; color: {color};"
        )

        card.body.addWidget(label)
        card.body.addWidget(value)
        return card

    def _load_data(self):
        with SessionLocal() as session:
            purchases = session.scalars(
                select(Purchase).order_by(Purchase.purchase_date.desc())
            ).all()

            self.purchases = [
                {
                    "id": purchase.id,
                    "date": purchase.purchase_date,
                    "currency": purchase.currency,
                    "total": Decimal(str(purchase.total_amount)),
                    "note": purchase.note or "",
                    "status": purchase.status,
                }
                for purchase in purchases
            ]

        debt_usd = Decimal("0.00")
        debt_tmt = Decimal("0.00")

        for purchase in self.purchases:
            purchase["balance"] = get_purchase_balance(purchase["id"])

            if purchase["status"] == "cancelled":
                purchase["paid"] = Decimal("0.00")
            else:
                purchase["paid"] = (
                    purchase["total"] - purchase["balance"]
                )

                if purchase["currency"] == "USD":
                    debt_usd += purchase["balance"]
                else:
                    debt_tmt += purchase["balance"]

        self.total_value.setText(str(len(self.purchases)))
        self.debt_usd_value.setText(f"{money(debt_usd)} USD")
        self.debt_tmt_value.setText(f"{money(debt_tmt)} TMT")
        self.count_label.setText(
            f"Документов: {len(self.purchases)}"
        )

        self._filter_data()

    def _filter_data(self, *_args):
        query = self.search_input.text().strip().lower()

        filtered = [
            purchase
            for purchase in self.purchases
            if (
                query in str(purchase["id"]).lower()
                or query in purchase["note"].lower()
            )
        ]

        self.table.setRowCount(len(filtered))

        for row, purchase in enumerate(filtered):
            balance = purchase["balance"]
            cancelled = purchase["status"] == "cancelled"

            if cancelled:
                status = "Аннулирована"
                status_color = "#858B94"
                paid_text = "—"
                balance_text = "—"
            else:
                status = "Оплачено" if balance == 0 else "Есть долг"
                status_color = (
                    theme.GREEN if balance == 0 else theme.ACCENT
                )
                paid_text = money(purchase["paid"])
                balance_text = money(balance)

            values = [
                str(purchase["id"]),
                purchase["date"].strftime("%d.%m.%Y %H:%M"),
                purchase["currency"],
                money(purchase["total"]),
                paid_text,
                balance_text,
                status,
            ]

            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)

                if column in (0, 2, 3, 4, 5):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if column == 6:
                    cell.setForeground(QColor("white"))
                    cell.setBackground(QColor(status_color))
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if cancelled and column != 6:
                    cell.setForeground(QColor("#858B94"))

                self.table.setItem(row, column, cell)

            self.table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole,
                purchase["id"],
            )

    def _open_new_purchase(self):
        dialog = PurchaseDialog(self)

        if dialog.exec():
            self._load_data()

    def _open_selected(self, row: int, _column: int):
        item = self.table.item(row, 0)

        if item is None:
            return

        purchase_id = item.data(Qt.ItemDataRole.UserRole)
        dialog = PurchaseDetailsDialog(purchase_id, self)
        dialog.exec()
        self._load_data()
