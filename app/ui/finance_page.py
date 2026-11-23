from datetime import date, datetime, time
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import SessionLocal
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.purchase_page import PurchaseDetailsDialog
from app.ui.receipt_printer import export_shift_report_pdf
from app.ui.sales_page import SaleDetailsDialog
from app.ui.widgets import (
    Card,
    ClickableCard,
    configure_dialog_buttons,
    configure_table,
    make_button,
    money_str,
    show_toast,
    style_combo,
)


class ExpenseDialog(QDialog):
    """Окно регистрации операционного расхода магазина."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Çykdajy hasaba almak")
        self.setMinimumWidth(450)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Täze çykdajy")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.category_input = style_combo(QComboBox())
        self.category_input.setEditable(True)
        self.category_input.addItems([
            "Kärende",
            "Aýlyk",
            "Kommunal hyzmatlar",
            "Logistika we eltip bermek",
            "Mahabat we marketing",
            "Hojalyk zerurlyklary",
            "Beýleki çykdajylar",
        ])

        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["TMT", "USD"])

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setMinimumHeight(38)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.setMinimumHeight(38)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Bellik / tölegiň maksady...")

        form.addRow("Çykdajy kategoriýasy *", self.category_input)
        form.addRow("Walýuta *", self.currency_combo)
        form.addRow("Jemi *", self.amount_spin)
        form.addRow("Kurs (1 USD = X TMT) *", self.rate_spin)
        form.addRow("Düşündiriş", self.desc_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Çykdajyny ýatda sakla", "primary")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        configure_dialog_buttons(self, save_btn, cancel_btn)
        self.amount_spin.setFocus()
        self.amount_spin.selectAll()

    def _save(self) -> None:
        cat = self.category_input.currentText().strip()
        amt = Decimal(f"{self.amount_spin.value():.2f}")
        cur = self.currency_combo.currentText()
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        desc = self.desc_input.text().strip() or None

        if not cat:
            QMessageBox.warning(self, "Ýalňyşlyk", "Çykdajy kategoriýasyny görkeziň.")
            return
        if amt <= 0:
            QMessageBox.warning(self, "Ýalňyşlyk", "Çykdajy mukdary noldan uly bolmaly.")
            return

        try:
            with SessionLocal() as session:
                FinanceService.record_expense(
                    session=session,
                    category=cat,
                    amount=amt,
                    currency=cur,
                    exchange_rate=rate,
                    description=desc,
                )
                session.commit()
            show_toast(
                self.parentWidget() or self,
                f"Çykdajy hasaba alyndy: {money_str(amt)} {cur} ({cat})",
                kind="success",
            )
            self.accept()
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))


class CashAdjustmentDialog(QDialog):
    """Окно создания корректирующей / сторнирующей кассовой записи."""

    def __init__(self, reference_entry: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.reference_entry = reference_entry
        self.setWindowTitle("Maliýe düzediş / Storno")
        self.setMinimumWidth(460)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Düzediş ýazgysy")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        note = QLabel(
            "Asyl amallar pozulmaýar we üýtgedilmeýär.\n"
            "Düzediş sebäbi görkezilip žurnalda aýratyn ýazgy döredýär."
        )
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        root.addWidget(note)

        form = QFormLayout()
        form.setSpacing(10)

        self.direction_combo = style_combo(QComboBox())
        self.direction_combo.addItem("Kassa girdeji (+)", "income")
        self.direction_combo.addItem("Kassadan çykdajy (−)", "expense")

        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["TMT", "USD"])

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setMinimumHeight(38)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.setMinimumHeight(38)

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Düzedişiň hökmany sebäbini görkeziň...")

        if reference_entry:
            rev_dir = "expense" if reference_entry.get("is_inflow") else "income"
            idx = self.direction_combo.findData(rev_dir)
            if idx >= 0:
                self.direction_combo.setCurrentIndex(idx)
            self.currency_combo.setCurrentText(reference_entry.get("currency", "TMT"))
            self.amount_spin.setValue(float(reference_entry.get("amount", 0)))
            self.rate_spin.setValue(float(reference_entry.get("exchange_rate", 19.5)))
            self.reason_input.setText(
                f"Amal #{reference_entry['id']} storno ({reference_entry['type_label']})"
            )

        form.addRow("Amal görnüşi *", self.direction_combo)
        form.addRow("Walýuta *", self.currency_combo)
        form.addRow("Jemi *", self.amount_spin)
        form.addRow("Kurs (1 USD = X TMT) *", self.rate_spin)
        form.addRow("Sebäp *", self.reason_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Düzedişi geçir", "primary")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        configure_dialog_buttons(self, save_btn, cancel_btn)
        self.amount_spin.setFocus()

    def _save(self) -> None:
        direction = self.direction_combo.currentData()
        cur = self.currency_combo.currentText()
        amt = Decimal(f"{self.amount_spin.value():.2f}")
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        reason = self.reason_input.text().strip()

        if amt <= 0:
            QMessageBox.warning(self, "Ýalňyşlyk", "Düzediş mukdary noldan uly bolmaly.")
            return
        if not reason:
            QMessageBox.warning(self, "Ýalňyşlyk", "Düzedişiň sebäbini görkeziň.")
            return

        confirm = QMessageBox.question(
            self,
            "Düzedişi tassyklamak",
            f"{amt:,.2f} {cur} möçberinde maliýe düzedişini geçirmelimi?\n"
            f"Sebäbi: {reason}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        ref_id = self.reference_entry["id"] if self.reference_entry else None
        try:
            with SessionLocal() as session:
                FinanceService.record_cash_adjustment(
                    session=session,
                    direction=direction,
                    amount=amt,
                    currency=cur,
                    exchange_rate=rate,
                    reason=reason,
                    reference_movement_id=ref_id,
                )
                session.commit()
            show_toast(self.parentWidget() or self, "Düzediş ýazgysy üstünlikli döredildi.", kind="success")
            self.accept()
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))


class SimurgPayoutDialog(QDialog):
    """Окно приёма выплаты от Simurg (произвольной или готовой суммой по FIFO)."""

    def __init__(self, summary: dict, parent=None) -> None:
        super().__init__(parent)
        self.summary = summary
        self.setWindowTitle("Simurg tölegini kabul etmek")
        self.setMinimumWidth(480)
        self.setStyleSheet(theme.STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("🏦 Simurg tölegini kabul etmek")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        tot = summary["total_debt"]
        rdy = summary["ready_amount"]
        info = QLabel(
            f"Jemi bergi: <b>{money_str(tot['TMT'])} TMT</b>  |  <b>${money_str(tot['USD'])} USD</b>   "
            f"({summary['total_items_count']} enjam)\n"
            f"Almak üçin taýýar (≥5 gün): <span style='color:{theme.GREEN}; font-weight:700;'>"
            f"{money_str(rdy['TMT'])} TMT  |  ${money_str(rdy['USD'])} USD</span> "
            f"({summary['ready_items_count']} enjam)"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "background: #FFF8F1; border: 1px solid #FDBA74; border-radius: 8px; padding: 10px 12px;"
        )
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["TMT", "USD"])
        if tot["TMT"] <= 0 and tot["USD"] > 0:
            self.currency_combo.setCurrentText("USD")
        self.currency_combo.currentTextChanged.connect(self._on_currency_changed)

        amt_row = QHBoxLayout()
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 100000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setMinimumHeight(38)
        amt_row.addWidget(self.amount_spin, 1)

        fill_ready_btn = make_button("Taýýar jemi", "link")
        fill_ready_btn.clicked.connect(self._fill_ready)
        fill_all_btn = make_button("Ähli bergi", "link")
        fill_all_btn.clicked.connect(self._fill_all)
        amt_row.addWidget(fill_ready_btn)
        amt_row.addWidget(fill_all_btn)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.setMinimumHeight(38)

        self.ready_only_cb = QCheckBox("Diňe taýýar arzalardan (≥5 gün) ýap")
        self.ready_only_cb.setChecked(False)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Bellik (mysal üçin: Simurg geçirim)...")

        form.addRow("Walýuta *", self.currency_combo)
        form.addRow("Alnan pul *", amt_row)
        form.addRow("Kurs (1 USD = X TMT)", self.rate_spin)
        form.addRow("", self.ready_only_cb)
        form.addRow("Bellik", self.note_input)
        root.addLayout(form)

        hint = QLabel("Töleg iň köne Simurg arzalaryndan başlap awtomatiki (FIFO) ýapylýar we kassa geçýär.")
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Tölegi kassa kabul et", "primary")
        save_btn.clicked.connect(self._collect)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        configure_dialog_buttons(self, save_btn, cancel_btn)
        self._on_currency_changed()
        self.amount_spin.setFocus()
        self.amount_spin.selectAll()

    def _on_currency_changed(self) -> None:
        cur = self.currency_combo.currentText()
        rdy = self.summary["ready_amount"][cur]
        tot = self.summary["total_debt"][cur]
        self.amount_spin.setValue(float(rdy if rdy > 0 else tot))

    def _fill_ready(self) -> None:
        cur = self.currency_combo.currentText()
        self.amount_spin.setValue(float(self.summary["ready_amount"][cur]))

    def _fill_all(self) -> None:
        cur = self.currency_combo.currentText()
        self.amount_spin.setValue(float(self.summary["total_debt"][cur]))

    def _collect(self) -> None:
        cur = self.currency_combo.currentText()
        amt = Decimal(f"{self.amount_spin.value():.2f}")
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        if amt <= 0:
            QMessageBox.warning(self, "Ýalňyşlyk", "Töleg mukdary noldan uly bolmaly.")
            return
        try:
            with SessionLocal() as session, session.begin():
                res = FinanceService.collect_simurg_payout(
                    session=session,
                    currency=cur,
                    amount=amt,
                    ready_only=self.ready_only_cb.isChecked(),
                    exchange_rate=rate,
                    description=self.note_input.text().strip() or "Simurg tölegi",
                )
            show_toast(
                self.parentWidget() or self,
                f"Simurg tölegi kabul edildi: {money_str(res['collected_amount'])} {cur} ({res['sales_count']} çek)",
                kind="success",
                duration_ms=3400,
            )
            self.accept()
        except (ValueError, TypeError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))


class ShiftAndCashDialog(QDialog):
    """Единое окно закрытия смены (Z-отчёт), сверки кассы и пересчёта купюр (TMT + USD)."""

    TMT_DENOMS = (500, 100, 50, 20, 10, 5, 1)
    USD_DENOMS = (100, 50, 20, 10, 5, 1)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smena we kassa sanawy (Z-hasabat)")
        self.setMinimumSize(720, 580)
        self.setStyleSheet(theme.STYLE)

        self.tmt_spins: dict[int, QSpinBox] = {}
        self.usd_spins: dict[int, QSpinBox] = {}
        self._load_shift_stats()
        self._build_ui()
        self._recalculate_diff()
        self._recalculate_bills()

    def _load_shift_stats(self) -> None:
        today = date.today()
        t_start = datetime.combine(today, time.min)
        t_end = datetime.combine(today, time.max)
        with SessionLocal() as session:
            balances = FinanceService.get_register_balances(session)
            flow = FinanceService.get_period_cash_summary(session, t_start, t_end)
            sales_rep = ReportService.get_sales_report(session, t_start, t_end)
            profit_rep = ReportService.get_profit_report(session, t_start, t_end)
            session.commit()

        self.usd_expected = balances["usd_balance"]
        self.tmt_expected = balances["tmt_balance"]
        self.usd_income = flow["USD"]["income"]
        self.usd_expense = flow["USD"]["expense"]
        self.tmt_income = flow["TMT"]["income"]
        self.tmt_expense = flow["TMT"]["expense"]
        self.receipts_count = sales_rep["active_receipts_count"]
        self.profit_usd = profit_rep["by_currency"]["USD"]["gross_profit"]
        self.profit_tmt = profit_rep["by_currency"]["TMT"]["gross_profit"]

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("🔒 Smena ýapmak we kassany sanamak")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        summary = QLabel(
            f"Şu günki çekler: <b>{self.receipts_count}</b>   |   "
            f"Peýda: <b>${money_str(self.profit_usd)} USD / {money_str(self.profit_tmt)} TMT</b>\n"
            f"Girdeji: +${money_str(self.usd_income)} USD / +{money_str(self.tmt_income)} TMT   |   "
            f"Çykdajy: −${money_str(self.usd_expense)} USD / −{money_str(self.tmt_expense)} TMT"
        )
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        root.addWidget(summary)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_shift_tab(), "🔒 Smena barlagy (Z-hasabat)")
        self.tabs.addTab(self._build_bills_tab(), "🧮 Kupýura sanawy (TMT + USD)")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.adjust_btn = make_button("⚖ Kassany hakyky pul boýunça deňle")
        self.adjust_btn.clicked.connect(self._apply_reconciliation)
        footer.addWidget(self.adjust_btn)

        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        pdf_btn = make_button("🖨 Z-hasabaty PDF-de ýatda sakla", "primary")
        pdf_btn.clicked.connect(self._export_pdf)
        footer.addWidget(close_btn)
        footer.addWidget(pdf_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, pdf_btn, close_btn)

    def _build_shift_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(14)

        grid.addWidget(QLabel("<b>Kassa walýutasy</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Programmadaky galyndy</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Hakyky nagt pul</b>"), 0, 2)
        grid.addWidget(QLabel("<b>Tapawut</b>"), 0, 3)

        grid.addWidget(QLabel("Kassa USD ($):"), 1, 0)
        self.exp_usd_lbl = QLabel(f"${money_str(self.usd_expected)}")
        self.exp_usd_lbl.setStyleSheet("font-weight: 700;")
        grid.addWidget(self.exp_usd_lbl, 1, 1)

        self.actual_usd_spin = QDoubleSpinBox()
        self.actual_usd_spin.setRange(0, 100000000)
        self.actual_usd_spin.setDecimals(2)
        self.actual_usd_spin.setValue(float(self.usd_expected))
        self.actual_usd_spin.valueChanged.connect(self._recalculate_diff)
        grid.addWidget(self.actual_usd_spin, 1, 2)

        self.diff_usd_lbl = QLabel("$0.00")
        grid.addWidget(self.diff_usd_lbl, 1, 3)

        grid.addWidget(QLabel("Kassa TMT (m.):"), 2, 0)
        self.exp_tmt_lbl = QLabel(f"{money_str(self.tmt_expected)} m.")
        self.exp_tmt_lbl.setStyleSheet("font-weight: 700;")
        grid.addWidget(self.exp_tmt_lbl, 2, 1)

        self.actual_tmt_spin = QDoubleSpinBox()
        self.actual_tmt_spin.setRange(0, 100000000)
        self.actual_tmt_spin.setDecimals(2)
        self.actual_tmt_spin.setValue(float(self.tmt_expected))
        self.actual_tmt_spin.valueChanged.connect(self._recalculate_diff)
        grid.addWidget(self.actual_tmt_spin, 2, 2)

        self.diff_tmt_lbl = QLabel("0.00 m.")
        grid.addWidget(self.diff_tmt_lbl, 2, 3)

        lay.addLayout(grid)

        self.combined_actual_lbl = QLabel()
        self.combined_actual_lbl.setStyleSheet(
            f"background: #EFF6FF; color: {theme.NAVY}; border: 1px solid #BFDBFE; "
            "border-radius: 8px; padding: 10px 12px; font-weight: 700;"
        )
        lay.addWidget(self.combined_actual_lbl)

        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        lay.addWidget(self.status_banner)

        tip = QLabel(
            "Maslahat: «Kupýura sanawy» goýmasynda kagyz pullary sanasaňyz, hakyky mukdarlar bu ýere awtomatiki geçer."
        )
        tip.setObjectName("mutedText")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch()
        return w

    def _build_bills_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Kurs (1 USD = X TMT):"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.valueChanged.connect(self._recalculate_bills)
        rate_row.addWidget(self.rate_spin)
        rate_row.addStretch()

        clear_btn = make_button("Arassala")
        clear_btn.clicked.connect(self._clear_bills)
        rate_row.addWidget(clear_btn)

        sync_btn = make_button("↪ Smena barlagyna geçir")
        sync_btn.clicked.connect(self._sync_bills_to_shift)
        rate_row.addWidget(sync_btn)
        lay.addLayout(rate_row)

        cols = QHBoxLayout()
        cols.setSpacing(14)

        tmt_card = Card(margins=(12, 10, 12, 10), spacing=6)
        t_head = QLabel("TMT kupýuralar")
        t_head.setObjectName("cardTitle")
        tmt_card.body.addWidget(t_head)

        t_grid = QGridLayout()
        t_grid.setSpacing(5)
        for idx, denom in enumerate(self.TMT_DENOMS):
            t_grid.addWidget(QLabel(f"{denom} TMT ×"), idx, 0)
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setMinimumHeight(28)
            sp.valueChanged.connect(self._recalculate_bills)
            self.tmt_spins[denom] = sp
            t_grid.addWidget(sp, idx, 1)
        t_grid.addWidget(QLabel("Teňňe / goşmaça:"), len(self.TMT_DENOMS), 0)
        self.tmt_extra = QDoubleSpinBox()
        self.tmt_extra.setRange(0, 10000000)
        self.tmt_extra.setDecimals(2)
        self.tmt_extra.valueChanged.connect(self._recalculate_bills)
        t_grid.addWidget(self.tmt_extra, len(self.TMT_DENOMS), 1)
        tmt_card.body.addLayout(t_grid)

        self.tmt_bills_lbl = QLabel("Sanalan TMT: 0.00")
        self.tmt_bills_lbl.setStyleSheet(f"font-weight: 700; color: {theme.TEAL};")
        tmt_card.body.addWidget(self.tmt_bills_lbl)
        cols.addWidget(tmt_card, 1)

        usd_card = Card(margins=(12, 10, 12, 10), spacing=6)
        u_head = QLabel("USD kupýuralar")
        u_head.setObjectName("cardTitle")
        usd_card.body.addWidget(u_head)

        u_grid = QGridLayout()
        u_grid.setSpacing(5)
        for idx, denom in enumerate(self.USD_DENOMS):
            u_grid.addWidget(QLabel(f"${denom} USD ×"), idx, 0)
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setMinimumHeight(28)
            sp.valueChanged.connect(self._recalculate_bills)
            self.usd_spins[denom] = sp
            u_grid.addWidget(sp, idx, 1)
        u_grid.addWidget(QLabel("Sent / goşmaça:"), len(self.USD_DENOMS), 0)
        self.usd_extra = QDoubleSpinBox()
        self.usd_extra.setRange(0, 10000000)
        self.usd_extra.setDecimals(2)
        self.usd_extra.valueChanged.connect(self._recalculate_bills)
        u_grid.addWidget(self.usd_extra, len(self.USD_DENOMS), 1)
        usd_card.body.addLayout(u_grid)

        self.usd_bills_lbl = QLabel("Sanalan USD: $0.00")
        self.usd_bills_lbl.setStyleSheet(f"font-weight: 700; color: {theme.NAVY};")
        usd_card.body.addWidget(self.usd_bills_lbl)
        cols.addWidget(usd_card, 1)

        lay.addLayout(cols)

        self.bills_grand_lbl = QLabel()
        self.bills_grand_lbl.setStyleSheet(
            f"background: #F8FAFC; border: 1px solid {theme.BORDER}; border-radius: 8px; "
            f"padding: 8px 12px; font-weight: 800; color: {theme.NAVY};"
        )
        lay.addWidget(self.bills_grand_lbl)
        return w

    def _clear_bills(self) -> None:
        for sp in (*self.tmt_spins.values(), *self.usd_spins.values()):
            sp.setValue(0)
        self.tmt_extra.setValue(0.0)
        self.usd_extra.setValue(0.0)

    def _get_bills_totals(self) -> tuple[Decimal, Decimal, Decimal]:
        tmt_sum = sum(Decimal(d) * sp.value() for d, sp in self.tmt_spins.items()) + Decimal(
            f"{self.tmt_extra.value():.2f}"
        )
        usd_sum = sum(Decimal(d) * sp.value() for d, sp in self.usd_spins.items()) + Decimal(
            f"{self.usd_extra.value():.2f}"
        )
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        return tmt_sum.quantize(Decimal("0.01")), usd_sum.quantize(Decimal("0.01")), rate

    def _recalculate_bills(self) -> None:
        tmt_sum, usd_sum, rate = self._get_bills_totals()
        total_tmt = (tmt_sum + usd_sum * rate).quantize(Decimal("0.01"))
        total_usd = (usd_sum + (tmt_sum / rate)).quantize(Decimal("0.01"))
        self.tmt_bills_lbl.setText(f"Sanalan TMT: {tmt_sum:,.2f} TMT")
        self.usd_bills_lbl.setText(f"Sanalan USD: ${usd_sum:,.2f} USD")
        self.bills_grand_lbl.setText(
            f"JEMI SANALAN:   {total_tmt:,.2f} TMT   •   ${total_usd:,.2f} USD"
        )
        if tmt_sum > 0 or usd_sum > 0:
            self.actual_tmt_spin.blockSignals(True)
            self.actual_usd_spin.blockSignals(True)
            if tmt_sum > 0:
                self.actual_tmt_spin.setValue(float(tmt_sum))
            if usd_sum > 0:
                self.actual_usd_spin.setValue(float(usd_sum))
            self.actual_tmt_spin.blockSignals(False)
            self.actual_usd_spin.blockSignals(False)
            self._recalculate_diff()

    def _sync_bills_to_shift(self) -> None:
        tmt_sum, usd_sum, _rate = self._get_bills_totals()
        self.actual_tmt_spin.setValue(float(tmt_sum))
        self.actual_usd_spin.setValue(float(usd_sum))
        self.tabs.setCurrentIndex(0)
        show_toast(self, "Sanalan pul smena barlagyna geçirildi.", kind="info")

    def _recalculate_diff(self) -> None:
        act_usd = Decimal(f"{self.actual_usd_spin.value():.2f}")
        act_tmt = Decimal(f"{self.actual_tmt_spin.value():.2f}")
        rate = Decimal(f"{self.rate_spin.value():.4f}") if hasattr(self, "rate_spin") else SettingsService.get_default_exchange_rate()
        diff_usd = act_usd - self.usd_expected
        diff_tmt = act_tmt - self.tmt_expected

        u_sign = "+" if diff_usd > 0 else ""
        t_sign = "+" if diff_tmt > 0 else ""
        self.diff_usd_lbl.setText(f"{u_sign}{money_str(diff_usd)} USD")
        self.diff_tmt_lbl.setText(f"{t_sign}{money_str(diff_tmt)} TMT")

        self.diff_usd_lbl.setStyleSheet(
            f"font-weight: 700; color: {theme.GREEN if diff_usd == 0 else theme.RED};"
        )
        self.diff_tmt_lbl.setStyleSheet(
            f"font-weight: 700; color: {theme.GREEN if diff_tmt == 0 else theme.RED};"
        )

        tot_tmt = (act_tmt + act_usd * rate).quantize(Decimal("0.01"))
        tot_usd = (act_usd + (act_tmt / rate)).quantize(Decimal("0.01"))
        self.combined_actual_lbl.setText(
            f"Hakyky jemi kassa (kurs {rate:.2f}):   {tot_tmt:,.2f} TMT   •   ${tot_usd:,.2f} USD"
        )

        has_diff = diff_usd != Decimal("0.00") or diff_tmt != Decimal("0.00")
        self.adjust_btn.setEnabled(has_diff)
        if not has_diff:
            self.status_banner.setText("✔ Iki kassadaky hakyky nagt pul hasaplanan galyndy bilen doly gabat gelýär.")
            self.status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #EAF7EF; color: {theme.GREEN}; font-weight: 600;"
            )
        else:
            self.status_banner.setText(
                "Programma bilen hakyky nagt puluň arasynda tapawut tapyldy. "
                "«Kassany hakyky pul boýunça deňle» düwmesi bilen düzediş geçirip bilersiňiz."
            )
            self.status_banner.setStyleSheet(
                f"padding: 8px 10px; border-radius: 8px; background: #FFF3E6; color: {theme.ACCENT}; font-weight: 600;"
            )

    def _apply_reconciliation(self) -> None:
        act_usd = Decimal(f"{self.actual_usd_spin.value():.2f}")
        act_tmt = Decimal(f"{self.actual_tmt_spin.value():.2f}")
        diff_usd = act_usd - self.usd_expected
        diff_tmt = act_tmt - self.tmt_expected
        if diff_usd == 0 and diff_tmt == 0:
            return

        ans = QMessageBox.question(
            self,
            "Kassany deňlemek",
            f"Kassa balanslaryny hakyky pula deňlemelimi?\n"
            f"• USD düzedişi: {diff_usd:+,.2f} USD (täze: ${act_usd:,.2f})\n"
            f"• TMT düzedişi: {diff_tmt:+,.2f} TMT (täze: {act_tmt:,.2f})",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        rate = Decimal(f"{self.rate_spin.value():.4f}")
        try:
            with SessionLocal() as session:
                if diff_usd != 0:
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_usd > 0 else "expense",
                        amount=abs(diff_usd),
                        currency="USD",
                        exchange_rate=rate,
                        reason="Smena we kassa barlagy",
                    )
                if diff_tmt != 0:
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_tmt > 0 else "expense",
                        amount=abs(diff_tmt),
                        currency="TMT",
                        exchange_rate=rate,
                        reason="Smena we kassa barlagy",
                    )
                session.commit()
            self._load_shift_stats()
            self.exp_usd_lbl.setText(f"${money_str(self.usd_expected)}")
            self.exp_tmt_lbl.setText(f"{money_str(self.tmt_expected)} m.")
            self._recalculate_diff()
            show_toast(self, "Kassa balanslary hakyky galyndy boýunça deňlendi.", kind="success")
        except (ValueError, TypeError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _export_pdf(self) -> None:
        act_usd = Decimal(f"{self.actual_usd_spin.value():.2f}")
        act_tmt = Decimal(f"{self.actual_tmt_spin.value():.2f}")
        export_shift_report_pdf(
            {
                "usd_income": self.usd_income,
                "usd_expense": self.usd_expense,
                "tmt_income": self.tmt_income,
                "tmt_expense": self.tmt_expense,
                "usd_expected": self.usd_expected,
                "tmt_expected": self.tmt_expected,
                "usd_actual": act_usd,
                "tmt_actual": act_tmt,
                "usd_diff": act_usd - self.usd_expected,
                "tmt_diff": act_tmt - self.tmt_expected,
                "receipts_count": self.receipts_count,
                "profit_usd": self.profit_usd,
                "profit_tmt": self.profit_tmt,
            },
            self,
        )


# Обратная совместимость имён классов для существующих тестов и импортов
ShiftCloseDialog = ShiftAndCashDialog
CashCountDialog = ShiftAndCashDialog


class FinancePage(QWidget):
    """Страница «Финансы»: объединённый баланс кассы, Simurg, стоимость склада, поставщики и журнал."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.journal_entries: list[dict] = []
        self.simurg_rows: list[dict] = []
        self.simurg_summary: dict = {}
        self.supplier_rows: list[dict] = []

        self._build_ui()
        self.refresh_data()

    def open_simurg_tab(self) -> None:
        self.tabs.setCurrentIndex(1)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Maliýe we hasaplaşyklar")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Kassa balansy, Simurg garaşaryna hasaplaşyklary, sklad bahasy we üpjün edijiler"
        )
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        adjust_btn = make_button("Düzediş / Storno")
        adjust_btn.clicked.connect(self._open_adjustment_dialog)
        header.addWidget(adjust_btn)

        zero_cash_btn = make_button("🧹 Kassany nolla", "danger")
        zero_cash_btn.clicked.connect(self._zero_cash_dialog)
        header.addWidget(zero_cash_btn)

        shift_cash_btn = make_button("🔒 Smena we kassa sanawy", "dark")
        shift_cash_btn.clicked.connect(self._open_shift_and_cash_dialog)
        header.addWidget(shift_cash_btn)

        refresh_btn = make_button("↻ Täzele", "primary")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        # Ровная сетка 2x2 из 4 объединённых карточек
        cards_grid = QGridLayout()
        cards_grid.setSpacing(14)

        # 1. Kassa balansy (общая USD + TMT)
        self.cash_main_label = QLabel("$0.00 USD  |  0.00 TMT")
        self.cash_eq_label = QLabel("Jemi: 0.00 TMT • $0.00 USD")
        self.cash_flow_label = QLabel("Girdeji / Çykdajy")
        cash_card = self._build_rich_card(
            "💵 Kassa balansy (USD / TMT)",
            self.cash_main_label,
            self.cash_eq_label,
            self.cash_flow_label,
            theme.NAVY,
            accent_sub_color=theme.TEAL,
        )
        cards_grid.addWidget(cash_card, 0, 0)

        # 2. Simurg bergisi (кликабельная -> открывает вкладку Simurg)
        self.simurg_main_label = QLabel("$0.00  |  0.00 TMT")
        self.simurg_ready_label = QLabel("✔ Almak üçin taýýar (≥5 gün): 0.00 TMT")
        self.simurg_devices_label = QLabel("0 enjam • 0 taýýar / 0 garaşylýar")
        simurg_card = self._build_rich_card(
            "🏦 Simurg bergisi (5 günlük töleg) →",
            self.simurg_main_label,
            self.simurg_ready_label,
            self.simurg_devices_label,
            theme.ACCENT,
            accent_sub_color=theme.GREEN,
            clickable=True,
        )
        simurg_card.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        cards_grid.addWidget(simurg_card, 0, 1)

        # 3. Sklad jemi baha (USD / TMT)
        self.stock_val_main_label = QLabel("$0.00 USD  |  0.00 TMT")
        self.stock_val_eq_label = QLabel("Asyl: $0.00 USD + 0.00 TMT")
        self.stock_val_units_label = QLabel("0 enjam • 0 aksessuar")
        stock_card = self._build_rich_card(
            "🏪 Sklad jemi baha (USD / TMT)",
            self.stock_val_main_label,
            self.stock_val_eq_label,
            self.stock_val_units_label,
            theme.BLUE,
            accent_sub_color=theme.NAVY,
        )
        cards_grid.addWidget(stock_card, 1, 0)

        # 4. Dükanyň üpjün edijilere bergisi (кликабельная -> вкладка поставщиков)
        self.sup_payable_main = QLabel("$0.00 USD  |  0.00 TMT")
        self.sup_payable_sub = QLabel("Işjeň alyşlar boýunça tölenmedik galyndy")
        self.sup_payable_hint = QLabel("Hasaplaşyk üçin basyň →")
        sup_card = self._build_rich_card(
            "📦 Üpjün edijilere bergi (USD / TMT)",
            self.sup_payable_main,
            self.sup_payable_sub,
            self.sup_payable_hint,
            theme.RED,
            accent_sub_color=theme.MUTED,
            clickable=True,
        )
        sup_card.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        cards_grid.addWidget(sup_card, 1, 1)

        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)
        root.addLayout(cards_grid)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_journal_tab(), "Maliýe amallary žurnaly")
        self.tabs.addTab(self._create_simurg_tab(), "🏦 Simurg hasaplaşyklary")
        self.tabs.addTab(self._create_supplier_debts_tab(), "Üpjün edijiler bilen hasaplaşyk")
        root.addWidget(self.tabs, 1)

    def _build_rich_card(
        self,
        title: str,
        value_label: QLabel,
        mid_label: QLabel,
        sub_label: QLabel,
        color: str,
        accent_sub_color: str = theme.MUTED,
        clickable: bool = False,
    ) -> Card:
        card = ClickableCard(margins=(16, 12, 16, 12), spacing=3) if clickable else Card(margins=(16, 12, 16, 12), spacing=3)
        t = QLabel(title)
        t.setObjectName("mutedText")
        value_label.setStyleSheet(f"font-size: 14.5pt; font-weight: 800; color: {color};")
        mid_label.setStyleSheet(f"font-size: 9.5pt; font-weight: 700; color: {accent_sub_color};")
        sub_label.setStyleSheet(f"font-size: 8.5pt; color: {theme.MUTED};")
        card.body.addWidget(t)
        card.body.addWidget(value_label)
        card.body.addWidget(mid_label)
        card.body.addWidget(sub_label)
        return card

    def _create_journal_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.use_date_filter = QCheckBox("Döwür:")
        self.use_date_filter.setChecked(False)
        self.use_date_filter.toggled.connect(self._load_journal)
        filters.addWidget(self.use_date_filter)

        today = QDate.currentDate()
        self.date_from_edit = QDateEdit(today.addMonths(-1))
        self.date_from_edit.setCalendarPopup(True)
        self.date_from_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_from_edit.dateChanged.connect(self._load_journal)
        filters.addWidget(self.date_from_edit)

        filters.addWidget(QLabel("—"))

        self.date_to_edit = QDateEdit(today)
        self.date_to_edit.setCalendarPopup(True)
        self.date_to_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_to_edit.dateChanged.connect(self._load_journal)
        filters.addWidget(self.date_to_edit)

        self.journal_curr_combo = style_combo(QComboBox())
        self.journal_curr_combo.addItem("Ähli walýutalar", None)
        self.journal_curr_combo.addItem("USD", "USD")
        self.journal_curr_combo.addItem("TMT", "TMT")
        self.journal_curr_combo.currentIndexChanged.connect(self._load_journal)
        filters.addWidget(self.journal_curr_combo)

        self.journal_type_combo = style_combo(QComboBox())
        self.journal_type_combo.addItem("Ähli amal görnüşleri", None)
        self.journal_type_combo.addItem("Satyş tölegi", "sale_payment")
        self.journal_type_combo.addItem("Simurg / Bergi tölegi", "customer_debt_payment")
        self.journal_type_combo.addItem("Müşderä gaýtargy", "sale_change")
        self.journal_type_combo.addItem("Çek ýatyrmada yzyna gaýtarma", "sale_refund")
        self.journal_type_combo.addItem("Üpjün edijä töleg", "purchase_payment")
        self.journal_type_combo.addItem("Üpjün edijiden yzyna gaýtarma", "purchase_refund")
        self.journal_type_combo.addItem("Çalyşyk goşmaça tölegi (Trade-in)", "exchange_payment")
        self.journal_type_combo.addItem("Operasion çykdajy", "expense")
        self.journal_type_combo.addItem("Düzediş (girdeji)", "correction_income")
        self.journal_type_combo.addItem("Düzediş (çykdajy)", "correction_expense")
        self.journal_type_combo.currentIndexChanged.connect(self._load_journal)
        filters.addWidget(self.journal_type_combo)

        self.journal_search = QLineEdit()
        self.journal_search.setPlaceholderText("Resminama ýa-da düşündiriş boýunça gözleg...")
        self.journal_search.setClearButtonEnabled(True)
        self.journal_search.textChanged.connect(self._load_journal)
        filters.addWidget(self.journal_search, 1)

        open_doc_btn = make_button("📄 Resminamany aç", "primary")
        open_doc_btn.clicked.connect(self._open_selected_journal_doc)
        filters.addWidget(open_doc_btn)

        storno_btn = make_button("Saýlanany storno et", "danger")
        storno_btn.clicked.connect(self._storno_selected_movement)
        filters.addWidget(storno_btn)

        layout.addLayout(filters)

        self.journal_table = QTableWidget(0, 9)
        self.journal_table.setHorizontalHeaderLabels([
            "ID", "Sene", "Ugur", "Amal görnüşi", "Jemi", "Walýuta", "Kurs", "Resminama", "Bellik",
        ])
        configure_table(self.journal_table)
        self.journal_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.journal_table.cellDoubleClicked.connect(self._open_journal_document)
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.journal_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_journal_doc)
        layout.addWidget(self.journal_table, 1)

        self.period_summary_label = QLabel()
        self.period_summary_label.setObjectName("mutedText")
        layout.addWidget(self.period_summary_label)

        return widget

    def _create_simurg_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.simurg_filter_combo = style_combo(QComboBox())
        self.simurg_filter_combo.addItem("Ähli açyk Simurg bergileri", "open")
        self.simurg_filter_combo.addItem("🟢 Diňe almak üçin taýýar (≥5 gün)", "ready")
        self.simurg_filter_combo.addItem("🟡 Garaşylýanlar (<5 gün)", "pending")
        self.simurg_filter_combo.addItem("Ähli çekler (tölenenler bilen)", "all")
        self.simurg_filter_combo.currentIndexChanged.connect(self._load_simurg_table)
        top.addWidget(self.simurg_filter_combo)

        self.simurg_search = QLineEdit()
        self.simurg_search.setPlaceholderText("Çek, haryt/IMEI ýa-da müşderi boýunça gözleg...")
        self.simurg_search.setClearButtonEnabled(True)
        self.simurg_search.textChanged.connect(self._load_simurg_table)
        top.addWidget(self.simurg_search, 1)

        collect_ready_btn = make_button("💰 Taýýar puly al (≥5 gün)", "success")
        collect_ready_btn.clicked.connect(self._collect_all_ready_simurg)
        top.addWidget(collect_ready_btn)

        collect_custom_btn = make_button("💵 Töleg al (summa)", "primary")
        collect_custom_btn.clicked.connect(self._open_simurg_payout_dialog)
        top.addWidget(collect_custom_btn)

        open_btn = make_button("📄 Çeki aç")
        open_btn.clicked.connect(self._open_selected_simurg_sale)
        top.addWidget(open_btn)

        zero_debt_btn = make_button("🧹 Bergini nolla", "danger")
        zero_debt_btn.clicked.connect(self._zero_selected_simurg_debt)
        top.addWidget(zero_debt_btn)

        layout.addLayout(top)

        self.simurg_table = QTableWidget(0, 9)
        self.simurg_table.setHorizontalHeaderLabels([
            "ID",
            "Çek",
            "Satyş senesi",
            "Aljak güni (+5g)",
            "Haryt / IMEI",
            "Müşderi / Arza",
            "Jemi",
            "Galan bergi",
            "Ýagdaýy",
        ])
        configure_table(self.simurg_table)
        self.simurg_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.simurg_table.cellDoubleClicked.connect(lambda _r, _c: self._open_selected_simurg_sale())
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.simurg_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_simurg_sale)
        layout.addWidget(self.simurg_table, 1)

        self.simurg_footer_label = QLabel()
        self.simurg_footer_label.setObjectName("mutedText")
        layout.addWidget(self.simurg_footer_label)

        return widget

    def _create_supplier_debts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.sup_filter_combo = style_combo(QComboBox())
        self.sup_filter_combo.addItem("Açyk bergiler", "open")
        self.sup_filter_combo.addItem("Ähli alyşlar (ýapylanlar bilen)", "all")
        self.sup_filter_combo.currentIndexChanged.connect(self._load_supplier_payables)
        top.addWidget(self.sup_filter_combo)

        self.sup_search = QLineEdit()
        self.sup_search.setPlaceholderText("Üpjün ediji ýa-da alyş № boýunça gözleg...")
        self.sup_search.setClearButtonEnabled(True)
        self.sup_search.textChanged.connect(self._load_supplier_payables)
        top.addWidget(self.sup_search, 1)

        open_btn = make_button("Alyşy aç / Töle", "primary")
        open_btn.clicked.connect(self._open_selected_supplier_purchase)
        top.addWidget(open_btn)

        pay_sup_btn = make_button("✔ Doly hasaplaş (kassa)")
        pay_sup_btn.clicked.connect(lambda: self._settle_selected_supplier_debt(with_cash=True))
        top.addWidget(pay_sup_btn)

        zero_sup_btn = make_button("🧹 Bergini nolla", "danger")
        zero_sup_btn.clicked.connect(lambda: self._settle_selected_supplier_debt(with_cash=False))
        top.addWidget(zero_sup_btn)

        layout.addLayout(top)

        self.sup_table = QTableWidget(0, 7)
        self.sup_table.setHorizontalHeaderLabels([
            "Alyş №",
            "Sene",
            "Üpjün ediji",
            "Walýuta (Kurs)",
            "Alyş jemi",
            "Tölendi",
            "Galan bergi",
        ])
        configure_table(self.sup_table)
        self.sup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sup_table.cellDoubleClicked.connect(lambda _r, _c: self._open_selected_supplier_purchase())
        for seq in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(seq), self.sup_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected_supplier_purchase)
        layout.addWidget(self.sup_table, 1)

        return widget

    def refresh_data(self) -> None:
        rate = SettingsService.get_default_exchange_rate()
        with SessionLocal() as session:
            balances = FinanceService.get_register_balances(session)
            combined = FinanceService.get_combined_cash_totals(session, rate)
            debts = FinanceService.get_all_outstanding_balances(session)
            flow = FinanceService.get_period_cash_summary(session)
            simurg = FinanceService.get_simurg_summary(session, include_paid=False)
            stock_val = ReportService.get_stock_valuation(session, rate)
            session.commit()

        self.simurg_summary = simurg

        # 1. Kassa balansy (объединённый)
        self.cash_main_label.setText(
            f"${balances['usd_balance']:,.2f} USD   |   {balances['tmt_balance']:,.2f} TMT"
        )
        self.cash_eq_label.setText(
            f"Jemi (kurs {combined['exchange_rate']:.2f}):  {combined['total_in_tmt']:,.2f} TMT  •  ${combined['total_in_usd']:,.2f} USD"
        )
        self.cash_flow_label.setText(
            f"Girdeji: +${flow['USD']['income']:,.2f} / +{flow['TMT']['income']:,.2f} m.   |   "
            f"Çykdajy: −${flow['USD']['expense']:,.2f} / −{flow['TMT']['expense']:,.2f} m."
        )

        # 2. Simurg bergisi
        tot = simurg["total_debt"]
        rdy = simurg["ready_amount"]
        self.simurg_main_label.setText(
            f"${tot['USD']:,.2f} USD   |   {tot['TMT']:,.2f} TMT"
        )
        self.simurg_ready_label.setText(
            f"✔ Almak üçin taýýar (≥5 gün):  ${rdy['USD']:,.2f}  |  {rdy['TMT']:,.2f} TMT"
        )
        self.simurg_devices_label.setText(
            f"{simurg['total_items_count']} enjam ({simurg['ready_items_count']} taýýar • "
            f"{simurg['pending_items_count']} garaşylýar)  •  {simurg['open_sales_count']} açyk çek"
        )

        # 3. Sklad jemi baha
        self.stock_val_main_label.setText(
            f"${stock_val['total_in_usd']:,.2f} USD   |   {stock_val['total_in_tmt']:,.2f} TMT"
        )
        self.stock_val_eq_label.setText(
            f"Asyl walýuta: ${stock_val['usd_native']:,.2f} USD + {stock_val['tmt_native']:,.2f} TMT (kurs {stock_val['exchange_rate']:.2f})"
        )
        self.stock_val_units_label.setText(
            f"{stock_val['devices_count']} enjam (IMEI) • {stock_val['accessories_count']} aksessuar (jemi {stock_val['total_units']} sany)"
        )

        # 4. Üpjün edijilere bergi
        sp = debts["supplier_payables"]
        self.sup_payable_main.setText(
            f"${sp['USD']:,.2f} USD   |   {sp['TMT']:,.2f} TMT"
        )

        self._load_journal()
        self._load_simurg_table()
        self._load_supplier_payables()

    def _load_journal(self, *_args) -> None:
        date_from = None
        date_to = None
        if self.use_date_filter.isChecked():
            d1 = self.date_from_edit.date().toPython()
            d2 = self.date_to_edit.date().toPython()
            date_from = datetime.combine(d1, time.min)
            date_to = datetime.combine(d2, time.max)

        curr = self.journal_curr_combo.currentData()
        mov_type = self.journal_type_combo.currentData()
        query = self.journal_search.text().strip()

        with SessionLocal() as session:
            self.journal_entries = FinanceService.get_financial_journal(
                session=session,
                date_from=date_from,
                date_to=date_to,
                currency=curr,
                movement_type=mov_type,
                search_query=query,
            )
            period_flow = FinanceService.get_period_cash_summary(
                session=session,
                date_from=date_from,
                date_to=date_to,
            )

        self.journal_table.setRowCount(len(self.journal_entries))
        for i, entry in enumerate(self.journal_entries):
            date_str = entry["date"].strftime("%d.%m.%Y %H:%M") if entry["date"] else "—"
            vals = [
                str(entry["id"]),
                date_str,
                entry["direction"],
                entry["type_label"],
                money_str(entry["amount"]),
                entry["currency"],
                f"{entry['exchange_rate']:,.4f}",
                entry["doc_label"],
                entry["description"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 2, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c in (2, 4):
                    cell.setForeground(
                        QColor(theme.GREEN if entry["is_inflow"] else theme.RED)
                    )
                self.journal_table.setItem(i, c, cell)

        u = period_flow["USD"]
        t = period_flow["TMT"]
        self.period_summary_label.setText(
            f"Saýlanan döwür — USD: Girdeji +${u['income']:,.2f}, Çykdajy −${u['expense']:,.2f}, Arassa akym: ${u['net']:,.2f}   |   "
            f"TMT: Girdeji +{t['income']:,.2f} m., Çykdajy −{t['expense']:,.2f} m., Arassa akym: {t['net']:,.2f} m."
        )

    def _load_simurg_table(self, *_args) -> None:
        mode = self.simurg_filter_combo.currentData()
        query = self.simurg_search.text().strip().lower()

        with SessionLocal() as session:
            summary = FinanceService.get_simurg_summary(
                session=session,
                include_paid=(mode == "all"),
            )
        self.simurg_summary = summary

        filtered = []
        for r in summary["rows"]:
            if mode == "open" and r["remaining_debt"] <= 0:
                continue
            if mode == "ready" and (r["remaining_debt"] <= 0 or not r["is_ready"]):
                continue
            if mode == "pending" and (r["remaining_debt"] <= 0 or r["is_ready"]):
                continue
            if query:
                hay = f"{r['receipt_number']} {r['items_summary']} {r['customer_name']} {r['comment']}".lower()
                if query not in hay:
                    continue
            filtered.append(r)

        self.simurg_rows = filtered
        self.simurg_table.setRowCount(len(filtered))
        for i, r in enumerate(filtered):
            sale_str = r["sale_date"].strftime("%d.%m.%Y") if r["sale_date"] else "—"
            payout_str = r["payout_date"].strftime("%d.%m.%Y") if r["payout_date"] else "—"
            cust_str = r["customer_name"]
            if r["comment"]:
                cust_str = f"{cust_str} • {r['comment']}"
            vals = [
                str(r["sale_id"]),
                r["receipt_number"],
                sale_str,
                payout_str,
                r["items_summary"],
                cust_str,
                f"{money_str(r['original_amount'])} {r['currency']}",
                f"{money_str(r['remaining_debt'])} {r['currency']}",
                r["status_label"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 2, 3, 6, 7, 8):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7 and r["remaining_debt"] > 0:
                    cell.setForeground(QColor(theme.GREEN if r["is_ready"] else theme.ACCENT))
                if c == 8:
                    if r["remaining_debt"] <= 0:
                        cell.setForeground(QColor(theme.MUTED))
                    elif r["is_ready"]:
                        cell.setForeground(QColor("white"))
                        cell.setBackground(QColor(theme.GREEN))
                    else:
                        cell.setForeground(QColor("#9A3412"))
                        cell.setBackground(QColor("#FFEDD5"))
                self.simurg_table.setItem(i, c, cell)

        tot = summary["total_debt"]
        rdy = summary["ready_amount"]
        pnd = summary["pending_amount"]
        self.simurg_footer_label.setText(
            f"Simurg jemi: {summary['total_items_count']} enjam • "
            f"Taýýar (≥5g): {money_str(rdy['TMT'])} TMT / ${money_str(rdy['USD'])} USD   |   "
            f"Garaşylýar: {money_str(pnd['TMT'])} TMT / ${money_str(pnd['USD'])} USD   |   "
            f"Jemi bergi: {money_str(tot['TMT'])} TMT / ${money_str(tot['USD'])} USD"
        )

    def _load_supplier_payables(self, *_args) -> None:
        mode = self.sup_filter_combo.currentData()
        query = self.sup_search.text().strip().lower()

        with SessionLocal() as session:
            all_rows = FinanceService.get_supplier_payables_list(
                session=session,
                include_paid=(mode == "all"),
            )

        filtered = []
        for r in all_rows:
            if mode == "open" and r["store_debt_to_supplier"] <= 0:
                continue
            if query:
                hay = f"{r['purchase_id']} {r['supplier_name']}".lower()
                if query not in hay:
                    continue
            filtered.append(r)

        self.supplier_rows = filtered
        self.sup_table.setRowCount(len(filtered))
        for i, r in enumerate(filtered):
            date_str = r["purchase_date"].strftime("%d.%m.%Y %H:%M") if r["purchase_date"] else "—"
            vals = [
                str(r["purchase_id"]),
                date_str,
                r["supplier_name"],
                f"{r['currency']} ({r['exchange_rate']:,.2f})",
                money_str(r["original_amount"]),
                money_str(r["paid_amount"]),
                money_str(r["store_debt_to_supplier"]),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 3, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 6 and r["store_debt_to_supplier"] > 0:
                    cell.setForeground(QColor(theme.RED))
                self.sup_table.setItem(i, c, cell)

    def _open_adjustment_dialog(self) -> None:
        dlg = CashAdjustmentDialog(parent=self)
        if dlg.exec():
            self.refresh_data()

    def _open_shift_and_cash_dialog(self) -> None:
        dlg = ShiftAndCashDialog(parent=self)
        dlg.exec()
        self.refresh_data()

    def _collect_all_ready_simurg(self) -> None:
        rdy = self.simurg_summary.get("ready_amount", {"USD": Decimal("0.00"), "TMT": Decimal("0.00")})
        rdy_tmt = rdy.get("TMT", Decimal("0.00"))
        rdy_usd = rdy.get("USD", Decimal("0.00"))
        if rdy_tmt <= 0 and rdy_usd <= 0:
            show_toast(self, "Häzirlikçe almak üçin taýýar (≥5 gün) Simurg puly ýok.", kind="info")
            return

        parts = []
        if rdy_tmt > 0:
            parts.append(f"{money_str(rdy_tmt)} TMT")
        if rdy_usd > 0:
            parts.append(f"${money_str(rdy_usd)} USD")

        ans = QMessageBox.question(
            self,
            "Simurg taýýar puly almak",
            f"Taýýar bolan ähli Simurg tölegini ({' + '.join(parts)}) kassa kabul etmelimi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        rate = SettingsService.get_default_exchange_rate()
        try:
            total_sales = 0
            with SessionLocal() as session, session.begin():
                if rdy_tmt > 0:
                    res = FinanceService.collect_simurg_payout(
                        session, "TMT", amount=None, ready_only=True, exchange_rate=rate
                    )
                    total_sales += res["sales_count"]
                if rdy_usd > 0:
                    res = FinanceService.collect_simurg_payout(
                        session, "USD", amount=None, ready_only=True, exchange_rate=rate
                    )
                    total_sales += res["sales_count"]
            self.refresh_data()
            show_toast(
                self,
                f"Simurg taýýar puly kassa kabul edildi: {' + '.join(parts)} ({total_sales} çek).",
                kind="success",
                duration_ms=3400,
            )
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _open_simurg_payout_dialog(self) -> None:
        tot = self.simurg_summary.get("total_debt", {"USD": Decimal("0.00"), "TMT": Decimal("0.00")})
        if tot.get("TMT", 0) <= 0 and tot.get("USD", 0) <= 0:
            show_toast(self, "Açyk Simurg bergisi ýok.", kind="info")
            return
        dlg = SimurgPayoutDialog(self.simurg_summary, parent=self)
        if dlg.exec():
            self.refresh_data()

    def _open_selected_simurg_sale(self) -> None:
        row = self.simurg_table.currentRow()
        if not (0 <= row < len(self.simurg_rows)):
            show_toast(self, "Simurg tablisasyndan çek saýlaň.", kind="info")
            return
        sale_id = self.simurg_rows[row]["sale_id"]
        dlg = SaleDetailsDialog(sale_id, self)
        dlg.exec()
        self.refresh_data()

    def _zero_selected_simurg_debt(self) -> None:
        row = self.simurg_table.currentRow()
        if not (0 <= row < len(self.simurg_rows)):
            show_toast(self, "Nollamak üçin tablisadan çek saýlaň.", kind="info")
            return
        r = self.simurg_rows[row]
        if r["remaining_debt"] <= 0:
            show_toast(self, "Bu çek boýunça açyk bergi ýok.", kind="info")
            return

        reason, ok = QInputDialog.getText(
            self,
            "Bergini kassasyz nollamak",
            f"Çek: {r['receipt_number']} ({money_str(r['remaining_debt'])} {r['currency']})\n\nBellik / sebäp:",
            text=f"Simurg bergisi nollandy ({r['receipt_number']})",
        )
        if not ok:
            return
        try:
            with SessionLocal() as session, session.begin():
                FinanceService.settle_or_zero_customer_debt(
                    session, r["sale_id"], with_cash=False, reason=reason.strip()
                )
            self.refresh_data()
            show_toast(self, "Bergi üstünlikli nollandy (0.00).", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _zero_cash_dialog(self) -> None:
        rate = SettingsService.get_default_exchange_rate()
        with SessionLocal() as session:
            bal = FinanceService.get_register_balances(session)

        options = [
            f"Kassa TMT ({bal['tmt_balance']:,.2f} TMT)",
            f"Kassa USD (${bal['usd_balance']:,.2f} USD)",
            "Iki kassany hem nolla (USD + TMT)",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Kassany nollamak / Pul almak",
            "Haýsy kassany nollamaly (0.00 etmeli)?",
            options,
            0,
            False,
        )
        if not ok or not choice:
            return

        reason, ok_r = QInputDialog.getText(
            self,
            "Sebäp / Bellik",
            "Kassany nollamagyň (pul almagyň) sebäbini ýazyň:",
            text="Kassadan pul almak / nollamak",
        )
        if not ok_r or not reason.strip():
            return

        targets = ["TMT", "USD"] if "Iki kassany" in choice else (["USD"] if "Kassa USD" in choice else ["TMT"])
        try:
            cleared = []
            with SessionLocal() as session, session.begin():
                for cur in targets:
                    amt = FinanceService.zero_cash_register(session, cur, rate, reason.strip())
                    cleared.append(f"{cur}: {amt:,.2f}")
            self.refresh_data()
            show_toast(self, "Kassa nollandy (" + " | ".join(cleared) + ").", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _settle_selected_supplier_debt(self, with_cash: bool) -> None:
        row = self.sup_table.currentRow()
        if not (0 <= row < len(self.supplier_rows)):
            show_toast(self, "Tablisadan alyş setirini saýlaň.", kind="info")
            return
        r = self.supplier_rows[row]
        purchase_id = r["purchase_id"]
        if r["store_debt_to_supplier"] <= 0:
            show_toast(self, "Bu alyş boýunça açyk bergi ýok.", kind="info")
            return

        amount = r["store_debt_to_supplier"]
        action_title = "Bergini kassa bilen doly ýapmak" if with_cash else "Bergini kassasyz nollamak"
        default_reason = (
            f"Alyş №{purchase_id} doly hasaplaşyk"
            if with_cash
            else f"Alyş №{purchase_id} bergisi nollandy"
        )
        reason, ok = QInputDialog.getText(
            self,
            action_title,
            f"Dükanyň üpjün edijä bergisi ({amount:,.2f} {r['currency']})\n"
            f"Alyş №{purchase_id} ({r['supplier_name']})\n\nBellik / sebäp:",
            text=default_reason,
        )
        if not ok:
            return
        try:
            with SessionLocal() as session, session.begin():
                FinanceService.settle_or_zero_supplier_debt(
                    session, purchase_id, with_cash=with_cash, reason=reason.strip()
                )
            self.refresh_data()
            show_toast(self, "Üpjün ediji bergisi üstünlikli ýapyldy (0.00).", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _storno_selected_movement(self) -> None:
        row = self.journal_table.currentRow()
        if not (0 <= row < len(self.journal_entries)):
            show_toast(self, "Storno üçin maliýe žurnalyndan setir saýlaň.", kind="info")
            return
        entry = self.journal_entries[row]
        dlg = CashAdjustmentDialog(reference_entry=entry, parent=self)
        if dlg.exec():
            self.refresh_data()

    def _open_selected_journal_doc(self) -> None:
        row = self.journal_table.currentRow()
        if not (0 <= row < len(self.journal_entries)):
            show_toast(self, "Maliýe žurnalyndan ýazgy saýlaň.", kind="info")
            return
        entry = self.journal_entries[row]
        if entry["doc_type"] in ("sale", "purchase") and entry["doc_id"]:
            self._open_journal_document(row, 0)
        else:
            show_toast(self, "Bu amal çeke ýa-da alyşa bagly däl.", kind="info")

    def _open_journal_document(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self.journal_entries)):
            return
        entry = self.journal_entries[row]
        if entry["doc_type"] == "sale" and entry["doc_id"]:
            dlg = SaleDetailsDialog(entry["doc_id"], self)
            dlg.exec()
            self.refresh_data()
        elif entry["doc_type"] == "purchase" and entry["doc_id"]:
            dlg = PurchaseDetailsDialog(entry["doc_id"], self)
            dlg.exec()
            self.refresh_data()

    def _open_selected_supplier_purchase(self) -> None:
        row = self.sup_table.currentRow()
        if not (0 <= row < len(self.supplier_rows)):
            show_toast(self, "Üpjün edijiler tablisasyndan alyş setirini saýlaň.", kind="info")
            return
        purchase_id = self.supplier_rows[row]["purchase_id"]
        dlg = PurchaseDetailsDialog(purchase_id, self)
        dlg.exec()
        self.refresh_data()
