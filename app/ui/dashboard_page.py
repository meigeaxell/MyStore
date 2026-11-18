from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.repositories.product_repository import get_low_stock_products
from app.ui import theme
from app.ui.widgets import BarChart, Card, ColorStatCard, KpiCard


class DashboardPage(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.low_stock_products = get_low_stock_products()
        content = QWidget()
        content.setObjectName("page")
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(18)
        self.setWidget(content)

        root.addLayout(self._header())
        root.addWidget(self._alert())
        root.addLayout(self._stat_row())
        root.addLayout(self._kpi_row())

        lower = QHBoxLayout()
        lower.setSpacing(18)
        lower.addWidget(self._chart_card(), 3)
        lower.addWidget(self._side_card(), 2)
        root.addLayout(lower)
        root.addStretch()

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)

        title = QLabel("Добро пожаловать!")
        title.setObjectName("pageTitle")

        sub = QLabel("Сегодня оформлено <b>24 заказа</b>")
        sub.setObjectName("mutedText")

        col.addWidget(title)
        col.addWidget(sub)
        row.addLayout(col, 1)

        today = QDate.currentDate()
        week_start = today.addDays(1 - today.dayOfWeek())
        week_end = week_start.addDays(6)

        date_text = (
            f"📅  {week_start.toString('dd.MM.yyyy')} – "
            f"{week_end.toString('dd.MM.yyyy')}"
        )

        pill = QLabel(date_text)
        pill.setObjectName("datePill")
        row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)

        return row

    
    def _alert(self) -> QFrame:
        box = QFrame()
        box.setObjectName("alert")

        if not self.low_stock_products:
            box.hide()
            return box

        product = self.low_stock_products[0]

        row = QHBoxLayout(box)
        row.setContentsMargins(14, 8, 8, 8)

        text = QLabel(
            f"Товар <b>{product.name}</b> заканчивается: "
            f"на складе {product.stock_quantity} шт. "
            f"(минимум: {product.min_stock_quantity} шт.)"
        )
        text.setObjectName("alertText")
        row.addWidget(text, 1)

        action = QPushButton("Оформить закупку")
        action.setObjectName("linkBtn")
        action.setCursor(Qt.CursorShape.PointingHandCursor)

        close = QPushButton("✕")
        close.setObjectName("alertClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(box.hide)

        row.addWidget(action)
        row.addWidget(close)

        return box
    
    def _stat_row(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        data = [
            ("Продажи", "0.00 USD", "0%", True, theme.ACCENT, "🧾"),
            ("Возвраты", "0.00 USD", "0%", False, theme.NAVY, "↩"),
            ("Закупки", "0.00 USD", "0%", True, theme.TEAL, "📦"),
            ("Количество чеков", "0", "0%", True, theme.BLUE, "🧮"),
        ]

        for i, d in enumerate(data):
            grid.addWidget(ColorStatCard(*d), 0, i)
            grid.setColumnStretch(i, 1)

        return grid

    def _kpi_row(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        data = [
            ("Прибыль USD", "0.00 USD", "0%", True, "#E8F1FF", "📈"),
            ("Прибыль TMT", "0.00 TMT", "0%", True, "#E3F6F1", "📈"),
            ("Касса USD", "0.00 USD", "0%", True, "#FDEBE7", "💵"),
            ("Касса TMT", "0.00 TMT", "0%", True, "#F0EAFE", "💵"),
        ]

        for i, d in enumerate(data):
            grid.addWidget(KpiCard(*d), 0, i)
            grid.setColumnStretch(i, 1)

        return grid

    def _chart_card(self) -> Card:
        card = Card()
        head = QHBoxLayout()
        title = QLabel("Продажи и закупки")
        title.setObjectName("cardTitle")
        head.addWidget(title, 1)
        group = QButtonGroup(card)
        for i, name in enumerate(["1Д", "1Н", "1М", "3М", "6М", "1Г"]):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == "1Г")
            group.addButton(b)
            head.addWidget(b)
        card.body.addLayout(head)

        legend = QLabel(
            f"<span style='color:{theme.ACCENT_SOFT}'>●</span> Закупки <b>49K</b>"
            f"&nbsp;&nbsp;&nbsp;<span style='color:{theme.ACCENT}'>●</span> Продажи <b>38K</b>"
        )
        legend.setObjectName("mutedText")
        card.body.addWidget(legend)

        months = [
            "Янв",
            "Фев",
            "Мар",
            "Апр",
            "Май",
            "Июн",
            "Июл",
            "Авг",
            "Сен",
            "Окт",
            "Ноя",
            "Дек",
        ]
        purchases = [53, 37, 23, 52, 42, 52, 23, 29, 46, 33, 45, 31]
        sales = [13, 23, 8, 13, 26, 13, 10, 17, 42, 4, 29, 13]
        card.body.addWidget(BarChart(months, purchases, sales), 1)
        return card

    def _side_card(self) -> Card:
        card = Card()
        t = QLabel("Склад сейчас")
        t.setObjectName("cardTitle")
        card.body.addWidget(t)

        row = QHBoxLayout()
        row.setSpacing(10)
        for label, value, tint in [
            ("Новые телефоны", "0", "#E8F1FF"),
            ("Б/у телефоны", "0", "#E3F6F1"),
            ("Аксессуары", "0", "#FDEBE7"),
        ]:
            box = QFrame()
            box.setStyleSheet(f"background:{tint}; border-radius:10px;")
            v = QVBoxLayout(box)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(0)
            a = QLabel(label)
            a.setObjectName("mutedText")
            b = QLabel(value)
            b.setStyleSheet("font-size:14pt; font-weight:700;")
            v.addWidget(a)
            v.addWidget(b)
            row.addWidget(box, 1)
        card.body.addLayout(row)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.BORDER};")
        card.body.addWidget(line)

        head = QHBoxLayout()
        h = QLabel("Заканчиваются на складе")
        h.setStyleSheet("font-weight:700;")
        head.addWidget(h, 1)
        all_btn = QPushButton("Все")
        all_btn.setObjectName("linkBtn")
        head.addWidget(all_btn)
        card.body.addLayout(head)

        products = self.low_stock_products

        if products:
            for product in products:
                r = QHBoxLayout()
                r.addWidget(QLabel(product.name), 1)

                badge = QLabel(f"{product.stock_quantity} шт.")
                badge.setStyleSheet(
                    "background:#FDECEA; color:#B42318; border-radius:8px; "
                    "padding:2px 9px; font-size:8.5pt; font-weight:600;"
                )

                r.addWidget(badge)
                card.body.addLayout(r)
        else:
            empty = QLabel("Нет товаров с низким остатком")
            empty.setObjectName("mutedText")
            card.body.addWidget(empty)
        card.body.addStretch()
        return card
