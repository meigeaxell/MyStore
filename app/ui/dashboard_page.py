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
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.stock_item import StockItem
from app.repositories.product_repository import get_low_stock_products
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.services.sales_service import _convert_currency
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.widgets import (
    BarChart,
    Card,
    ClickableCard,
    ColorStatCard,
    configure_table,
    make_button,
    money_str,
)

MONTH_NAMES_SHORT = ["Ýan", "Few", "Mar", "Apr", "Maý", "Iýun", "Iýul", "Awg", "Sen", "Okt", "Noý", "Dek"]
MONTH_NAMES_FULL = [
    "Ýanwar", "Fewral", "Mart", "Aprel", "Maý", "Iýun",
    "Iýul", "Awgust", "Sentýabr", "Oktýabr", "Noýabr", "Dekabr",
]
WEEKDAY_SHORT = ["Duş", "Siş", "Çar", "Pen", "Ann", "Şen", "Ýek"]

RANGE_CONFIG = {
    "1G": ("günlük", "Şu günki dinamika"),
    "1H": ("hepdelik", "7 günlük dinamika"),
    "1A": ("aýlyk", "Şu aýyň dinamikasy"),
    "6A": ("6 aýlyk", "6 aýlyk dinamika"),
    "1Ý": ("ýyllyk", "Ýyllyk dinamika"),
}

CHART_ITEM_FILTERS = [
    ("all", "Ählisi"),
    ("imei", "IMEI"),
    ("piece", "Ştuk"),
]


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
        self.chart_item_filter = "all"
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

    def _set_chart_item_filter(self, filter_key: str) -> None:
        valid = {k for k, _ in CHART_ITEM_FILTERS}
        if filter_key in valid and filter_key != self.chart_item_filter:
            self.chart_item_filter = filter_key
            self.refresh_data()

    def refresh_data(self) -> None:
        self._clear_layout(self.root_layout)

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
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
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
            rate = SettingsService.get_default_exchange_rate()
            balances = FinanceService.get_register_balances(session)
            combined_cash = FinanceService.get_combined_cash_totals(session, rate)
            debts = FinanceService.get_all_outstanding_balances(session)
            simurg = FinanceService.get_simurg_summary(session, include_paid=False)
            stock_val = ReportService.get_stock_valuation(session, rate)
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
            active_pur_ids: list[int] = []
            pur_by_id: dict[int, Purchase] = {}
            for p in purchases_all:
                if p.status == "active" and p.purchase_date and range_start <= p.purchase_date <= range_end:
                    amt = Decimal(str(p.total_amount))
                    if p.currency == "USD":
                        pur_usd += amt
                    elif p.currency == "TMT":
                        pur_tmt += amt
                    active_pur_ids.append(p.id)
                    pur_by_id[p.id] = p

            active_sale_ids: list[int] = []
            sale_by_id: dict[int, Sale] = {}
            for s in sales_all:
                if s.status != "cancelled" and s.sale_date and range_start <= s.sale_date <= range_end:
                    active_sale_ids.append(s.id)
                    sale_by_id[s.id] = s

            # Построчный расчёт диаграммы с учётом тумблера: Ählisi / IMEI / Ştuk
            phone_unit_ids = set(
                session.scalars(select(Product.id).where(Product.is_phone_unit.is_(True))).all()
            )
            chart_mode = self.chart_item_filter
            chart_pur_usd = Decimal("0.00")
            chart_pur_tmt = Decimal("0.00")
            chart_sal_usd = Decimal("0.00")
            chart_sal_tmt = Decimal("0.00")
            chart_prof_usd = Decimal("0.00")
            chart_prof_tmt = Decimal("0.00")

            if active_pur_ids:
                pur_items = session.scalars(
                    select(PurchaseItem).where(PurchaseItem.purchase_id.in_(active_pur_ids))
                ).all()
                pur_stock_counts: dict[tuple[int, int], int] = {}
                linked_sts = session.execute(
                    select(StockItem.purchase_id, StockItem.product_id)
                    .where(StockItem.purchase_id.in_(active_pur_ids))
                ).all()
                for pid_k, prod_k in linked_sts:
                    if pid_k is not None:
                        key = (int(pid_k), int(prod_k))
                        pur_stock_counts[key] = pur_stock_counts.get(key, 0) + 1

                # Отслеживаем остаток IMEI-единиц, если в одной закупке несколько строк с одним product_id
                remaining_imei_counts = dict(pur_stock_counts)
                for pi in pur_items:
                    pur = pur_by_id.get(pi.purchase_id)
                    if pur is None or pur.purchase_date is None:
                        continue
                    b_idx = matcher(pur.purchase_date)
                    if b_idx is None:
                        continue

                    qty_total = int(pi.quantity or 0)
                    if qty_total <= 0:
                        continue
                    if pi.product_id in phone_unit_ids:
                        imei_qty = qty_total
                    else:
                        key = (int(pi.purchase_id), int(pi.product_id))
                        avail_imei = remaining_imei_counts.get(key, 0)
                        imei_qty = min(qty_total, avail_imei)
                        if imei_qty > 0:
                            remaining_imei_counts[key] = avail_imei - imei_qty
                    piece_qty = max(0, qty_total - imei_qty)

                    if chart_mode == "imei":
                        eff_qty = imei_qty
                    elif chart_mode == "piece":
                        eff_qty = piece_qty
                    else:
                        eff_qty = qty_total

                    if eff_qty <= 0:
                        continue

                    line_amt = (Decimal(str(pi.unit_cost)) * eff_qty).quantize(Decimal("0.01"))
                    p_rate = Decimal(str(pur.exchange_rate or 19.5))
                    if pur.currency == "USD":
                        chart_pur_usd += line_amt
                        buckets[b_idx]["purchases_usd"] += line_amt
                        buckets[b_idx]["purchases_bar"] += float(line_amt * p_rate)
                    else:
                        chart_pur_tmt += line_amt
                        buckets[b_idx]["purchases_tmt"] += line_amt
                        buckets[b_idx]["purchases_bar"] += float(line_amt)

            if active_sale_ids:
                s_items = session.scalars(
                    select(SaleItem).where(SaleItem.sale_id.in_(active_sale_ids))
                ).all()
                bucket_receipt_sets: list[set[int]] = [set() for _ in buckets]
                for si in s_items:
                    sale = sale_by_id.get(si.sale_id)
                    if sale is None or sale.sale_date is None:
                        continue
                    b_idx = matcher(sale.sale_date)
                    if b_idx is None:
                        continue

                    is_imei_item = bool(
                        (si.imei or "").strip()
                        or si.stock_item_id is not None
                        or si.product_id in phone_unit_ids
                    )
                    if chart_mode == "imei" and not is_imei_item:
                        continue
                    if chart_mode == "piece" and is_imei_item:
                        continue

                    s_rate = Decimal(str(sale.exchange_rate or 19.5))
                    if s_rate <= 0:
                        s_rate = Decimal("19.5")
                    item_curr = (si.currency or sale.currency or "TMT").strip().upper()
                    sale_curr = (sale.currency or "TMT").strip().upper()
                    raw_line = (Decimal(str(si.unit_price)) * int(si.quantity or 1)) - Decimal(str(si.discount or 0))
                    raw_line = max(raw_line, Decimal("0.00"))
                    rev_in_sale_curr = _convert_currency(raw_line, item_curr, sale_curr, s_rate)

                    cost_curr = (si.cost_currency or sale_curr).strip().upper()
                    c_rate = Decimal(str(si.cost_exchange_rate or s_rate or 19.5))
                    if c_rate <= 0:
                        c_rate = s_rate
                    raw_cost = Decimal(str(si.unit_cost or 0)) * int(si.quantity or 1)
                    cost_in_sale_curr = _convert_currency(raw_cost, cost_curr, sale_curr, c_rate)
                    line_profit = (rev_in_sale_curr - cost_in_sale_curr).quantize(Decimal("0.01"))

                    bucket_receipt_sets[b_idx].add(sale.id)
                    if sale_curr == "USD":
                        chart_sal_usd += rev_in_sale_curr
                        chart_prof_usd += line_profit
                        buckets[b_idx]["sales_usd"] += rev_in_sale_curr
                        buckets[b_idx]["profit_usd"] += line_profit
                        buckets[b_idx]["sales_bar"] += float(rev_in_sale_curr * s_rate)
                    else:
                        chart_sal_tmt += rev_in_sale_curr
                        chart_prof_tmt += line_profit
                        buckets[b_idx]["sales_tmt"] += rev_in_sale_curr
                        buckets[b_idx]["profit_tmt"] += line_profit
                        buckets[b_idx]["sales_bar"] += float(rev_in_sale_curr)

                for idx_b, rset in enumerate(bucket_receipt_sets):
                    buckets[idx_b]["receipts_count"] = len(rset)

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
            "combined_cash": combined_cash,
            "debts": debts,
            "simurg": simurg,
            "stock_val": stock_val,
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
            "chart_totals": {
                "pur_usd": chart_pur_usd,
                "pur_tmt": chart_pur_tmt,
                "sal_usd": chart_sal_usd,
                "sal_tmt": chart_sal_tmt,
                "prof_usd": chart_prof_usd,
                "prof_tmt": chart_prof_tmt,
            },
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

        refresh_btn = make_button("↻  Täzele")
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

        action = make_button("Alyş et", "link")
        action.clicked.connect(lambda: self.navigateRequested.emit("Alyşlar"))

        close = make_button("✕")
        close.setObjectName("alertClose")
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

        sv = stats["stock_val"]
        stock_val_text = f"${sv['total_in_usd']:,.2f} / {sv['total_in_tmt']:,.0f} m."
        stock_units_badge = f"{sv['total_units']} sany"

        data = [
            (f"Satyşlar ({period_label})", sales_val, self.current_range, True, theme.ACCENT, "🧾"),
            ("Çalyşyk / Ýatyrma", f"{ex_cnt} çal. / {canc_cnt} ýat.", self.current_range, True, theme.NAVY, "↩"),
            (f"Alyşlar ({period_label})", pur_val, self.current_range, True, theme.TEAL, "📦"),
            ("Sklad jemi baha", stock_val_text, stock_units_badge, True, theme.BLUE, "🏪"),
        ]

        for i, d in enumerate(data):
            grid.addWidget(ColorStatCard(*d), 0, i)
            grid.setColumnStretch(i, 1)

        return grid

    def _build_combined_kpi(
        self,
        title: str,
        primary_line: str,
        secondary_line: str,
        tint: str,
        glyph: str,
        value_color: str,
    ) -> Card:
        card = Card(margins=(20, 16, 20, 14), spacing=6)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)

        t = QLabel(title)
        t.setObjectName("mutedText")
        v = QLabel(primary_line)
        v.setStyleSheet(f"font-size: 16pt; font-weight: 800; color: {value_color};")
        col.addWidget(t)
        col.addWidget(v)
        top.addLayout(col, 1)

        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(42, 42)
        icon.setStyleSheet(f"background:{tint}; border-radius:10px; font-size:15pt;")
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(top)

        sub = QLabel(secondary_line)
        sub.setObjectName("mutedText")
        sub.setStyleSheet(f"font-size: 9pt; color: {theme.MUTED};")
        card.body.addWidget(sub)
        return card

    def _kpi_row(self, stats: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        period_label, _chart_title = RANGE_CONFIG[self.current_range]
        prof_u = stats["profit_period"]["USD"]["gross_profit"]
        prof_t = stats["profit_period"]["TMT"]["gross_profit"]
        rate = stats["combined_cash"]["exchange_rate"]
        prof_total_tmt = (prof_t + prof_u * rate).quantize(Decimal("0.01"))
        prof_total_usd = (prof_u + (prof_t / rate)).quantize(Decimal("0.01"))

        cash_u = stats["balances"]["usd_balance"]
        cash_t = stats["balances"]["tmt_balance"]
        cash_total_tmt = stats["combined_cash"]["total_in_tmt"]
        cash_total_usd = stats["combined_cash"]["total_in_usd"]

        profit_card = self._build_combined_kpi(
            title=f"Jemi peýda ({period_label}) — USD / TMT",
            primary_line=f"${prof_u:,.2f} USD   |   {prof_t:,.2f} TMT",
            secondary_line=f"Umumy ekwiwalent (kurs {rate:.2f}):  <b>${prof_total_usd:,.2f} USD</b>  •  <b>{prof_total_tmt:,.2f} TMT</b>",
            tint="#E3F6F1",
            glyph="📈",
            value_color=theme.GREEN if prof_total_tmt >= 0 else theme.RED,
        )

        cash_card = self._build_combined_kpi(
            title="Kassa balansy — USD / TMT",
            primary_line=f"${cash_u:,.2f} USD   |   {cash_t:,.2f} TMT",
            secondary_line=f"Jemi kassa (kurs {rate:.2f}):  <b>${cash_total_usd:,.2f} USD</b>  •  <b>{cash_total_tmt:,.2f} TMT</b>",
            tint="#E8F1FF",
            glyph="💵",
            value_color=theme.NAVY,
        )

        grid.addWidget(profit_card, 0, 0)
        grid.addWidget(cash_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return grid

    def _debts_card(self, stats: dict) -> Card:
        card = Card(margins=(18, 14, 18, 14), spacing=10)
        head = QHBoxLayout()
        t = QLabel("Simurg, Sklad we Üpjün edijiler")
        t.setObjectName("cardTitle")
        head.addWidget(t, 1)
        fin_btn = make_button("Maliýe bölümini aç →", "link")
        fin_btn.clicked.connect(lambda: self.navigateRequested.emit("Maliýe"))
        head.addWidget(fin_btn)
        card.body.addLayout(head)

        d = stats["debts"]
        sim = stats["simurg"]
        sv = stats["stock_val"]

        row = QHBoxLayout()
        row.setSpacing(12)

        # 1. Кликабельный блок Simurg bergisi
        sim_box = ClickableCard(margins=(14, 10, 14, 10), spacing=3)
        sim_box.setStyleSheet(
            f"QFrame#clickableCard {{ background: #FFF8F1; border: 1.5px solid #FDBA74; border-radius: 10px; }}"
            f"QFrame#clickableCard:hover {{ background: {theme.ACCENT_BG}; border: 1.5px solid {theme.ACCENT}; }}"
        )
        sim_box.clicked.connect(lambda: self.navigateRequested.emit("Simurg"))
        sim_title = QLabel(f"Simurg bergisi ({sim['total_items_count']} enjam) →")
        sim_title.setStyleSheet(f"color: {theme.MUTED}; font-size: 9pt; font-weight: 600;")
        sim_val = QLabel(
            f"${sim['total_debt']['USD']:,.2f} USD  |  {sim['total_debt']['TMT']:,.2f} TMT"
        )
        sim_val.setStyleSheet(f"font-size: 11.5pt; font-weight: 800; color: {theme.ACCENT};")
        sim_ready = QLabel(
            f"✔ Taýýar (≥5g): <b>{sim['ready_amount']['TMT']:,.2f} TMT</b>"
            + (f" / <b>${sim['ready_amount']['USD']:,.2f}</b>" if sim["ready_amount"]["USD"] > 0 else "")
            + f"  •  {sim['ready_items_count']} taýýar"
        )
        sim_ready.setStyleSheet(f"font-size: 8.8pt; color: {theme.GREEN};")
        sim_box.body.addWidget(sim_title)
        sim_box.body.addWidget(sim_val)
        sim_box.body.addWidget(sim_ready)
        row.addWidget(sim_box, 2)

        # 2. Üpjün edijilere bergi
        sup_box = QFrame()
        sup_box.setStyleSheet("background: #FDECEA; border-radius: 10px;")
        sv_l = QVBoxLayout(sup_box)
        sv_l.setContentsMargins(14, 10, 14, 10)
        sv_l.setSpacing(3)
        sup_t = QLabel("Dükanyň üpjün edijilere bergisi")
        sup_t.setObjectName("mutedText")
        sup_v = QLabel(
            f"${d['supplier_payables']['USD']:,.2f}  |  {d['supplier_payables']['TMT']:,.2f} m."
        )
        sup_v.setStyleSheet(f"font-size: 11.5pt; font-weight: 700; color: {theme.RED};")
        sup_s = QLabel("Alyşlar boýunça tölenmedik galyndy")
        sup_s.setStyleSheet(f"font-size: 8.5pt; color: {theme.MUTED};")
        sv_l.addWidget(sup_t)
        sv_l.addWidget(sup_v)
        sv_l.addWidget(sup_s)
        row.addWidget(sup_box, 1)

        # 3. Sklad jemi baha
        stk_box = QFrame()
        stk_box.setStyleSheet("background: #EFF6FF; border-radius: 10px;")
        st_l = QVBoxLayout(stk_box)
        st_l.setContentsMargins(14, 10, 14, 10)
        st_l.setSpacing(3)
        stk_t = QLabel("Sklad jemi baha (USD / TMT)")
        stk_t.setObjectName("mutedText")
        stk_v = QLabel(
            f"${sv['total_in_usd']:,.2f} USD  |  {sv['total_in_tmt']:,.2f} TMT"
        )
        stk_v.setStyleSheet(f"font-size: 11.5pt; font-weight: 700; color: {theme.BLUE};")
        stk_s = QLabel(
            f"{sv['devices_count']} enjam • {sv['accessories_count']} aksessuar (jemi {sv['total_units']} sany)"
        )
        stk_s.setStyleSheet(f"font-size: 8.5pt; color: {theme.MUTED};")
        st_l.addWidget(stk_t)
        st_l.addWidget(stk_v)
        st_l.addWidget(stk_s)
        row.addWidget(stk_box, 1)

        card.body.addLayout(row)
        return card

    def _chart_card(self, stats: dict) -> Card:
        card = Card()
        head = QHBoxLayout()
        head.setSpacing(6)
        period_label, chart_title = RANGE_CONFIG[self.current_range]
        title = QLabel(chart_title)
        title.setObjectName("cardTitle")
        head.addWidget(title, 1)

        # Тумблер переключения: Ählisi / IMEI / Ştuk
        type_group = QButtonGroup(card)
        for key, label in CHART_ITEM_FILTERS:
            tb = QPushButton(label)
            tb.setObjectName("chip")
            tb.setCheckable(True)
            tb.setAutoDefault(False)
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            tb.setChecked(key == self.chart_item_filter)
            tb.clicked.connect(lambda _=False, k=key: self._set_chart_item_filter(k))
            type_group.addButton(tb)
            head.addWidget(tb)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        head.addWidget(sep)

        group = QButtonGroup(card)
        for name in ["1G", "1H", "1A", "6A", "1Ý"]:
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == self.current_range)
            b.clicked.connect(lambda _=False, key=name: self._set_time_range(key))
            group.addButton(b)
            head.addWidget(b)
        card.body.addLayout(head)

        ct = stats["chart_totals"]
        sm_u = ct["sal_usd"]
        sm_t = ct["sal_tmt"]
        pm_u = ct["pur_usd"]
        pm_t = ct["pur_tmt"]
        pr_u = ct["prof_usd"]
        pr_t = ct["prof_tmt"]
        filter_label = dict(CHART_ITEM_FILTERS).get(self.chart_item_filter, "Ählisi")

        legend = QLabel(
            f"<b>[{filter_label}]</b>&nbsp;&nbsp;"
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
        all_btn = make_button("Ählisi", "link")
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
        rep_btn = make_button("Ähli hasabatlar →", "link")
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
