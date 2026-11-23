from datetime import date, datetime, time
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
from app.ui.widgets import Card, configure_table, make_button, money_str, style_combo


class ExpenseDialog(QDialog):
    """Окно регистрации операционного расхода магазина."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Çykdajy hasaba almak")
        self.setMinimumWidth(440)
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
        self.rate_spin.setValue(19.5)
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
        cancel_btn = QPushButton("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Çykdajyny ýatda sakla")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

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
            QMessageBox.information(self, "Taýýar", "Çykdajy üstünlikli hasaba alyndy.")
            self.accept()
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))


class CashAdjustmentDialog(QDialog):
    """Окно создания корректирующей / сторнирующей кассовой записи (Раздел 5.7)."""

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
        self.rate_spin.setValue(19.5)
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
        cancel_btn = QPushButton("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Düzedişi geçir")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

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
            QMessageBox.information(self, "Taýýar", "Düzediş ýazgysy üstünlikli döredildi.")
            self.accept()
        except (ValueError, TypeError, SQLAlchemyError) as e:
            QMessageBox.warning(self, "Ýalňyşlyk", str(e))


class ShiftCloseDialog(QDialog):
    """Окно закрытия смены (Z-отчёт) и сверки фактической и расчётной кассы USD/TMT."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smenany ýapmak we kassa barlagy (Z-hasabat)")
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.STYLE)

        self._load_shift_stats()
        self._build_ui()
        self._recalculate_diff()

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

        title = QLabel("Smenany ýapmak we nagt pul barlagy")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        summary = QLabel(
            f"Şu günki çekler: <b>{self.receipts_count}</b>   |   "
            f"Jemi peýda: <b>${money_str(self.profit_usd)} USD / {money_str(self.profit_tmt)} TMT</b>\n"
            f"Smena girdejisi: +${money_str(self.usd_income)} USD / +{money_str(self.tmt_income)} TMT   |   "
            f"Smena çykdajysy: −${money_str(self.usd_expense)} USD / −{money_str(self.tmt_expense)} TMT"
        )
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        root.addWidget(summary)

        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(14)

        grid.addWidget(QLabel("<b>Kassa walýutasy</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Hasaplanan galyndy</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Kassada hakyky</b>"), 0, 2)
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

        root.addLayout(grid)

        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        root.addWidget(self.status_banner)

        footer = QHBoxLayout()
        self.adjust_btn = make_button("⚖ Kassany hakyky pul boýunça deňle")
        self.adjust_btn.clicked.connect(self._apply_reconciliation)
        footer.addWidget(self.adjust_btn)

        pdf_btn = make_button("🖨 Z-hasabaty PDF-de ýatda sakla", "primary")
        pdf_btn.clicked.connect(self._export_pdf)
        footer.addWidget(pdf_btn)

        footer.addStretch()
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _recalculate_diff(self) -> None:
        act_usd = Decimal(f"{self.actual_usd_spin.value():.2f}")
        act_tmt = Decimal(f"{self.actual_tmt_spin.value():.2f}")
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
                "«Kassany hakyky pul boýunça deňle» düwmesi bilen awtomatiki düzediş ýazgysyny döredip bilersiňiz."
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

        rate = SettingsService.get_default_exchange_rate()
        try:
            with SessionLocal() as session:
                if diff_usd != 0:
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_usd > 0 else "expense",
                        amount=abs(diff_usd),
                        currency="USD",
                        exchange_rate=rate,
                        reason="Smena ýapylanda kassa barlagy",
                    )
                if diff_tmt != 0:
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_tmt > 0 else "expense",
                        amount=abs(diff_tmt),
                        currency="TMT",
                        exchange_rate=rate,
                        reason="Smena ýapylanda kassa barlagy",
                    )
                session.commit()
            self._load_shift_stats()
            self.exp_usd_lbl.setText(f"${money_str(self.usd_expected)}")
            self.exp_tmt_lbl.setText(f"{money_str(self.tmt_expected)} m.")
            self._recalculate_diff()
            QMessageBox.information(self, "Kassa deňlendi", "Kassa balansy hakyky galyndy boýunça deňlendi.")
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


class CashCountDialog(QDialog):
    """Калькулятор пересчёта всей кассы по номиналам купюр (TMT и USD) с общим итогом по курсу."""

    TMT_DENOMS = (500, 100, 50, 20, 10, 5, 1)
    USD_DENOMS = (100, 50, 20, 10, 5, 1)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kassany sana (kupýura kalkulýatory)")
        self.setMinimumWidth(680)
        self.setStyleSheet(theme.STYLE)

        self.tmt_spins: dict[int, QSpinBox] = {}
        self.usd_spins: dict[int, QSpinBox] = {}
        self.expected_tmt = Decimal("0.00")
        self.expected_usd = Decimal("0.00")

        with SessionLocal() as session:
            bal = FinanceService.get_register_balances(session)
            self.expected_tmt = bal["tmt_balance"]
            self.expected_usd = bal["usd_balance"]

        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QSpinBox

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("🧮 Kassadaky ähli puly sanamak (TMT + USD)")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Hasaplama kursy (1 USD = X TMT):"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.valueChanged.connect(self._recalculate)
        rate_row.addWidget(self.rate_spin)
        rate_row.addStretch()

        clear_btn = make_button("Arassala")
        clear_btn.clicked.connect(self._clear_all)
        rate_row.addWidget(clear_btn)
        root.addLayout(rate_row)

        cols = QHBoxLayout()
        cols.setSpacing(16)

        # TMT kupýuralar
        tmt_card = Card(margins=(14, 12, 14, 12), spacing=8)
        t_head = QLabel(f"TMT kupýuralar (programmadaky: {self.expected_tmt:,.2f} TMT)")
        t_head.setObjectName("cardTitle")
        tmt_card.body.addWidget(t_head)

        t_grid = QGridLayout()
        t_grid.setSpacing(6)
        for row_idx, denom in enumerate(self.TMT_DENOMS):
            t_grid.addWidget(QLabel(f"{denom} TMT  ×"), row_idx, 0)
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setMinimumHeight(30)
            sp.valueChanged.connect(self._recalculate)
            self.tmt_spins[denom] = sp
            t_grid.addWidget(sp, row_idx, 1)
        t_grid.addWidget(QLabel("Goşmaça / teňňe:"), len(self.TMT_DENOMS), 0)
        self.tmt_extra = QDoubleSpinBox()
        self.tmt_extra.setRange(0, 10000000)
        self.tmt_extra.setDecimals(2)
        self.tmt_extra.valueChanged.connect(self._recalculate)
        t_grid.addWidget(self.tmt_extra, len(self.TMT_DENOMS), 1)
        tmt_card.body.addLayout(t_grid)

        self.tmt_total_lbl = QLabel("Jemi TMT: 0.00")
        self.tmt_total_lbl.setStyleSheet(f"font-weight: 700; font-size: 11pt; color: {theme.TEAL};")
        tmt_card.body.addWidget(self.tmt_total_lbl)
        cols.addWidget(tmt_card, 1)

        # USD kupýuralar
        usd_card = Card(margins=(14, 12, 14, 12), spacing=8)
        u_head = QLabel(f"USD kupýuralar (programmadaky: ${self.expected_usd:,.2f})")
        u_head.setObjectName("cardTitle")
        usd_card.body.addWidget(u_head)

        u_grid = QGridLayout()
        u_grid.setSpacing(6)
        for row_idx, denom in enumerate(self.USD_DENOMS):
            u_grid.addWidget(QLabel(f"${denom} USD  ×"), row_idx, 0)
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setMinimumHeight(30)
            sp.valueChanged.connect(self._recalculate)
            self.usd_spins[denom] = sp
            u_grid.addWidget(sp, row_idx, 1)
        u_grid.addWidget(QLabel("Goşmaça / sent:"), len(self.USD_DENOMS), 0)
        self.usd_extra = QDoubleSpinBox()
        self.usd_extra.setRange(0, 10000000)
        self.usd_extra.setDecimals(2)
        self.usd_extra.valueChanged.connect(self._recalculate)
        u_grid.addWidget(self.usd_extra, len(self.USD_DENOMS), 1)
        usd_card.body.addLayout(u_grid)

        self.usd_total_lbl = QLabel("Jemi USD: $0.00")
        self.usd_total_lbl.setStyleSheet(f"font-weight: 700; font-size: 11pt; color: {theme.NAVY};")
        usd_card.body.addWidget(self.usd_total_lbl)
        cols.addWidget(usd_card, 1)

        root.addLayout(cols)

        summary_card = Card(margins=(16, 12, 16, 12), spacing=6)
        self.grand_total_lbl = QLabel()
        self.grand_total_lbl.setStyleSheet(f"font-size: 13pt; font-weight: 800; color: {theme.NAVY};")
        self.diff_lbl = QLabel()
        self.diff_lbl.setWordWrap(True)
        summary_card.body.addWidget(self.grand_total_lbl)
        summary_card.body.addWidget(self.diff_lbl)
        root.addWidget(summary_card)

        footer = QHBoxLayout()
        self.apply_btn = make_button("⚖ Kassany sanalan pula deňle", "primary")
        self.apply_btn.clicked.connect(self._apply_counted_to_registers)
        footer.addWidget(self.apply_btn)
        footer.addStretch()
        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _clear_all(self) -> None:
        for sp in (*self.tmt_spins.values(), *self.usd_spins.values()):
            sp.setValue(0)
        self.tmt_extra.setValue(0.0)
        self.usd_extra.setValue(0.0)

    def _get_totals(self) -> tuple[Decimal, Decimal, Decimal]:
        tmt_sum = sum(Decimal(d) * sp.value() for d, sp in self.tmt_spins.items()) + Decimal(f"{self.tmt_extra.value():.2f}")
        usd_sum = sum(Decimal(d) * sp.value() for d, sp in self.usd_spins.items()) + Decimal(f"{self.usd_extra.value():.2f}")
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        return tmt_sum.quantize(Decimal("0.01")), usd_sum.quantize(Decimal("0.01")), rate

    def _recalculate(self) -> None:
        tmt_sum, usd_sum, rate = self._get_totals()
        total_in_tmt = (tmt_sum + usd_sum * rate).quantize(Decimal("0.01"))
        total_in_usd = (usd_sum + (tmt_sum / rate)).quantize(Decimal("0.01"))

        diff_tmt = tmt_sum - self.expected_tmt
        diff_usd = usd_sum - self.expected_usd

        self.tmt_total_lbl.setText(f"Sanalan TMT: {tmt_sum:,.2f} TMT  (tapawut: {diff_tmt:+,.2f})")
        self.usd_total_lbl.setText(f"Sanalan USD: ${usd_sum:,.2f} USD  (tapawut: {diff_usd:+,.2f})")
        self.grand_total_lbl.setText(
            f"JEMI SANALAN KASSA:   {total_in_tmt:,.2f} TMT   •   ${total_in_usd:,.2f} USD"
        )

        sys_total_tmt = (self.expected_tmt + self.expected_usd * rate).quantize(Decimal("0.01"))
        total_diff_tmt = total_in_tmt - sys_total_tmt
        self.diff_lbl.setText(
            f"Programmadaky jemi kassa: {sys_total_tmt:,.2f} TMT   |   "
            f"Jemi tapawut: {total_diff_tmt:+,.2f} TMT"
        )
        self.apply_btn.setEnabled(diff_tmt != Decimal("0.00") or diff_usd != Decimal("0.00"))

    def _apply_counted_to_registers(self) -> None:
        tmt_sum, usd_sum, rate = self._get_totals()
        diff_tmt = tmt_sum - self.expected_tmt
        diff_usd = usd_sum - self.expected_usd
        ans = QMessageBox.question(
            self,
            "Kassany deňlemek",
            f"Kassa balanslaryny sanalan pula deňlemelimi?\n"
            f"• TMT düzedişi: {diff_tmt:+,.2f} TMT (täze balans: {tmt_sum:,.2f})\n"
            f"• USD düzedişi: {diff_usd:+,.2f} USD (täze balans: ${usd_sum:,.2f})",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            with SessionLocal() as session, session.begin():
                if diff_tmt != Decimal("0.00"):
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_tmt > 0 else "expense",
                        amount=abs(diff_tmt),
                        currency="TMT",
                        exchange_rate=rate,
                        reason="Kupýura sanawy boýunça kassa deňlemesi",
                    )
                if diff_usd != Decimal("0.00"):
                    FinanceService.record_cash_adjustment(
                        session=session,
                        direction="income" if diff_usd > 0 else "expense",
                        amount=abs(diff_usd),
                        currency="USD",
                        exchange_rate=rate,
                        reason="Kupýura sanawy boýunça kassa deňlemesi",
                    )
            self.expected_tmt = tmt_sum
            self.expected_usd = usd_sum
            self._recalculate()
            QMessageBox.information(self, "Taýýar", "Kassa balanslary sanalan pula deňlendi.")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))


class FinancePage(QWidget):
    """Страница «Финансы»: балансы касс, 4 категории долгов, журнал транзакций, расчеты с клиентами и поставщиками."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.journal_entries: list[dict] = []
        self.customer_rows: list[dict] = []
        self.supplier_rows: list[dict] = []

        self._build_ui()
        self.refresh_data()

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
            "USD we TMT aýratyn hasaby • Kassalar, müşderi we üpjün ediji bergileri, hereketler žurnaly"
        )
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        expense_btn = make_button("+ Çykdajy ýaz")
        expense_btn.clicked.connect(self._open_expense_dialog)
        header.addWidget(expense_btn)

        adjust_btn = make_button("Düzediş / Storno")
        adjust_btn.clicked.connect(self._open_adjustment_dialog)
        header.addWidget(adjust_btn)

        count_btn = make_button("🧮 Kassany sana")
        count_btn.clicked.connect(self._open_cash_count_dialog)
        header.addWidget(count_btn)

        zero_cash_btn = make_button("🧹 Kassany nolla", "danger")
        zero_cash_btn.clicked.connect(self._zero_cash_dialog)
        header.addWidget(zero_cash_btn)

        shift_btn = make_button("🔒 Smenany ýapmak / Barlag")
        shift_btn.clicked.connect(self._open_shift_close_dialog)
        header.addWidget(shift_btn)

        refresh_btn = make_button("↻ Täzele", "primary")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        self.combined_cash_banner = QLabel("Jemi kassa (ähli walýutalar): 0.00 TMT  •  $0.00 USD")
        self.combined_cash_banner.setStyleSheet(
            f"background: #EFF6FF; color: {theme.NAVY}; border: 1px solid #BFDBFE; "
            "border-radius: 8px; padding: 8px 14px; font-weight: 700; font-size: 10.5pt;"
        )
        root.addWidget(self.combined_cash_banner)

        cards_grid = QGridLayout()
        cards_grid.setSpacing(12)

        self.usd_cash_label = QLabel("0.00 USD")
        self.usd_flow_label = QLabel("Girdeji: 0.00 | Çykdajy: 0.00")
        cards_grid.addWidget(
            self._build_metric_card(
                "Kassa balansy USD",
                self.usd_cash_label,
                self.usd_flow_label,
                theme.NAVY,
            ),
            0,
            0,
        )

        self.tmt_cash_label = QLabel("0.00 TMT")
        self.tmt_flow_label = QLabel("Girdeji: 0.00 | Çykdajy: 0.00")
        cards_grid.addWidget(
            self._build_metric_card(
                "Kassa balansy TMT",
                self.tmt_cash_label,
                self.tmt_flow_label,
                theme.TEAL,
            ),
            0,
            1,
        )

        self.cust_debt_val = QLabel("USD: 0.00 | TMT: 0.00")
        self.cust_debt_sub = QLabel("Müşderileriň dükana bergisi (satyşlar)")
        cards_grid.addWidget(
            self._build_metric_card(
                "1. Müşderileriň dükana bergisi",
                self.cust_debt_val,
                self.cust_debt_sub,
                theme.ACCENT,
                small_value=True,
            ),
            0,
            2,
        )

        self.sup_payable_val = QLabel("USD: 0.00 | TMT: 0.00")
        self.sup_payable_sub = QLabel("Dükanyň üpjün edijilere bergisi (alyşlar)")
        cards_grid.addWidget(
            self._build_metric_card(
                "2. Dükanyň üpjün edijilere bergisi",
                self.sup_payable_val,
                self.sup_payable_sub,
                theme.RED,
                small_value=True,
            ),
            1,
            0,
        )

        self.store_to_cust_val = QLabel("USD: 0.00 | TMT: 0.00")
        self.store_to_cust_sub = QLabel("Dükanyň müşderilere bergisi (satyş ýatyrma)")
        cards_grid.addWidget(
            self._build_metric_card(
                "3. Dükanyň müşderilere bergisi",
                self.store_to_cust_val,
                self.store_to_cust_sub,
                "#7C3AED",
                small_value=True,
            ),
            1,
            1,
        )

        self.sup_to_store_val = QLabel("USD: 0.00 | TMT: 0.00")
        self.sup_to_store_sub = QLabel("Üpjün edijileriň dükana bergisi (alyş ýatyrma)")
        cards_grid.addWidget(
            self._build_metric_card(
                "4. Üpjün edijileriň dükana bergisi",
                self.sup_to_store_val,
                self.sup_to_store_sub,
                theme.BLUE,
                small_value=True,
            ),
            1,
            2,
        )

        root.addLayout(cards_grid)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_journal_tab(), "Maliýe amallary žurnaly")
        self.tabs.addTab(self._create_customer_debts_tab(), "Müşderiler bilen hasaplaşyk")
        self.tabs.addTab(self._create_supplier_debts_tab(), "Üpjün edijiler bilen hasaplaşyk")
        root.addWidget(self.tabs, 1)

    def _build_metric_card(
        self,
        title: str,
        value_label: QLabel,
        sub_label: QLabel,
        color: str,
        small_value: bool = False,
    ) -> Card:
        card = Card(margins=(16, 12, 16, 12), spacing=4)
        t = QLabel(title)
        t.setObjectName("mutedText")
        font_sz = "13.5pt" if small_value else "17pt"
        value_label.setStyleSheet(f"font-size: {font_sz}; font-weight: 700; color: {color};")
        sub_label.setStyleSheet(f"font-size: 8.5pt; color: {theme.MUTED};")
        card.body.addWidget(t)
        card.body.addWidget(value_label)
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
        self.journal_type_combo.addItem("Müşderiniň bergi tölegi", "customer_debt_payment")
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
            "ID",
            "Sene",
            "Ugur",
            "Amal görnüşi",
            "Jemi",
            "Walýuta",
            "Kurs",
            "Resminama",
            "Bellik",
        ])
        configure_table(self.journal_table)
        self.journal_table.horizontalHeader().setSectionResizeMode(
            8, QHeaderView.ResizeMode.Stretch
        )
        self.journal_table.cellDoubleClicked.connect(self._open_journal_document)
        layout.addWidget(self.journal_table, 1)

        self.period_summary_label = QLabel()
        self.period_summary_label.setObjectName("mutedText")
        layout.addWidget(self.period_summary_label)

        return widget

    def _create_customer_debts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.cust_filter_combo = style_combo(QComboBox())
        self.cust_filter_combo.addItem("Ähli açyk bergiler", "open")
        self.cust_filter_combo.addItem("Diňe müşderileriň dükana bergisi", "customer_owes_store")
        self.cust_filter_combo.addItem("Diňe dükanyň müşderilere bergisi (ýatyrma)", "store_owes_customer")
        self.cust_filter_combo.addItem("Ähli çekler (ýapylanlar bilen)", "all")
        self.cust_filter_combo.currentIndexChanged.connect(self._load_customer_receivables)
        top.addWidget(self.cust_filter_combo)

        self.cust_search = QLineEdit()
        self.cust_search.setPlaceholderText("Müşderi, telefon ýa-da çek belgisi boýunça gözleg...")
        self.cust_search.setClearButtonEnabled(True)
        self.cust_search.textChanged.connect(self._load_customer_receivables)
        top.addWidget(self.cust_search, 1)

        open_btn = QPushButton("Çeki aç / Töleg kabul et")
        open_btn.setObjectName("primaryBtn")
        open_btn.clicked.connect(self._open_selected_customer_sale)
        top.addWidget(open_btn)

        pay_full_btn = make_button("✔ Doly hasaplaş (kassa)")
        pay_full_btn.clicked.connect(lambda: self._settle_selected_customer_debt(with_cash=True))
        top.addWidget(pay_full_btn)

        zero_debt_btn = make_button("🧹 Bergini nolla", "danger")
        zero_debt_btn.clicked.connect(lambda: self._settle_selected_customer_debt(with_cash=False))
        top.addWidget(zero_debt_btn)

        layout.addLayout(top)

        self.cust_table = QTableWidget(0, 9)
        self.cust_table.setHorizontalHeaderLabels([
            "ID",
            "Çek",
            "Sene",
            "Müşderi",
            "Walýuta (Kurs)",
            "Çekiň jemi",
            "Tölendi",
            "Müşderiniň bergisi",
            "Dükanyň müşderä bergisi",
        ])
        configure_table(self.cust_table)
        self.cust_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.cust_table.cellDoubleClicked.connect(
            lambda _r, _c: self._open_selected_customer_sale()
        )
        layout.addWidget(self.cust_table, 1)

        return widget

    def _create_supplier_debts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.sup_filter_combo = style_combo(QComboBox())
        self.sup_filter_combo.addItem("Ähli açyk bergiler", "open")
        self.sup_filter_combo.addItem("Diňe dükanyň üpjün edijilere bergisi", "store_owes_supplier")
        self.sup_filter_combo.addItem("Diňe üpjün edijileriň dükana bergisi (ýatyrma)", "supplier_owes_store")
        self.sup_filter_combo.addItem("Ähli alyşlar (ýapylanlar bilen)", "all")
        self.sup_filter_combo.currentIndexChanged.connect(self._load_supplier_payables)
        top.addWidget(self.sup_filter_combo)

        self.sup_search = QLineEdit()
        self.sup_search.setPlaceholderText("Üpjün ediji ýa-da alyş № boýunça gözleg...")
        self.sup_search.setClearButtonEnabled(True)
        self.sup_search.textChanged.connect(self._load_supplier_payables)
        top.addWidget(self.sup_search, 1)

        open_btn = QPushButton("Alyşy aç / Töle / Gaýtarma")
        open_btn.setObjectName("primaryBtn")
        open_btn.clicked.connect(self._open_selected_supplier_purchase)
        top.addWidget(open_btn)

        pay_sup_btn = make_button("✔ Doly hasaplaş (kassa)")
        pay_sup_btn.clicked.connect(lambda: self._settle_selected_supplier_debt(with_cash=True))
        top.addWidget(pay_sup_btn)

        zero_sup_btn = make_button("🧹 Bergini nolla", "danger")
        zero_sup_btn.clicked.connect(lambda: self._settle_selected_supplier_debt(with_cash=False))
        top.addWidget(zero_sup_btn)

        layout.addLayout(top)

        self.sup_table = QTableWidget(0, 8)
        self.sup_table.setHorizontalHeaderLabels([
            "Alyş №",
            "Sene",
            "Üpjün ediji",
            "Walýuta (Kurs)",
            "Alyş jemi",
            "Tölendi",
            "Dükanyň üpjün edijä bergisi",
            "Üpjün edijiniň dükana bergisi",
        ])
        configure_table(self.sup_table)
        self.sup_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.sup_table.cellDoubleClicked.connect(
            lambda _r, _c: self._open_selected_supplier_purchase()
        )
        layout.addWidget(self.sup_table, 1)

        return widget

    def refresh_data(self) -> None:
        rate = SettingsService.get_default_exchange_rate()
        with SessionLocal() as session:
            balances = FinanceService.get_register_balances(session)
            combined = FinanceService.get_combined_cash_totals(session, rate)
            debts = FinanceService.get_all_outstanding_balances(session)
            flow = FinanceService.get_period_cash_summary(session)
            session.commit()

        self.combined_cash_banner.setText(
            f"💰 Jemi kassa (USD + TMT, kurs {combined['exchange_rate']:.4f}):   "
            f"{combined['total_in_tmt']:,.2f} TMT   •   ${combined['total_in_usd']:,.2f} USD"
        )

        self.usd_cash_label.setText(f"${balances['usd_balance']:,.2f} USD")
        self.usd_flow_label.setText(
            f"Jemi girdeji: +${flow['USD']['income']:,.2f} | Çykdajy: −${flow['USD']['expense']:,.2f}"
        )

        self.tmt_cash_label.setText(f"{balances['tmt_balance']:,.2f} TMT")
        self.tmt_flow_label.setText(
            f"Jemi girdeji: +{flow['TMT']['income']:,.2f} m. | Çykdajy: −{flow['TMT']['expense']:,.2f} m."
        )

        cd = debts["customer_debts"]
        self.cust_debt_val.setText(f"USD: ${cd['USD']:,.2f}  |  TMT: {cd['TMT']:,.2f} m.")

        sp = debts["supplier_payables"]
        self.sup_payable_val.setText(f"USD: ${sp['USD']:,.2f}  |  TMT: {sp['TMT']:,.2f} m.")

        stc = debts["store_debts_to_customers"]
        self.store_to_cust_val.setText(f"USD: ${stc['USD']:,.2f}  |  TMT: {stc['TMT']:,.2f} m.")

        sts = debts["supplier_debts_to_store"]
        self.sup_to_store_val.setText(f"USD: ${sts['USD']:,.2f}  |  TMT: {sts['TMT']:,.2f} m.")

        self._load_journal()
        self._load_customer_receivables()
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
            f"TMT: Girdeji +{t['income']:,.2f} m., Çykdajy −{t['expense']:,.2f} m., Arassa akym: {t['net']:,.2f} m. "
            "(Bagly resminamany açmak üçin setiri iki gezek basyň)"
        )

    def _load_customer_receivables(self, *_args) -> None:
        mode = self.cust_filter_combo.currentData()
        query = self.cust_search.text().strip().lower()

        with SessionLocal() as session:
            all_rows = FinanceService.get_customer_receivables_list(
                session=session,
                include_paid=(mode == "all"),
            )

        filtered = []
        for r in all_rows:
            if mode == "customer_owes_store" and r["remaining_customer_debt"] <= 0:
                continue
            if mode == "store_owes_customer" and r["store_debt_to_customer"] <= 0:
                continue
            if query:
                hay = f"{r['receipt_number']} {r['customer_name']} {r['customer_phone']}".lower()
                if query not in hay:
                    continue
            filtered.append(r)

        self.customer_rows = filtered
        self.cust_table.setRowCount(len(filtered))
        for i, r in enumerate(filtered):
            cust_str = r["customer_name"]
            if r["customer_phone"]:
                cust_str += f" ({r['customer_phone']})"
            date_str = r["sale_date"].strftime("%d.%m.%Y %H:%M") if r["sale_date"] else "—"
            vals = [
                str(r["sale_id"]),
                r["receipt_number"],
                date_str,
                cust_str,
                f"{r['currency']} ({r['exchange_rate']:,.2f})",
                money_str(r["original_amount"]),
                money_str(r["paid_amount"]),
                money_str(r["remaining_customer_debt"]),
                money_str(r["store_debt_to_customer"]),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 4, 5, 6, 7, 8):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 7 and r["remaining_customer_debt"] > 0:
                    cell.setForeground(QColor(theme.ACCENT))
                if c == 8 and r["store_debt_to_customer"] > 0:
                    cell.setForeground(QColor(theme.RED))
                self.cust_table.setItem(i, c, cell)

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
            if mode == "store_owes_supplier" and r["store_debt_to_supplier"] <= 0:
                continue
            if mode == "supplier_owes_store" and r["supplier_debt_to_store"] <= 0:
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
                money_str(r["supplier_debt_to_store"]),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 3, 4, 5, 6, 7):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 6 and r["store_debt_to_supplier"] > 0:
                    cell.setForeground(QColor(theme.RED))
                if c == 7 and r["supplier_debt_to_store"] > 0:
                    cell.setForeground(QColor(theme.BLUE))
                self.sup_table.setItem(i, c, cell)

    def _open_expense_dialog(self) -> None:
        dlg = ExpenseDialog(self)
        if dlg.exec():
            self.refresh_data()

    def _open_adjustment_dialog(self) -> None:
        dlg = CashAdjustmentDialog(parent=self)
        if dlg.exec():
            self.refresh_data()

    def _open_shift_close_dialog(self) -> None:
        dlg = ShiftCloseDialog(parent=self)
        dlg.exec()
        self.refresh_data()

    def _open_cash_count_dialog(self) -> None:
        dlg = CashCountDialog(parent=self)
        dlg.exec()
        self.refresh_data()

    def _zero_cash_dialog(self) -> None:
        from PySide6.QtWidgets import QInputDialog

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
            QMessageBox.information(
                self,
                "Kassa nollandy",
                "Kassa balansy 0.00 edildi.\n" + "\n".join(cleared),
            )
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _settle_selected_customer_debt(self, with_cash: bool) -> None:
        from PySide6.QtWidgets import QInputDialog

        row = self.cust_table.currentRow()
        if not (0 <= row < len(self.customer_rows)):
            QMessageBox.information(
                self,
                "Çek saýlaň",
                "Hasaplaşmak ýa-da nollamak üçin tablisadan çek setirini saýlaň.",
            )
            return
        r = self.customer_rows[row]
        sale_id = r["sale_id"]
        is_store_debt = r["store_debt_to_customer"] > 0
        is_cust_debt = r["remaining_customer_debt"] > 0

        if not is_store_debt and not is_cust_debt:
            QMessageBox.information(self, "Bergi ýok", "Bu çek boýunça açyk bergi ýok.")
            return

        amount = r["store_debt_to_customer"] if is_store_debt else r["remaining_customer_debt"]
        label = (
            f"Dükanyň müşderä bergisi ({amount:,.2f} {r['currency']})"
            if is_store_debt
            else f"Müşderiniň bergisi ({amount:,.2f} {r['currency']})"
        )
        action_title = "Bergini kassa bilen doly ýapmak" if with_cash else "Bergini kassasyz nollamak (öçürmek)"
        default_reason = (
            f"Doly hasaplaşyk ({r['receipt_number']})"
            if with_cash
            else f"Bergi nollandy / hasapdan öçürildi ({r['receipt_number']})"
        )

        reason, ok = QInputDialog.getText(
            self,
            action_title,
            f"{label}\nÇek: {r['receipt_number']} ({r['customer_name']})\n\nBellik / sebäp:",
            text=default_reason,
        )
        if not ok:
            return

        try:
            with SessionLocal() as session, session.begin():
                if is_store_debt:
                    FinanceService.settle_or_zero_store_debt_to_customer(
                        session, sale_id, with_cash=with_cash, reason=reason.strip()
                    )
                else:
                    FinanceService.settle_or_zero_customer_debt(
                        session, sale_id, with_cash=with_cash, reason=reason.strip()
                    )
            self.refresh_data()
            QMessageBox.information(self, "Taýýar", "Bergi üstünlikli ýapyldy (0.00).")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _settle_selected_supplier_debt(self, with_cash: bool) -> None:
        from PySide6.QtWidgets import QInputDialog

        row = self.sup_table.currentRow()
        if not (0 <= row < len(self.supplier_rows)):
            QMessageBox.information(
                self,
                "Alyş saýlaň",
                "Hasaplaşmak ýa-da nollamak üçin tablisadan alyş setirini saýlaň.",
            )
            return
        r = self.supplier_rows[row]
        purchase_id = r["purchase_id"]
        is_store_owes = r["store_debt_to_supplier"] > 0
        is_sup_owes = r["supplier_debt_to_store"] > 0

        if not is_store_owes and not is_sup_owes:
            QMessageBox.information(self, "Bergi ýok", "Bu alyş boýunça açyk bergi ýok.")
            return

        amount = r["store_debt_to_supplier"] if is_store_owes else r["supplier_debt_to_store"]
        label = (
            f"Dükanyň üpjün edijä bergisi ({amount:,.2f} {r['currency']})"
            if is_store_owes
            else f"Üpjün edijiniň dükana bergisi ({amount:,.2f} {r['currency']})"
        )
        action_title = "Bergini kassa bilen doly ýapmak" if with_cash else "Bergini kassasyz nollamak"
        default_reason = (
            f"Alyş №{purchase_id} doly hasaplaşyk"
            if with_cash
            else f"Alyş №{purchase_id} bergisi nollandy"
        )

        reason, ok = QInputDialog.getText(
            self,
            action_title,
            f"{label}\nAlyş №{purchase_id} ({r['supplier_name']})\n\nBellik / sebäp:",
            text=default_reason,
        )
        if not ok:
            return

        try:
            with SessionLocal() as session, session.begin():
                if is_store_owes:
                    FinanceService.settle_or_zero_supplier_debt(
                        session, purchase_id, with_cash=with_cash, reason=reason.strip()
                    )
                else:
                    FinanceService.settle_or_zero_supplier_refund_debt(
                        session, purchase_id, with_cash=with_cash, reason=reason.strip()
                    )
            self.refresh_data()
            QMessageBox.information(self, "Taýýar", "Üpjün ediji bergisi üstünlikli ýapyldy (0.00).")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _storno_selected_movement(self) -> None:
        row = self.journal_table.currentRow()
        if not (0 <= row < len(self.journal_entries)):
            QMessageBox.information(
                self,
                "Amal saýlaň",
                "Storno ýazgysyny döretmek üçin maliýe žurnalyndan setir saýlaň.",
            )
            return
        entry = self.journal_entries[row]
        dlg = CashAdjustmentDialog(reference_entry=entry, parent=self)
        if dlg.exec():
            self.refresh_data()

    def _open_selected_journal_doc(self) -> None:
        row = self.journal_table.currentRow()
        if not (0 <= row < len(self.journal_entries)):
            QMessageBox.information(
                self,
                "Ýazgy saýlaň",
                "Maliýe amallary žurnalyndan ýazgy saýlaň.",
            )
            return
        entry = self.journal_entries[row]
        if entry["doc_type"] in ("sale", "purchase") and entry["doc_id"]:
            self._open_journal_document(row, 0)
        else:
            QMessageBox.information(
                self,
                "Bagly resminama ýok",
                "Bu amal (çykdajy ýa-da düzediş) çeke ýa-da alyşa bagly däl.",
            )

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

    def _open_selected_customer_sale(self) -> None:
        row = self.cust_table.currentRow()
        if not (0 <= row < len(self.customer_rows)):
            QMessageBox.information(
                self,
                "Çek saýlaň",
                "Müşderiler bilen hasaplaşyk tablisasyndan çek setirini saýlaň.",
            )
            return
        sale_id = self.customer_rows[row]["sale_id"]
        dlg = SaleDetailsDialog(sale_id, self)
        dlg.exec()
        self.refresh_data()

    def _open_selected_supplier_purchase(self) -> None:
        row = self.sup_table.currentRow()
        if not (0 <= row < len(self.supplier_rows)):
            QMessageBox.information(
                self,
                "Alyş saýlaň",
                "Üpjün edijiler bilen hasaplaşyk tablisasyndan alyş setirini saýlaň.",
            )
            return
        purchase_id = self.supplier_rows[row]["purchase_id"]
        dlg = PurchaseDetailsDialog(purchase_id, self)
        dlg.exec()
        self.refresh_data()
