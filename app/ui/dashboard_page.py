import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.device_exchange import DeviceExchange
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.stock_item import StockItem
from app.repositories.product_repository import get_low_stock_products
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.ui import theme
from app.ui.widgets import (
    BarChart,
    Card,
    ColorStatCard,
    KpiCard,
    configure_table,
    money_str,
)

MONTH_NAMES_SHORT = ["Ýan", "Few", "Mar", "Apr", "Maý", "Iýun", "Iýul", "Awg", "Sen", "Okt", "Noý", "Dek"]
MONTH_NAMES_FULL = [
    "Ýanwar", "Fewral", "Mart", "Aprel", "Maý", "Iýun",
    "Iýul", "Awgust", "Sentýabr", "Oktýabr", "Noýabr", "Dekabr",
]
WEEKDAY_SHORT = ["Duş", "Siş", "Çar", "Pen", "Ann", "Şen", "Ýek"]

RANGE_CONFIG = {
    "1G": ("günlük", "Şu günki satyş we alyş dinamikasy (sagat boýunça)"),
    "1H": ("hepdelik", "7 günlük satyş we alyş dinamikasy"),
    "1A": ("aýlyk", "Şu aýyň satyş we alyş dinamikasy (gün boýunça)"),
    "6A": ("6 aýlyk", "6 aýlyk satyş we alyş dinamikasy"),
    "1Ý": ("ýyllyk", "Ýyllyk satyş we alyş dinamikasy (aý boýunça)"),
}


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, (total % 12) + 1


class DashboardPage(QScrollArea):
    """Esasy panel MobileStore (1G, 1H, 1A, 6A, 1Ý)."""

    navigateRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.current_range = "1A"
        self.low_stock_products = []
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        self.content = QWidget()
        self.content.setObjectName("page")
        self.root_layout = QVBoxLayout(self.content)
        self.root_layout.setContentsMargins(28, 24, 28, 28)
        self.root_layout.setSpacing(18)
        self.setWidget(self.content)

    def _set_time_range(self, range_key: str) -> None:
        if range_key in RANGE_CONFIG and range_key != self.current_range:
            self.current_range = range_key
            self.refresh_data()

    def refresh_data(self) -> None:
        while self.root_layout.count():
            item = self.root_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        self.low_stock_products = get_low_stock_products()
        stats = self._query_dashboard_stats()

        self.root_layout.addLayout(self._header(stats))
        self.root_layout.addWidget(self._alert())
        self.root_layout.addLayout(self._stat_row(stats))
        self.root_layout.addLayout(self._kpi_row(stats))
        self.root_layout.addWidget(self._debts_card(stats))

        lower = QHBoxLayout()
        lower.setSpacing(18)
        lower.addWidget(self._chart_card(stats), 3)
        lower.addWidget(self._side_card(stats), 2)
        self.root_layout.addLayout(lower)

        self.root_layout.addWidget(self._recent_operations_card(stats))
        self.root_layout.addStretch()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _build_buckets_for_range(
        self,
        today: date,
    ) -> tuple[datetime, datetime, list[str], list[dict], callable]:
        """Создаёт временные интервалы (корзины) и функцию сопоставления даты для выбранного режима."""
        mode = self.current_range

        if mode == "1G":
            start_dt = datetime.combine(today, time.min)
            end_dt = datetime.combine(today, time.max)
            labels = [f"{h:02d}:00" for h in range(0, 24, 2)]
            buckets = [
                self._empty_bucket(f"Şu gün ({today:%d.%m.%Y}), {h:02d}:00–{h + 2:02d}:00")
                for h in range(0, 24, 2)
            ]

            def matcher(dt: datetime) -> int | None:
                if dt.date() != today:
                    return None
                return min(11, dt.hour // 2)

            return start_dt, end_dt, labels, buckets, matcher

        if mode == "1H":
            start_day = today - timedelta(days=6)
            start_dt = datetime.combine(start_day, time.min)
            end_dt = datetime.combine(today, time.max)
            days = [start_day + timedelta(days=i) for i in range(7)]
            labels = [f"{WEEKDAY_SHORT[d.weekday()]} {d:%d.%m}" for d in days]
            buckets = [
                self._empty_bucket(f"{WEEKDAY_SHORT[d.weekday()]}, {d:%d.%m.%Y}")
                for d in days
            ]

            def matcher(dt: datetime) -> int | None:
                delta = (dt.date() - start_day).days
                return delta if 0 <= delta < 7 else None

            return start_dt, end_dt, labels, buckets, matcher

        if mode == "1A":
            days_in_month = calendar.monthrange(today.year, today.month)[1]
            start_day = today.replace(day=1)
            end_day = today.replace(day=days_in_month)
            start_dt = datetime.combine(start_day, time.min)
            end_dt = datetime.combine(end_day, time.max)
            labels = [f"{d:02d}" for d in range(1, days_in_month + 1)]
            buckets = [
                self._empty_bucket(f"{d:02d}.{today.month:02d}.{today.year}")
                for d in range(1, days_in_month + 1)
            ]

            def matcher(dt: datetime) -> int | None:
                if dt.year == today.year and dt.month == today.month:
                    return dt.day - 1
                return None

            return start_dt, end_dt, labels, buckets, matcher

        if mode == "6A":
            ym_list = [_shift_month(today.year, today.month, -i) for i in range(5, -1, -1)]
            first_y, first_m = ym_list[0]
            last_y, last_m = ym_list[-1]
            last_day = calendar.monthrange(last_y, last_m)[1]
            start_dt = datetime.combine(date(first_y, first_m, 1), time.min)
            end_dt = datetime.combine(date(last_y, last_m, last_day), time.max)
            ym_to_idx = {ym: idx for idx, ym in enumerate(ym_list)}
            labels = [MONTH_NAMES_SHORT[m - 1] for _y, m in ym_list]
            buckets = [
                self._empty_bucket(f"{MONTH_NAMES_FULL[m - 1]} {y}")
                for y, m in ym_list
            ]

            def matcher(dt: datetime) -> int | None:
                return ym_to_idx.get((dt.year, dt.month))

            return start_dt, end_dt, labels, buckets, matcher

        # Режим "1Г" (текущий год по месяцам)
        year = today.year
        start_dt = datetime.combine(date(year, 1, 1), time.min)
        end_dt = datetime.combine(date(year, 12, 31), time.max)
        labels = list(MONTH_NAMES_SHORT)
        buckets = [
            self._empty_bucket(f"{MONTH_NAMES_FULL[m - 1]} {year}")
            for m in range(1, 13)
        ]

        def matcher(dt: datetime) -> int | None:
            return (dt.month - 1) if dt.year == year else None

        return start_dt, end_dt, labels, buckets, matcher

    @staticmethod
    def _empty_bucket(title: str) -> dict:
        return {
            "title": title,
            "sales_usd": Decimal("0.00"),
            "sales_tmt": Decimal("0.00"),
            "profit_usd": Decimal("0.00"),
            "profit_tmt": Decimal("0.00"),
            "purchases_usd": Decimal("0.00"),
            "purchases_tmt": Decimal("0.00"),
            "receipts_count": 0,
            "sales_bar": 0.0,
            "purchases_bar": 0.0,
        }

    def _query_dashboard_stats(self) -> dict:
        today = date.today()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        range_start, range_end, chart_labels, buckets, matcher = self._build_buckets_for_range(today)

        with SessionLocal() as session:
            balances = FinanceService.get_register_balances(session)
            debts = FinanceService.get_all_outstanding_balances(session)
            sales_today = ReportService.get_sales_report(session, today_start, today_end)
            sales_period = ReportService.get_sales_report(session, range_start, range_end)
            profit_period = ReportService.get_profit_report(session, range_start, range_end)
            inv = ReportService.get_inventory_report(session)

            purchases_all = session.scalars(
                select(Purchase).order_by(Purchase.purchase_date.desc())
            ).all()
            sales_all = session.scalars(
                select(Sale).order_by(Sale.sale_date.desc())
            ).all()
            exchanges_all = session.scalars(
                select(DeviceExchange).order_by(DeviceExchange.exchange_date.desc())
            ).all()

            pur_usd = Decimal("0.00")
            pur_tmt = Decimal("0.00")
            for p in purchases_all:
                if p.status == "active" and p.purchase_date and range_start <= p.purchase_date <= range_end:
                    amt = Decimal(str(p.total_amount))
                    rate = Decimal(str(p.exchange_rate or 19.5))
                    if p.currency == "USD":
                        pur_usd += amt
                    elif p.currency == "TMT":
                        pur_tmt += amt

                    b_idx = matcher(p.purchase_date)
                    if b_idx is not None:
                        if p.currency == "USD":
                            buckets[b_idx]["purchases_usd"] += amt
                            buckets[b_idx]["purchases_bar"] += float(amt * rate)
                        else:
                            buckets[b_idx]["purchases_tmt"] += amt
                            buckets[b_idx]["purchases_bar"] += float(amt)

            for s in sales_all:
                if s.status != "cancelled" and s.sale_date and range_start <= s.sale_date <= range_end:
                    b_idx = matcher(s.sale_date)
                    if b_idx is not None:
                        amt = Decimal(str(s.total_amount))
                        rate = Decimal(str(s.exchange_rate or 19.5))
                        buckets[b_idx]["receipts_count"] += 1
                        if s.currency == "USD":
                            buckets[b_idx]["sales_usd"] += amt
                            buckets[b_idx]["sales_bar"] += float(amt * rate)
                        else:
                            buckets[b_idx]["sales_tmt"] += amt
                            buckets[b_idx]["sales_bar"] += float(amt)

            for row in profit_period["rows"]:
                s_date = row["sale_date"]
                if s_date and range_start <= s_date <= range_end:
                    b_idx = matcher(s_date)
                    if b_idx is not None:
                        if row["currency"] == "USD":
                            buckets[b_idx]["profit_usd"] += Decimal(str(row["gross_profit"]))
                        else:
                            buckets[b_idx]["profit_tmt"] += Decimal(str(row["gross_profit"]))

            exchanges_in_period = sum(
                1
                for ex in exchanges_all
                if ex.exchange_date and range_start <= ex.exchange_date <= range_end
            )

            in_stock_imeis = session.scalars(
                select(StockItem).where(StockItem.status == "in_stock")
            ).all()
            new_phones = sum(1 for s in in_stock_imeis if s.condition == "new")
            used_phones = sum(1 for s in in_stock_imeis if s.condition != "new")

            recent_ops = []
            for s in sales_all[:5]:
                op_type = "Satyş ýatyryldy" if s.status == "cancelled" else "Satyş"
                recent_ops.append({
                    "date": s.sale_date,
                    "type": op_type,
                    "doc": f"Çek {s.receipt_number}",
                    "amount": f"{money_str(s.total_amount)} {s.currency}",
                    "info": s.customer_name or s.cancellation_reason or "Bölek satyş",
                })
            for p in purchases_all[:5]:
                op_type = "Alyş ýatyryldy" if p.status == "cancelled" else "Alyş"
                recent_ops.append({
                    "date": p.purchase_date,
                    "type": op_type,
                    "doc": f"Alyş №{p.id}",
                    "amount": f"{money_str(p.total_amount)} {p.currency}",
                    "info": p.supplier_name or p.cancellation_reason or "Sklada kabul edildi",
                })
            for ex in exchanges_all[:4]:
                recent_ops.append({
                    "date": ex.exchange_date,
                    "type": "Çalyşyk (Trade-in)",
                    "doc": ex.exchange_number,
                    "amount": f"Goşmaça töleg: {money_str(ex.price_difference)} {ex.currency}",
                    "info": f"IMEI {ex.old_imei or '—'} → {ex.new_imei or '—'}",
                })
            recent_ops.sort(key=lambda x: x["date"] or datetime.min, reverse=True)

            session.commit()

        return {
            "range_start": range_start,
            "range_end": range_end,
            "balances": balances,
            "debts": debts,
            "profit_period": profit_period["by_currency"],
            "sales_today": sales_today,
            "sales_period": sales_period,
            "pur_period_usd": pur_usd,
            "pur_period_tmt": pur_tmt,
            "exchanges_count": exchanges_in_period,
            "new_phones": new_phones,
            "used_phones": used_phones,
            "accessories": inv["total_accessories"],
            "chart_labels": chart_labels,
            "chart_purchases": [b["purchases_bar"] for b in buckets],
            "chart_sales": [b["sales_bar"] for b in buckets],
            "chart_buckets": buckets,
            "recent_ops": recent_ops[:10],
        }

    def _header(self, stats: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)

        title = QLabel("Hoş geldiňiz!")
        title.setObjectName("pageTitle")

        today_cnt = stats["sales_today"]["active_receipts_count"]
        today_u = stats["sales_today"]["by_currency"]["USD"]["revenue"]
        today_t = stats["sales_today"]["by_currency"]["TMT"]["revenue"]
        sub = QLabel(
            f"Şu günki çekler: <b>{today_cnt}</b> "
            f"(Şu günki girdeji: <b>${today_u:,.2f} USD</b> / <b>{today_t:,.2f} TMT</b>)"
        )
        sub.setObjectName("mutedText")

        col.addWidget(title)
        col.addWidget(sub)
        row.addLayout(col, 1)

        r_start = stats["range_start"]
        r_end = stats["range_end"]
        date_text = f"📅  {r_start:%d.%m.%Y} – {r_end:%d.%m.%Y}"

        pill = QLabel(date_text)
        pill.setObjectName("datePill")
        row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh_btn = QPushButton("↻  Täzele")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh_data)
        row.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)

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
            f"<b>{product.name}</b> harydy gutaryp barýar: "
            f"skladda {product.stock_quantity} sany "
            f"(iň azy: {product.min_stock_quantity} sany)"
        )
        text.setObjectName("alertText")
        row.addWidget(text, 1)

        action = QPushButton("Alyş et")
        action.setObjectName("linkBtn")
        action.setCursor(Qt.CursorShape.PointingHandCursor)
        action.clicked.connect(lambda: self.navigateRequested.emit("Alyşlar"))

        close = QPushButton("✕")
        close.setObjectName("alertClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(box.hide)

        row.addWidget(action)
        row.addWidget(close)

        return box

    def _stat_row(self, stats: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        period_label, _chart_title = RANGE_CONFIG[self.current_range]

        sm_u = stats["sales_period"]["by_currency"]["USD"]["revenue"]
        sm_t = stats["sales_period"]["by_currency"]["TMT"]["revenue"]
        sales_val = f"${sm_u:,.2f} / {sm_t:,.0f} m."

        ex_cnt = stats["exchanges_count"]
        canc_cnt = stats["sales_period"]["cancelled_receipts_count"]

        pm_u = stats["pur_period_usd"]
        pm_t = stats["pur_period_tmt"]
        pur_val = f"${pm_u:,.2f} / {pm_t:,.0f} m."

        rec_cnt = str(stats["sales_period"]["active_receipts_count"])
        units_sold = stats["sales_period"]["units_sold"]

        data = [
            (f"Satyşlar ({period_label})", sales_val, self.current_range, True, theme.ACCENT, "🧾"),
            (f"Çalyşyk / Ýatyrma ({period_label})", f"{ex_cnt} çal. / {canc_cnt} ýat.", self.current_range, True, theme.NAVY, "↩"),
            (f"Alyşlar ({period_label})", pur_val, self.current_range, True, theme.TEAL, "📦"),
            (f"Çekleriň sany ({period_label})", rec_cnt, f"{units_sold} sany", True, theme.BLUE, "🧮"),
        ]

        for i, d in enumerate(data):
            grid.addWidget(ColorStatCard(*d), 0, i)
            grid.setColumnStretch(i, 1)

        return grid

    def _kpi_row(self, stats: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        period_label, _chart_title = RANGE_CONFIG[self.current_range]
        prof_u = stats["profit_period"]["USD"]["gross_profit"]
        prof_t = stats["profit_period"]["TMT"]["gross_profit"]
        cash_u = stats["balances"]["usd_balance"]
        cash_t = stats["balances"]["tmt_balance"]

        data = [
            (f"Jemi peýda USD ({period_label})", f"{prof_u:,.2f} USD", "COGS", prof_u >= 0, "#E8F1FF", "📈"),
            (f"Jemi peýda TMT ({period_label})", f"{prof_t:,.2f} TMT", "COGS", prof_t >= 0, "#E3F6F1", "📈"),
            ("Kassa balansy USD", f"{cash_u:,.2f} USD", "Kassada", True, "#FDEBE7", "💵"),
            ("Kassa balansy TMT", f"{cash_t:,.2f} TMT", "Kassada", True, "#F0EAFE", "💵"),
        ]

        for i, d in enumerate(data):
            grid.addWidget(KpiCard(*d), 0, i)
            grid.setColumnStretch(i, 1)

        return grid

    def _debts_card(self, stats: dict) -> Card:
        card = Card(margins=(18, 14, 18, 14), spacing=8)
        head = QHBoxLayout()
        t = QLabel("Bergiler we borçlar (USD / TMT)")
        t.setObjectName("cardTitle")
        head.addWidget(t, 1)
        fin_btn = QPushButton("Maliýe bölümini aç →")
        fin_btn.setObjectName("linkBtn")
        fin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fin_btn.clicked.connect(lambda: self.navigateRequested.emit("Maliýe"))
        head.addWidget(fin_btn)
        card.body.addLayout(head)

        d = stats["debts"]
        row = QHBoxLayout()
        row.setSpacing(12)

        items = [
            (
                "Müşderileriň dükana bergisi",
                f"${d['customer_debts']['USD']:,.2f}  |  {d['customer_debts']['TMT']:,.2f} m.",
                "#FFF3E6",
                theme.ACCENT,
            ),
            (
                "Dükanyň üpjün edijilere bergisi",
                f"${d['supplier_payables']['USD']:,.2f}  |  {d['supplier_payables']['TMT']:,.2f} m.",
                "#FDECEA",
                theme.RED,
            ),
            (
                "Dükanyň müşderilere bergisi (ýatyrma)",
                f"${d['store_debts_to_customers']['USD']:,.2f}  |  {d['store_debts_to_customers']['TMT']:,.2f} m.",
                "#F0EAFE",
                "#7C3AED",
            ),
            (
                "Üpjün edijileriň dükana bergisi (ýatyrma)",
                f"${d['supplier_debts_to_store']['USD']:,.2f}  |  {d['supplier_debts_to_store']['TMT']:,.2f} m.",
                "#E8F1FF",
                theme.BLUE,
            ),
        ]

        for label, val, bg, color in items:
            box = QFrame()
            box.setStyleSheet(f"background:{bg}; border-radius:10px;")
            v = QVBoxLayout(box)
            v.setContentsMargins(12, 8, 12, 8)
            v.setSpacing(2)
            lbl = QLabel(label)
            lbl.setObjectName("mutedText")
            val_lbl = QLabel(val)
            val_lbl.setStyleSheet(f"font-size:11pt; font-weight:700; color:{color};")
            v.addWidget(lbl)
            v.addWidget(val_lbl)
            row.addWidget(box, 1)

        card.body.addLayout(row)
        return card

    def _chart_card(self, stats: dict) -> Card:
        card = Card()
        head = QHBoxLayout()
        period_label, chart_title = RANGE_CONFIG[self.current_range]
        title = QLabel(chart_title)
        title.setObjectName("cardTitle")
        head.addWidget(title, 1)

        group = QButtonGroup(card)
        for name in ["1G", "1H", "1A", "6A", "1Ý"]:
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == self.current_range)
            b.clicked.connect(lambda _=False, key=name: self._set_time_range(key))
            group.addButton(b)
            head.addWidget(b)
        card.body.addLayout(head)

        sm_u = stats["sales_period"]["by_currency"]["USD"]["revenue"]
        sm_t = stats["sales_period"]["by_currency"]["TMT"]["revenue"]
        pm_u = stats["pur_period_usd"]
        pm_t = stats["pur_period_tmt"]
        pr_u = stats["profit_period"]["USD"]["gross_profit"]
        pr_t = stats["profit_period"]["TMT"]["gross_profit"]

        legend = QLabel(
            f"<span style='color:{theme.ACCENT_SOFT}'>●</span> Alyşlar ({period_label}): "
            f"<b>${pm_u:,.2f} / {pm_t:,.2f} TMT</b>"
            f"&nbsp;&nbsp;&nbsp;<span style='color:{theme.ACCENT}'>●</span> Satyşlar ({period_label}): "
            f"<b>${sm_u:,.2f} / {sm_t:,.2f} TMT</b>"
            f"&nbsp;&nbsp;&nbsp;<span style='color:{theme.GREEN}'>●</span> Peýda ({period_label}): "
            f"<b>${pr_u:,.2f} / {pr_t:,.2f} TMT</b>"
        )
        legend.setObjectName("mutedText")
        legend.setWordWrap(True)
        card.body.addWidget(legend)

        labels = stats["chart_labels"]
        c_pur = stats["chart_purchases"]
        c_sal = stats["chart_sales"]
        buckets = stats["chart_buckets"]
        max_val = max(max(c_pur, default=0.0), max(c_sal, default=0.0), 60.0)
        card.body.addWidget(
            BarChart(labels, c_pur, c_sal, y_max=max_val, buckets_meta=buckets),
            1,
        )
        return card

    def _side_card(self, stats: dict) -> Card:
        card = Card()
        t = QLabel("Sklad häzir")
        t.setObjectName("cardTitle")
        card.body.addWidget(t)

        row = QHBoxLayout()
        row.setSpacing(10)
        for label, value, tint in [
            ("Täze telefonlar", str(stats["new_phones"]), "#E8F1FF"),
            ("B/U telefonlar", str(stats["used_phones"]), "#E3F6F1"),
            ("Aksessuarlar", str(stats["accessories"]), "#FDEBE7"),
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
        h = QLabel("Skladda az galanlar")
        h.setStyleSheet("font-weight:700;")
        head.addWidget(h, 1)
        all_btn = QPushButton("Ählisi")
        all_btn.setObjectName("linkBtn")
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.clicked.connect(lambda: self.navigateRequested.emit("Harytlar we sklad"))
        head.addWidget(all_btn)
        card.body.addLayout(head)

        products = self.low_stock_products

        if products:
            for product in products[:6]:
                r = QHBoxLayout()
                r.addWidget(QLabel(product.name), 1)

                badge = QLabel(f"{product.stock_quantity} sany")
                badge.setStyleSheet(
                    "background:#FDECEA; color:#B42318; border-radius:8px; "
                    "padding:2px 9px; font-size:8.5pt; font-weight:600;"
                )

                r.addWidget(badge)
                card.body.addLayout(r)
        else:
            empty = QLabel("Az galyndyly haryt ýok")
            empty.setObjectName("mutedText")
            card.body.addWidget(empty)
        card.body.addStretch()
        return card

    def _recent_operations_card(self, stats: dict) -> Card:
        card = Card(margins=(18, 14, 18, 14), spacing=10)
        head = QHBoxLayout()
        t = QLabel("Dükanyň soňky amallary")
        t.setObjectName("cardTitle")
        head.addWidget(t, 1)
        rep_btn = QPushButton("Ähli hasabatlar →")
        rep_btn.setObjectName("linkBtn")
        rep_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rep_btn.clicked.connect(lambda: self.navigateRequested.emit("Hasabatlar"))
        head.addWidget(rep_btn)
        card.body.addLayout(head)

        ops = stats["recent_ops"]
        table = QTableWidget(len(ops), 5)
        table.setHorizontalHeaderLabels(["Sene", "Amal görnüşi", "Resminama", "Jemi", "Jikme-jik"])
        configure_table(table)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(210)
        table.setMaximumHeight(260)

        for i, op in enumerate(ops):
            d_str = op["date"].strftime("%d.%m.%Y %H:%M") if op["date"] else "—"
            vals = [d_str, op["type"], op["doc"], op["amount"], op["info"]]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (1, 2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, c, cell)

        card.body.addWidget(table)
        return card
