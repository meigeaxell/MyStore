import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
from app.repositories.product_repository import get_low_stock_products_detailed
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
    configure_dialog_buttons,
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

TIMELINE_ORDER = ["year", "month", "week", "day", "hour"]

# (короткий бейдж карточек, подпись периода, кнопка-метка уровня)
TIMELINE_META = {
    "hour": ("1G", "günlük", "Sagatlar"),
    "day": ("1A", "aýlyk", "Günler"),
    "week": ("12H", "hepdelik", "Hepdeler"),
    "month": ("1Ý", "ýyllyk", "Aýlar"),
    "year": ("5Ý", "5 ýyllyk", "Ýyllar"),
}

CHART_ITEM_FILTERS = [
    ("all", "Ählisi"),
    ("imei", "IMEI"),
    ("piece", "Ştuk"),
]


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, (total % 12) + 1


def _format_low_stock_label(item: dict) -> str:
    bm = " / ".join(filter(None, [item.get("brand", ""), item.get("model", "")]))
    meta = " • ".join(p for p in (item.get("category", ""), bm) if p)
    return f"{item['name']} ({meta})" if meta else item["name"]


class StockValuationByCategoryDialog(QDialog):
    """Интерактивная разбивка общей стоимости склада по категориям."""

    def __init__(self, stock_val: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sklad bahasy — kategoriýalar boýunça")
        self.setMinimumSize(860, 480)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Kategoriýalar boýunça sklad jemi bahasy")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        rate = stock_val.get("exchange_rate", Decimal("19.5000"))
        summary = QLabel(
            f"Jemi sklad bahasy (kurs {rate:.2f}): "
            f"<b>${money_str(stock_val['total_in_usd'])} USD</b>  •  "
            f"<b>{money_str(stock_val['total_in_tmt'])} TMT</b>   |   "
            f"Enjam (IMEI): <b>{stock_val['devices_count']}</b>  •  "
            f"Aksessuar (sany): <b>{stock_val['accessories_count']}</b>"
        )
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        root.addWidget(summary)

        rows = stock_val.get("by_category") or []
        table = QTableWidget(len(rows), 8)
        table.setHorizontalHeaderLabels([
            "Kategoriýa",
            "Görnüş",
            "IMEI enjam",
            "Ştuk (sany)",
            "USD baha",
            "TMT baha",
            "Jemi ($ USD)",
            "Jemi (TMT)",
        ])
        configure_table(table, stretch_col=0, row_height=42)
        for col, width in ((1, 75), (2, 95), (3, 95), (4, 105), (5, 110), (6, 115), (7, 135)):
            table.setColumnWidth(col, width)

        for r, entry in enumerate(rows):
            vals = [
                entry["category_name"],
                str(entry["products_count"]),
                str(entry["devices_count"]),
                str(entry["accessories_count"]),
                f"${money_str(entry['usd_native'])}",
                f"{money_str(entry['tmt_native'])} m.",
                f"${money_str(entry['total_in_usd'])}",
                f"{money_str(entry['total_in_tmt'])} m.",
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c >= 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c in (6, 7):
                    cell.setForeground(QColor(theme.BLUE))
                table.setItem(r, c, cell)
        root.addWidget(table, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = make_button("Ýap", "primary")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)
        configure_dialog_buttons(self, close_btn, close_btn)


class LowStockDialog(QDialog):
    """Интерактивное окно всех товаров с низким остатком (название, категория, бренд/модель)."""

    def __init__(self, low_stock_items: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.navigate_target: str | None = None
        self.setWindowTitle(f"Skladda az galan harytlar ({len(low_stock_items)})")
        self.setMinimumSize(820, 460)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(f"Az galyndyly harytlar ({len(low_stock_items)} görnüş)")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        sub = QLabel(
            "Aşakdaky harytlaryň galyndysy bellenen iň az çäkden pes ýa-da deň. "
            "Üstüni ýetirmek üçin «Alyş et» düwmesine basyň."
        )
        sub.setObjectName("mutedText")
        sub.setWordWrap(True)
        root.addWidget(sub)

        table = QTableWidget(len(low_stock_items), 6)
        table.setHorizontalHeaderLabels([
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Skladda",
            "Iň az galyndy",
            "Ýetmeýän",
        ])
        configure_table(table, stretch_col=[0, 2], row_height=42)
        for col, width in ((1, 130), (3, 100), (4, 125), (5, 105)):
            table.setColumnWidth(col, width)

        for r, item in enumerate(low_stock_items):
            bm = " / ".join(filter(None, [item.get("brand", ""), item.get("model", "")])) or "—"
            vals = [
                item["name"],
                item.get("category", "—"),
                bm,
                f"{item['stock_quantity']} sany",
                f"{item['min_stock_quantity']} sany",
                f"+{item['deficit']} sany" if item["deficit"] > 0 else "Çäk boýunça",
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c >= 3:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    cell.setForeground(
                        QColor(theme.RED if item["stock_quantity"] == 0 else theme.ACCENT)
                    )
                table.setItem(r, c, cell)
        root.addWidget(table, 1)

        footer = QHBoxLayout()
        stock_btn = make_button("Harytlar we sklad →")
        stock_btn.clicked.connect(lambda: self._go("Harytlar we sklad"))
        footer.addWidget(stock_btn)
        footer.addStretch()
        buy_btn = make_button("Alyş et →", "primary")
        buy_btn.clicked.connect(lambda: self._go("Alyşlar"))
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(buy_btn)
        footer.addWidget(close_btn)
        root.addLayout(footer)
        configure_dialog_buttons(self, buy_btn, close_btn)

    def _go(self, page_title: str) -> None:
        self.navigate_target = page_title
        self.accept()


class DashboardPage(QScrollArea):
    """Esasy panel MobileStore — 1 ekrana sygýan ykjam görnüş,
    dinamiki taýmlaýn zummy (Sagatlar ↔ Günler ↔ Hepdeler ↔ Aýlar ↔ Ýyllar)."""

    navigateRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.timeline_level = "day"
        self.focus_date = date.today()
        self.chart_item_filter = "all"
        self.low_stock_products: list[dict] = []
        self._last_stock_val: dict = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        self.content = QWidget()
        self.content.setObjectName("page")
        self.root_layout = QVBoxLayout(self.content)
        self.root_layout.setContentsMargins(20, 10, 20, 12)
        self.root_layout.setSpacing(9)
        self.setWidget(self.content)

    def _zoom_timeline(self, delta: int, anchor_date: date | None = None) -> None:
        """Переключает уровень детализации таймлайна при приближении (+1) / отдалении (-1)."""
        idx = TIMELINE_ORDER.index(self.timeline_level)
        new_idx = max(0, min(len(TIMELINE_ORDER) - 1, idx + delta))
        if new_idx == idx:
            return
        today = date.today()
        if delta > 0 and isinstance(anchor_date, date):
            self.focus_date = min(anchor_date, today)
        self.timeline_level = TIMELINE_ORDER[new_idx]
        self.refresh_data()

    def _pan_timeline(self, step: int) -> None:
        """Сдвигает фокусную дату назад (-1) или вперёд (+1) в текущем уровне таймлайна."""
        if step == 0:
            return
        today = date.today()
        fd = self.focus_date
        lvl = self.timeline_level
        if lvl == "hour":
            new_fd = fd + timedelta(days=step)
        elif lvl == "day":
            ny, nm = _shift_month(fd.year, fd.month, step)
            last_d = calendar.monthrange(ny, nm)[1]
            new_fd = date(ny, nm, min(fd.day, last_d))
        elif lvl == "week":
            new_fd = fd + timedelta(weeks=4 * step)
        else:
            ny = max(2000, fd.year + step)
            last_d = calendar.monthrange(ny, fd.month)[1]
            new_fd = date(ny, fd.month, min(fd.day, last_d))

        new_fd = min(new_fd, today)
        if new_fd != self.focus_date:
            self.focus_date = new_fd
            self.refresh_data()

    def _reset_timeline_today(self) -> None:
        today = date.today()
        if self.focus_date != today:
            self.focus_date = today
            self.refresh_data()
        elif self.timeline_level != "day":
            self.timeline_level = "day"
            self.refresh_data()

    def _can_pan_forward(self) -> bool:
        today = date.today()
        lvl = self.timeline_level
        fd = self.focus_date
        if lvl == "hour":
            return fd < today
        if lvl == "day":
            return (fd.year, fd.month) < (today.year, today.month)
        if lvl == "week":
            cur_mon = fd - timedelta(days=fd.weekday())
            today_mon = today - timedelta(days=today.weekday())
            return cur_mon < today_mon
        return fd.year < today.year

    def _set_chart_item_filter(self, filter_key: str) -> None:
        valid = {k for k, _ in CHART_ITEM_FILTERS}
        if filter_key in valid and filter_key != self.chart_item_filter:
            self.chart_item_filter = filter_key
            self.refresh_data()

    def _open_stock_valuation_dialog(self) -> None:
        if not self._last_stock_val:
            return
        dlg = StockValuationByCategoryDialog(self._last_stock_val, self)
        dlg.exec()

    def _open_low_stock_dialog(self) -> None:
        if not self.low_stock_products:
            return
        dlg = LowStockDialog(self.low_stock_products, self)
        dlg.exec()
        if dlg.navigate_target:
            self.navigateRequested.emit(dlg.navigate_target)

    def refresh_data(self) -> None:
        self._clear_layout(self.root_layout)

        self.low_stock_products = get_low_stock_products_detailed()
        stats = self._query_dashboard_stats()
        self._last_stock_val = stats["stock_val"]

        self.root_layout.addLayout(self._header(stats))
        if self.low_stock_products:
            self.root_layout.addWidget(self._alert())
        self.root_layout.addLayout(self._stat_row(stats))
        self.root_layout.addLayout(self._kpi_row(stats))
        self.root_layout.addWidget(self._debts_card(stats))

        lower = QHBoxLayout()
        lower.setSpacing(14)
        lower.addWidget(self._chart_card(stats), 3)
        lower.addWidget(self._side_card(stats), 2)
        self.root_layout.addLayout(lower, 1)

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
        focus: date,
    ) -> tuple[datetime, datetime, list[str], list[dict], callable, str]:
        """Создаёт временные интервалы (корзины), функцию сопоставления даты и заголовок
        для активного уровня таймлайна (hour / day / week / month / year)."""
        lvl = self.timeline_level
        today = date.today()

        if lvl == "hour":
            start_dt = datetime.combine(focus, time.min)
            end_dt = datetime.combine(focus, time.max)
            labels = [f"{h:02d}:00" for h in range(24)]
            day_tag = "Şu gün" if focus == today else f"{WEEKDAY_SHORT[focus.weekday()]}"
            buckets = [
                self._empty_bucket(
                    f"{day_tag} ({focus:%d.%m.%Y}), {h:02d}:00–{h + 1:02d}:00",
                    focus_date=focus,
                )
                for h in range(24)
            ]

            def matcher(dt: datetime) -> int | None:
                return dt.hour if dt.date() == focus else None

            chart_title = f"Sagatlar boýunça • {focus:%d.%m.%Y}"
            return start_dt, end_dt, labels, buckets, matcher, chart_title

        if lvl == "day":
            days_in_month = calendar.monthrange(focus.year, focus.month)[1]
            start_day = focus.replace(day=1)
            end_day = focus.replace(day=days_in_month)
            start_dt = datetime.combine(start_day, time.min)
            end_dt = datetime.combine(end_day, time.max)
            labels = [f"{d:02d}" for d in range(1, days_in_month + 1)]
            buckets = []
            for d in range(1, days_in_month + 1):
                cur_d = date(focus.year, focus.month, d)
                buckets.append(
                    self._empty_bucket(
                        f"{WEEKDAY_SHORT[cur_d.weekday()]}, {cur_d:%d.%m.%Y}",
                        focus_date=cur_d,
                    )
                )

            def matcher(dt: datetime) -> int | None:
                if dt.year == focus.year and dt.month == focus.month:
                    return dt.day - 1
                return None

            chart_title = f"Günler boýunça • {MONTH_NAMES_FULL[focus.month - 1]} {focus.year}"
            return start_dt, end_dt, labels, buckets, matcher, chart_title

        if lvl == "week":
            # 12 недель (Пн–Вс), заканчивая неделей focus
            end_mon = focus - timedelta(days=focus.weekday())
            week_starts = [end_mon - timedelta(weeks=11 - i) for i in range(12)]
            start_day = week_starts[0]
            end_day = week_starts[-1] + timedelta(days=6)
            start_dt = datetime.combine(start_day, time.min)
            end_dt = datetime.combine(end_day, time.max)
            labels = [f"{ws:%d.%m}" for ws in week_starts]
            buckets = []
            for ws in week_starts:
                we = ws + timedelta(days=6)
                mid = min(we, today)
                buckets.append(
                    self._empty_bucket(
                        f"Hepde: {ws:%d.%m.%Y} – {we:%d.%m.%Y}",
                        focus_date=mid,
                    )
                )

            def matcher(dt: datetime) -> int | None:
                delta_days = (dt.date() - start_day).days
                if 0 <= delta_days < 12 * 7:
                    return delta_days // 7
                return None

            chart_title = f"Hepdeler boýunça • {start_day:%d.%m} – {end_day:%d.%m.%Y}"
            return start_dt, end_dt, labels, buckets, matcher, chart_title

        if lvl == "month":
            year = focus.year
            start_dt = datetime.combine(date(year, 1, 1), time.min)
            end_dt = datetime.combine(date(year, 12, 31), time.max)
            labels = list(MONTH_NAMES_SHORT)
            buckets = []
            for m in range(1, 13):
                last_d = calendar.monthrange(year, m)[1]
                cur_d = min(date(year, m, min(focus.day, last_d)), today)
                buckets.append(
                    self._empty_bucket(
                        f"{MONTH_NAMES_FULL[m - 1]} {year}",
                        focus_date=cur_d,
                    )
                )

            def matcher(dt: datetime) -> int | None:
                return (dt.month - 1) if dt.year == year else None

            chart_title = f"Aýlar boýunça • {year}"
            return start_dt, end_dt, labels, buckets, matcher, chart_title

        # Уровень "year": 5 лет, заканчивая годом focus
        end_y = focus.year
        years = [end_y - 4 + i for i in range(5)]
        start_dt = datetime.combine(date(years[0], 1, 1), time.min)
        end_dt = datetime.combine(date(years[-1], 12, 31), time.max)
        y_to_idx = {y: i for i, y in enumerate(years)}
        labels = [str(y) for y in years]
        buckets = []
        for y in years:
            last_d = calendar.monthrange(y, focus.month)[1]
            cur_d = min(date(y, focus.month, min(focus.day, last_d)), today)
            buckets.append(self._empty_bucket(f"{y} ýyl", focus_date=cur_d))

        def matcher(dt: datetime) -> int | None:
            return y_to_idx.get(dt.year)

        chart_title = f"Ýyllar boýunça • {years[0]}–{years[-1]}"
        return start_dt, end_dt, labels, buckets, matcher, chart_title

    @staticmethod
    def _empty_bucket(title: str, focus_date: date | None = None) -> dict:
        return {
            "title": title,
            "focus_date": focus_date,
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

        range_start, range_end, chart_labels, buckets, matcher, chart_title = (
            self._build_buckets_for_range(self.focus_date)
        )

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
            "chart_title": chart_title,
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
        box = ClickableCard(margins=(12, 6, 8, 6), spacing=0)
        box.setObjectName("alert")
        box.setStyleSheet(
            "QFrame#alert { background: #FDECEA; border: 1px solid #F9CFCB; border-radius: 9px; }"
            "QFrame#alert:hover { background: #FBDAD6; border: 1px solid #E5484D; }"
        )

        if not self.low_stock_products:
            box.hide()
            return box

        first = self.low_stock_products[0]
        extra = len(self.low_stock_products) - 1
        extra_str = f"  (+{extra} başga haryt)" if extra > 0 else ""

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        text = QLabel(
            f"⚠ <b>{_format_low_stock_label(first)}</b> gutaryp barýar: "
            f"skladda <b>{first['stock_quantity']} sany</b> (iň azy: {first['min_stock_quantity']}){extra_str}"
        )
        text.setObjectName("alertText")
        row.addWidget(text, 1)

        view_btn = make_button("Ählisini gör →", "link")
        view_btn.clicked.connect(self._open_low_stock_dialog)

        action = make_button("Alyş et", "link")
        action.clicked.connect(lambda: self.navigateRequested.emit("Alyşlar"))

        close = make_button("✕")
        close.setObjectName("alertClose")
        close.clicked.connect(box.hide)

        row.addWidget(view_btn)
        row.addWidget(action)
        row.addWidget(close)
        box.body.addLayout(row)
        box.clicked.connect(self._open_low_stock_dialog)
        return box

    def _stat_row(self, stats: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)

        badge_code, period_label, _gran_name = TIMELINE_META[self.timeline_level]

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
            (f"Satyşlar ({period_label})", sales_val, badge_code, True, theme.ACCENT, "🧾", False),
            ("Çalyşyk / Ýatyrma", f"{ex_cnt} çal. / {canc_cnt} ýat.", badge_code, True, theme.NAVY, "↩", False),
            (f"Alyşlar ({period_label})", pur_val, badge_code, True, theme.TEAL, "📦", False),
            ("Sklad jemi baha →", stock_val_text, stock_units_badge, True, theme.BLUE, "🏪", True),
        ]

        for i, (*args, is_clickable) in enumerate(data):
            card_w = ColorStatCard(*args, clickable=is_clickable)
            if is_clickable:
                card_w.clicked.connect(self._open_stock_valuation_dialog)
            grid.addWidget(card_w, 0, i)
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
        card = Card(margins=(14, 8, 14, 8), spacing=2)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(1)

        t = QLabel(title)
        t.setObjectName("mutedText")
        v = QLabel(primary_line)
        v.setStyleSheet(f"font-size: 13.5pt; font-weight: 800; color: {value_color};")
        col.addWidget(t)
        col.addWidget(v)
        top.addLayout(col, 1)

        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        icon.setStyleSheet(f"background:{tint}; border-radius:9px; font-size:13pt;")
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(top)

        sub = QLabel(secondary_line)
        sub.setObjectName("mutedText")
        sub.setStyleSheet(f"font-size: 8.5pt; color: {theme.MUTED};")
        card.body.addWidget(sub)
        return card

    def _kpi_row(self, stats: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)

        _badge_code, period_label, _gran_name = TIMELINE_META[self.timeline_level]
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
        card = Card(margins=(14, 8, 14, 8), spacing=6)
        head = QHBoxLayout()
        t = QLabel("Simurg, Sklad we Üpjün edijiler")
        t.setStyleSheet(f"font-size: 10.5pt; font-weight: 700; color: {theme.NAVY};")
        head.addWidget(t, 1)
        fin_btn = make_button("Maliýe bölümini aç →", "link")
        fin_btn.clicked.connect(lambda: self.navigateRequested.emit("Maliýe"))
        head.addWidget(fin_btn)
        card.body.addLayout(head)

        d = stats["debts"]
        sim = stats["simurg"]
        sv = stats["stock_val"]

        row = QHBoxLayout()
        row.setSpacing(10)

        # 1. Кликабельный блок Simurg bergisi
        sim_box = ClickableCard(margins=(12, 8, 12, 8), spacing=2)
        sim_box.setStyleSheet(
            f"QFrame#clickableCard {{ background: #FFF8F1; border: 1.5px solid #FDBA74; border-radius: 10px; }}"
            f"QFrame#clickableCard:hover {{ background: {theme.ACCENT_BG}; border: 1.5px solid {theme.ACCENT}; }}"
        )
        sim_box.clicked.connect(lambda: self.navigateRequested.emit("Simurg"))
        sim_title = QLabel(f"Simurg bergisi ({sim['total_items_count']} enjam) →")
        sim_title.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.8pt; font-weight: 600;")
        sim_val = QLabel(
            f"${sim['total_debt']['USD']:,.2f} USD  |  {sim['total_debt']['TMT']:,.2f} TMT"
        )
        sim_val.setStyleSheet(f"font-size: 11pt; font-weight: 800; color: {theme.ACCENT};")
        sim_ready = QLabel(
            f"✔ Taýýar (≥5g): <b>{sim['ready_amount']['TMT']:,.2f} TMT</b>"
            + (f" / <b>${sim['ready_amount']['USD']:,.2f}</b>" if sim["ready_amount"]["USD"] > 0 else "")
            + f"  •  {sim['ready_items_count']} taýýar"
        )
        sim_ready.setStyleSheet(f"font-size: 8.5pt; color: {theme.GREEN};")
        sim_box.body.addWidget(sim_title)
        sim_box.body.addWidget(sim_val)
        sim_box.body.addWidget(sim_ready)
        row.addWidget(sim_box, 2)

        # 2. Üpjün edijilere bergi
        sup_box = QFrame()
        sup_box.setStyleSheet("background: #FDECEA; border-radius: 10px;")
        sv_l = QVBoxLayout(sup_box)
        sv_l.setContentsMargins(12, 8, 12, 8)
        sv_l.setSpacing(2)
        sup_t = QLabel("Dükanyň üpjün edijilere bergisi")
        sup_t.setObjectName("mutedText")
        sup_v = QLabel(
            f"${d['supplier_payables']['USD']:,.2f}  |  {d['supplier_payables']['TMT']:,.2f} m."
        )
        sup_v.setStyleSheet(f"font-size: 11pt; font-weight: 700; color: {theme.RED};")
        sup_s = QLabel("Alyşlar boýunça tölenmedik galyndy")
        sup_s.setStyleSheet(f"font-size: 8.3pt; color: {theme.MUTED};")
        sv_l.addWidget(sup_t)
        sv_l.addWidget(sup_v)
        sv_l.addWidget(sup_s)
        row.addWidget(sup_box, 1)

        # 3. Интерактивный блок Sklad jemi baha -> разбивка по категориям
        stk_box = ClickableCard(margins=(12, 8, 12, 8), spacing=2)
        stk_box.setStyleSheet(
            f"QFrame#clickableCard {{ background: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 10px; }}"
            f"QFrame#clickableCard:hover {{ background: #DBEAFE; border: 1.5px solid {theme.BLUE}; }}"
        )
        stk_box.setToolTip("Kategoriýalar boýunça sklad bahasyny görmek üçin basyň")
        stk_box.clicked.connect(self._open_stock_valuation_dialog)
        stk_t = QLabel("Sklad jemi baha (kategoriýalar →)")
        stk_t.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.8pt; font-weight: 600;")
        stk_v = QLabel(
            f"${sv['total_in_usd']:,.2f} USD  |  {sv['total_in_tmt']:,.2f} TMT"
        )
        stk_v.setStyleSheet(f"font-size: 11pt; font-weight: 700; color: {theme.BLUE};")
        stk_s = QLabel(
            f"{sv['devices_count']} enjam • {sv['accessories_count']} aksessuar (jemi {sv['total_units']} sany)"
        )
        stk_s.setStyleSheet(f"font-size: 8.3pt; color: {theme.MUTED};")
        stk_box.body.addWidget(stk_t)
        stk_box.body.addWidget(stk_v)
        stk_box.body.addWidget(stk_s)
        row.addWidget(stk_box, 1)

        card.body.addLayout(row)
        return card

    def _chart_card(self, stats: dict) -> Card:
        card = Card(margins=(16, 12, 16, 12), spacing=8)
        head = QHBoxLayout()
        head.setSpacing(5)
        _badge_code, period_label, gran_label = TIMELINE_META[self.timeline_level]
        title = QLabel(stats["chart_title"])
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
        sep.setFixedHeight(18)
        head.addWidget(sep)

        # Семантический зум и навигация по таймлайнам: ◀  −  [Günler]  +  ▶
        lvl_idx = TIMELINE_ORDER.index(self.timeline_level)
        can_zoom_out = lvl_idx > 0
        can_zoom_in = lvl_idx < len(TIMELINE_ORDER) - 1
        can_forward = self._can_pan_forward()

        prev_btn = QPushButton("◀")
        prev_btn.setObjectName("chip")
        prev_btn.setFixedWidth(28)
        prev_btn.setStyleSheet("QPushButton#chip { padding: 4px 0px; font-weight: 700; }")
        prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prev_btn.setToolTip("Öňki döwür")
        prev_btn.clicked.connect(lambda: self._pan_timeline(-1))

        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setObjectName("chip")
        zoom_out_btn.setFixedWidth(30)
        zoom_out_btn.setEnabled(can_zoom_out)
        zoom_out_btn.setStyleSheet("QPushButton#chip { padding: 4px 0px; font-weight: 700; }")
        zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_out_btn.setToolTip("Uzaklaşdyr (Sagatlar → Günler → Hepdeler → Aýlar → Ýyllar)")
        zoom_out_btn.clicked.connect(lambda: self._zoom_timeline(-1))

        level_btn = QPushButton(gran_label)
        level_btn.setObjectName("chip")
        level_btn.setCheckable(True)
        level_btn.setChecked(True)
        level_btn.setMinimumWidth(78)
        level_btn.setStyleSheet("QPushButton#chip { padding: 4px 10px; font-weight: 700; }")
        level_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        level_btn.setToolTip("Häzirki taýmlaýn • Basyň — şu güne gaýtar")
        level_btn.clicked.connect(self._reset_timeline_today)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setObjectName("chip")
        zoom_in_btn.setFixedWidth(30)
        zoom_in_btn.setEnabled(can_zoom_in)
        zoom_in_btn.setStyleSheet("QPushButton#chip { padding: 4px 0px; font-weight: 700; }")
        zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_in_btn.setToolTip("Ýakynlaşdyr (Ýyllar → Aýlar → Hepdeler → Günler → Sagatlar)")
        zoom_in_btn.clicked.connect(lambda: self._zoom_timeline(1))

        next_btn = QPushButton("▶")
        next_btn.setObjectName("chip")
        next_btn.setFixedWidth(28)
        next_btn.setEnabled(can_forward)
        next_btn.setStyleSheet("QPushButton#chip { padding: 4px 0px; font-weight: 700; }")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setToolTip("Indiki döwür")
        next_btn.clicked.connect(lambda: self._pan_timeline(1))

        head.addWidget(prev_btn)
        head.addWidget(zoom_out_btn)
        head.addWidget(level_btn)
        head.addWidget(zoom_in_btn)
        head.addWidget(next_btn)
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
        max_val = max(max(c_pur, default=0.0), max(c_sal, default=0.0), 10.0)
        chart = BarChart(
            labels,
            c_pur,
            c_sal,
            y_max=max_val,
            buckets_meta=buckets,
            timeline_mode=True,
            can_zoom_in=can_zoom_in,
            can_zoom_out=can_zoom_out,
        )
        chart.timelineZoomRequested.connect(self._zoom_timeline)
        chart.timelinePanRequested.connect(self._pan_timeline)
        card.body.addWidget(chart, 1)
        return card

    def _side_card(self, stats: dict) -> Card:
        card = Card(margins=(16, 12, 16, 12), spacing=8)
        t = QLabel("Sklad häzir")
        t.setObjectName("cardTitle")
        card.body.addWidget(t)

        row = QHBoxLayout()
        row.setSpacing(8)
        for label, value, tint in [
            ("Täze telefonlar", str(stats["new_phones"]), "#E8F1FF"),
            ("B/U telefonlar", str(stats["used_phones"]), "#E3F6F1"),
            ("Aksessuarlar", str(stats["accessories"]), "#FDEBE7"),
        ]:
            box = QFrame()
            box.setStyleSheet(f"background:{tint}; border-radius:10px;")
            v = QVBoxLayout(box)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(0)
            a = QLabel(label)
            a.setObjectName("mutedText")
            b = QLabel(value)
            b.setStyleSheet("font-size:13.5pt; font-weight:700;")
            v.addWidget(a)
            v.addWidget(b)
            row.addWidget(box, 1)
        card.body.addLayout(row)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.BORDER};")
        card.body.addWidget(line)

        head = QHBoxLayout()
        low_cnt = len(self.low_stock_products)
        h = QLabel(f"Skladda az galanlar ({low_cnt})")
        h.setStyleSheet("font-weight:700;")
        head.addWidget(h, 1)
        if low_cnt > 0:
            all_btn = make_button("Ählisini gör →", "link")
            all_btn.clicked.connect(self._open_low_stock_dialog)
            head.addWidget(all_btn)
        else:
            all_btn = make_button("Sklad →", "link")
            all_btn.clicked.connect(lambda: self.navigateRequested.emit("Harytlar we sklad"))
            head.addWidget(all_btn)
        card.body.addLayout(head)

        products = self.low_stock_products

        if products:
            for item in products[:4]:
                row_card = ClickableCard(margins=(8, 5, 8, 5), spacing=0)
                row_card.setStyleSheet(
                    "QFrame#clickableCard { background: #FAFBFC; border: 1px solid #EEF2F6; border-radius: 8px; }"
                    "QFrame#clickableCard:hover { background: #FFF3E6; border: 1px solid #FDBA74; }"
                )
                row_card.clicked.connect(self._open_low_stock_dialog)
                r = QHBoxLayout()
                r.setContentsMargins(0, 0, 0, 0)
                r.setSpacing(6)

                info_col = QVBoxLayout()
                info_col.setSpacing(0)
                name_lbl = QLabel(item["name"])
                name_lbl.setStyleSheet("font-weight: 600; font-size: 9.2pt;")
                bm = " / ".join(filter(None, [item.get("brand", ""), item.get("model", "")]))
                sub_txt = " • ".join(p for p in (item.get("category", ""), bm) if p) or "—"
                sub_lbl = QLabel(sub_txt)
                sub_lbl.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.2pt;")
                info_col.addWidget(name_lbl)
                info_col.addWidget(sub_lbl)
                r.addLayout(info_col, 1)

                badge = QLabel(f"{item['stock_quantity']} / {item['min_stock_quantity']}")
                badge.setStyleSheet(
                    "background:#FDECEA; color:#B42318; border-radius:8px; "
                    "padding:2px 8px; font-size:8.3pt; font-weight:700;"
                )
                r.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
                row_card.body.addLayout(r)
                card.body.addWidget(row_card)
        else:
            empty = QLabel("Az galyndyly haryt ýok")
            empty.setObjectName("mutedText")
            card.body.addWidget(empty)
        card.body.addStretch()
        return card
