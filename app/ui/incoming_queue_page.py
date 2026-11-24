"""Kabul ediş nobaty (Incoming Queue) sahypasy — mobil skanerden gelen harytlary we telefonlary sklada geçirmek."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.repositories.product_repository import (
    is_system_category_code,
    list_categories,
    list_distinct_brands_and_models,
    list_distinct_phone_models,
)
from app.services.accessory_matcher import build_draft_suggestion, parse_box_ocr
from app.services.incoming_queue_service import (
    clear_queue,
    commit_known_items,
    commit_phone_item,
    commit_unknown_item,
    delete_queue_item,
    list_queue_items,
    update_queue_item,
)
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_dialog import CategoryDialog
from app.ui.widgets import (
    Card,
    configure_dialog_buttons,
    configure_table,
    make_button,
    money_str,
    show_toast,
    style_combo,
)


def _format_scanner_time(device_name: str, created_at: datetime | None) -> str:
    dev = (device_name or "").strip() or "Skaner"
    if isinstance(created_at, datetime):
        t_str = created_at.strftime("%d.%m %H:%M")
        return f"{dev} • {t_str}"
    return dev


class _EnterActivatedTable(QTableWidget):
    """Enter/Return basylanda saýlanan setiri açýan tablisa."""

    enterActivated = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentRow() >= 0:
            self.enterActivated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class CommitUnknownItemDialog(QDialog):
    """Näbelli haryt üçin kart döretmek we sklada geçirmek penjiresi."""

    def __init__(
        self,
        item: dict[str, Any],
        supplier_name: str,
        currency: str,
        exchange_rate: Decimal,
        paid_amount: Decimal,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.supplier_name = supplier_name
        self.default_currency = currency
        self.exchange_rate = exchange_rate
        self.paid_amount = paid_amount
        self.created_product_name: str = ""
        self.committed_qty: int = 0

        self.setWindowTitle("Näbelli harydy döretmek we sklada geçirmek")
        self.setMinimumWidth(540)
        self.setStyleSheet(theme.STYLE)

        self._categories = []
        self._build_ui()
        self._load_categories()
        self._setup_completers_and_prefill()
        self.name_input.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Näbelli haryt kartyny doldurmak")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        ocr_raw = (self.item.get("ocr_raw_text") or "").strip()
        model_hint = (self.item.get("model_hint") or "").strip()
        if ocr_raw or model_hint:
            hint_box = QFrame()
            hint_box.setStyleSheet(
                f"QFrame {{ background: #F8F9FB; border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
            )
            hb_layout = QVBoxLayout(hint_box)
            hb_layout.setContentsMargins(12, 8, 12, 8)
            hb_layout.setSpacing(4)
            if ocr_raw:
                ocr_lbl = QLabel(f"<b>📷 OCR guty teksti:</b> {ocr_raw}")
                ocr_lbl.setWordWrap(True)
                ocr_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 9pt;")
                hb_layout.addWidget(ocr_lbl)
            if model_hint and model_hint != ocr_raw:
                mh_lbl = QLabel(f"<b>📝 Skaner belligi:</b> {model_hint}")
                mh_lbl.setWordWrap(True)
                mh_lbl.setStyleSheet(f"color: {theme.MUTED}; font-size: 9pt;")
                hb_layout.addWidget(mh_lbl)
            root.addWidget(hint_box)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Mysal: Blueo 9D Udarnyk iPhone 16 Pro Max")
        form.addRow("Harydyň ady *:", self.name_input)

        cat_row = QHBoxLayout()
        self.category_combo = style_combo(QComboBox())
        self.category_combo.setPlaceholderText("Kategoriýa saýlaň")
        cat_row.addWidget(self.category_combo, 1)

        add_cat_btn = make_button("+ Kategoriýa")
        add_cat_btn.setToolTip("Täze kategoriýa döretmek")
        add_cat_btn.clicked.connect(self._add_category)
        cat_row.addWidget(add_cat_btn)
        form.addRow("Kategoriýa *:", cat_row)

        self.brand_input = QLineEdit()
        self.brand_input.setPlaceholderText("Harydyň brendi (mysal: Blueo, Hoco, Remax)")
        form.addRow("Brend:", self.brand_input)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Enjam modeli (mysal: iPhone 16 Pro Max, Samsung S24)")
        form.addRow("Model:", self.model_input)

        self.reference_input = QLineEdit()
        self.reference_input.setPlaceholderText("Gutynyň üstündäki aýratyn sözler/kodlar (vergul bilen)")
        form.addRow("Referens (OCR sözler):", self.reference_input)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("EAN-13 / ştrihkod (hökmany däl)")
        form.addRow("Ştrihkod:", self.barcode_input)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1_000_000)
        self.qty_spin.setValue(max(1, int(self.item.get("quantity") or 1)))
        form.addRow("Sany *:", self.qty_spin)

        cost_row = QHBoxLayout()
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0.0, 10_000_000.0)
        self.cost_spin.setDecimals(2)
        self.cost_spin.setValue(float(self.item.get("unit_cost") or 0))
        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["USD", "TMT"])
        init_curr = (self.item.get("currency") or self.default_currency or "USD").upper()
        if init_curr in ("USD", "TMT"):
            self.currency_combo.setCurrentText(init_curr)
        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.currency_combo)
        form.addRow("Alyş bahasy:", cost_row)

        self.min_stock_spin = QSpinBox()
        self.min_stock_spin.setRange(0, 100_000)
        self.min_stock_spin.setValue(SettingsService.get_default_min_stock())
        form.addRow("Iň az galyndy:", self.min_stock_spin)

        root.addLayout(form)

        if self.supplier_name:
            sup_txt = f"Üpjün ediji: {self.supplier_name} • Kurs: {self.exchange_rate:.4f}"
        else:
            sup_txt = f"Çeşme: Şahsy çeşme (bergisiz) • Kurs: {self.exchange_rate:.4f}"
        if self.paid_amount > 0:
            sup_txt += f" • Kassadan töleg: {money_str(self.paid_amount)}"
        sup_hint = QLabel(sup_txt)
        sup_hint.setObjectName("mutedText")
        sup_hint.setWordWrap(True)
        root.addWidget(sup_hint)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("✓ Sakla we sklada geçir", "primary")
        save_btn.clicked.connect(self._save)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)

    def _load_categories(self, select_id: int | None = None) -> None:
        self.category_combo.clear()
        try:
            all_cats = list_categories(active_only=True)
        except SQLAlchemyError:
            all_cats = []
        self._categories = [c for c in all_cats if not is_system_category_code(c.code)]
        for cat in self._categories:
            self.category_combo.addItem(cat.name, cat.id)
        if select_id is not None:
            idx = self.category_combo.findData(select_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
                return
        if self.category_combo.count() > 0:
            self.category_combo.setCurrentIndex(0)

    def _add_category(self) -> None:
        dlg = CategoryDialog(self)
        if dlg.exec():
            new_id = getattr(dlg, "created_category_id", None)
            self._load_categories(select_id=new_id)

    def _setup_completers_and_prefill(self) -> None:
        try:
            brands, models = list_distinct_brands_and_models()
        except SQLAlchemyError:
            brands, models = [], []

        brand_completer = QCompleter(brands, self)
        brand_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        brand_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.brand_input.setCompleter(brand_completer)

        model_completer = QCompleter(models, self)
        model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.model_input.setCompleter(model_completer)

        self.barcode_input.setText((self.item.get("barcode") or "").strip())

        ocr_raw = (self.item.get("ocr_raw_text") or "").strip()
        model_hint = (self.item.get("model_hint") or "").strip()
        source_text = ocr_raw or model_hint
        if source_text:
            parsed = parse_box_ocr(source_text, catalog_brands=brands)
            draft = build_draft_suggestion(parsed, self._categories)
            if draft.get("name"):
                self.name_input.setText(str(draft["name"]))
            elif model_hint:
                self.name_input.setText(model_hint)
            if draft.get("brand"):
                self.brand_input.setText(str(draft["brand"]))
            if draft.get("model"):
                self.model_input.setText(str(draft["model"]))
            if draft.get("specification"):
                self.reference_input.setText(str(draft["specification"]))
            suggested_cat_id = draft.get("category_id")
            if suggested_cat_id is not None:
                idx = self.category_combo.findData(suggested_cat_id)
                if idx >= 0:
                    self.category_combo.setCurrentIndex(idx)

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Maglumatlary barlaň", "Harydyň adyny giriziň.")
            self.name_input.setFocus()
            return
        cat_id = self.category_combo.currentData()
        if cat_id is None:
            QMessageBox.warning(self, "Maglumatlary barlaň", "Kategoriýany saýlaň.")
            self.category_combo.setFocus()
            return

        qty = int(self.qty_spin.value())
        cost_dec = Decimal(f"{self.cost_spin.value():.2f}")
        curr = self.currency_combo.currentText().strip().upper() or "USD"

        try:
            commit_unknown_item(
                queue_id=int(self.item["id"]),
                name=name,
                category_id=int(cat_id),
                quantity=qty,
                unit_cost=cost_dec,
                currency=curr,
                exchange_rate=self.exchange_rate,
                brand=self.brand_input.text().strip() or None,
                model=self.model_input.text().strip() or None,
                specification=self.reference_input.text().strip() or None,
                barcode=self.barcode_input.text().strip() or None,
                min_stock=int(self.min_stock_spin.value()),
                supplier_name=self.supplier_name or None,
                paid_amount=self.paid_amount,
            )
            self.created_product_name = name
            self.committed_qty = qty
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Harydy sklada geçirip bolmady:\n{err}")


class CommitQueuedPhoneDialog(QDialog):
    """Nobatdaky telefony (IMEI) maglumatyny dolduryp sklada kabul etmek penjiresi."""

    def __init__(
        self,
        item: dict[str, Any],
        supplier_name: str,
        currency: str,
        exchange_rate: Decimal,
        paid_amount: Decimal,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.supplier_name = supplier_name
        self.default_currency = currency
        self.exchange_rate = exchange_rate
        self.paid_amount = paid_amount
        self.committed_model: str = ""
        self.committed_imei1: str = ""

        self.setWindowTitle("Telefony (IMEI) kabul etmek")
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._prefill()
        self.model_input.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Telefony (IMEI) kabul etmek")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        ocr_raw = (self.item.get("ocr_raw_text") or "").strip()
        if ocr_raw:
            ocr_box = QLabel(f"📷 OCR tekst: {ocr_raw}")
            ocr_box.setWordWrap(True)
            ocr_box.setStyleSheet(
                f"background: #F8F9FB; border: 1px solid {theme.BORDER}; "
                f"border-radius: 8px; padding: 8px 10px; color: {theme.MUTED}; font-size: 9pt;"
            )
            root.addWidget(ocr_box)

        form = QFormLayout()
        form.setSpacing(10)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Mysal: iPhone 16 Pro Max, Samsung S24 Ultra...")
        try:
            phone_models = list_distinct_phone_models()
        except SQLAlchemyError:
            phone_models = []
        model_completer = QCompleter(phone_models, self)
        model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.model_input.setCompleter(model_completer)
        form.addRow("Model ady *:", self.model_input)

        mem_color_row = QHBoxLayout()
        self.memory_input = QLineEdit()
        self.memory_input.setPlaceholderText("128GB, 256GB, 512GB...")
        self.color_input = QLineEdit()
        self.color_input.setPlaceholderText("Black, Natural Titanium...")
        mem_color_row.addWidget(self.memory_input, 1)
        mem_color_row.addWidget(QLabel("Reňk:"))
        mem_color_row.addWidget(self.color_input, 1)
        form.addRow("Ýat (GB/TB):", mem_color_row)

        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("Hökmany IMEI 1 (15 san)")
        form.addRow("IMEI 1 *:", self.imei1_input)

        imei2_sn_row = QHBoxLayout()
        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi S/N")
        imei2_sn_row.addWidget(self.imei2_input, 1)
        imei2_sn_row.addWidget(QLabel("S/N:"))
        imei2_sn_row.addWidget(self.sn_input, 1)
        form.addRow("IMEI 2 / S/N:", imei2_sn_row)

        cond_row = QHBoxLayout()
        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        self.condition_combo.currentIndexChanged.connect(self._on_condition_changed)

        self.category_badge = QLabel()
        self.category_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cond_row.addWidget(self.condition_combo, 1)
        cond_row.addWidget(self.category_badge)
        form.addRow("Ýagdaýy:", cond_row)

        root.addLayout(form)

        # Diňe B/U saýlananda görkezilýän bölüm
        self.used_section = QFrame()
        self.used_section.setStyleSheet(
            f"QFrame {{ background: #FFF8F0; border: 1px solid {theme.ACCENT_SOFT}; border-radius: 10px; }}"
        )
        used_form = QFormLayout(self.used_section)
        used_form.setContentsMargins(14, 10, 14, 10)
        used_form.setSpacing(8)

        self.battery_input = QLineEdit()
        self.battery_input.setPlaceholderText("Mysal: 89%")
        used_form.addRow("Batareýa %:", self.battery_input)

        self.cosmetic_input = QLineEdit()
        self.cosmetic_input.setPlaceholderText("Mysal: Arassa, korpusda çyzyk ýok")
        used_form.addRow("Umumy ýagdaýy:", self.cosmetic_input)

        root.addWidget(self.used_section)

        cost_form = QFormLayout()
        cost_form.setSpacing(10)

        cost_row = QHBoxLayout()
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0.0, 10_000_000.0)
        self.cost_spin.setDecimals(2)
        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100_000.0)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(self.exchange_rate))
        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.currency_combo)
        cost_row.addWidget(QLabel("Kurs:"))
        cost_row.addWidget(self.rate_spin)
        cost_form.addRow("Öz bahasy:", cost_row)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Goşmaça bellik (komplekt, guty, kepillik...)")
        cost_form.addRow("Bellik:", self.notes_input)

        root.addLayout(cost_form)

        if self.supplier_name:
            sup_txt = f"Üpjün ediji: {self.supplier_name}"
        else:
            sup_txt = "Çeşme: Şahsy çeşme (üpjün edijä bergi döremeýär)"
        if self.paid_amount > 0:
            sup_txt += f" • Kassadan töleg: {money_str(self.paid_amount)}"
        sup_lbl = QLabel(sup_txt)
        sup_lbl.setObjectName("mutedText")
        sup_lbl.setWordWrap(True)
        root.addWidget(sup_lbl)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("📱 Kabul et we sklada geçir", "primary")
        save_btn.clicked.connect(self._save)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)

    def _prefill(self) -> None:
        model_hint = (self.item.get("model_hint") or "").strip()
        ocr_raw = (self.item.get("ocr_raw_text") or "").strip()
        if model_hint:
            self.model_input.setText(model_hint)
        elif ocr_raw:
            parsed = parse_box_ocr(ocr_raw)
            if parsed.device_model:
                self.model_input.setText(parsed.device_model)

        self.imei1_input.setText((self.item.get("imei1") or "").strip())
        self.imei2_input.setText((self.item.get("imei2") or "").strip())
        self.sn_input.setText((self.item.get("serial_number") or "").strip())

        cond = "used" if str(self.item.get("condition") or "new").lower() in ("used", "b/u") else "new"
        idx = self.condition_combo.findData(cond)
        if idx >= 0:
            self.condition_combo.setCurrentIndex(idx)

        self.cost_spin.setValue(float(self.item.get("unit_cost") or 0))
        init_curr = (self.item.get("currency") or self.default_currency or "USD").upper()
        if init_curr in ("USD", "TMT"):
            self.currency_combo.setCurrentText(init_curr)

        self._on_condition_changed()

    def _on_condition_changed(self) -> None:
        is_used = self.condition_combo.currentData() == "used"
        self.used_section.setVisible(is_used)
        if is_used:
            self.category_badge.setText("Kategoriýa: Telefon B/U")
            self.category_badge.setStyleSheet(
                f"background: {theme.ACCENT_BG}; color: {theme.ACCENT}; "
                f"border: 1px solid {theme.ACCENT}; border-radius: 8px; "
                "padding: 6px 12px; font-weight: 700; font-size: 9pt;"
            )
        else:
            self.category_badge.setText("Kategoriýa: Telefon Täze")
            self.category_badge.setStyleSheet(
                f"background: #E7F6EC; color: {theme.GREEN}; "
                f"border: 1px solid {theme.GREEN}; border-radius: 8px; "
                "padding: 6px 12px; font-weight: 700; font-size: 9pt;"
            )
        self.adjustSize()

    def _save(self) -> None:
        model_name = self.model_input.text().strip()
        imei1 = self.imei1_input.text().strip()
        if not model_name:
            QMessageBox.warning(self, "Maglumatlary barlaň", "Telefon modeliniň adyny giriziň.")
            self.model_input.setFocus()
            return
        if not imei1:
            QMessageBox.warning(self, "Maglumatlary barlaň", "Hökmany IMEI 1 giriziň.")
            self.imei1_input.setFocus()
            return

        cond = self.condition_combo.currentData() or "new"
        is_used = cond == "used"
        cost_dec = Decimal(f"{self.cost_spin.value():.2f}")
        curr = self.currency_combo.currentText().strip().upper() or "USD"
        rate_dec = Decimal(f"{self.rate_spin.value():.4f}")

        try:
            commit_phone_item(
                queue_id=int(self.item["id"]),
                model_name=model_name,
                imei1=imei1,
                memory=self.memory_input.text().strip() or None,
                color=self.color_input.text().strip() or None,
                imei2=self.imei2_input.text().strip() or None,
                serial_number=self.sn_input.text().strip() or None,
                condition=cond,
                battery_health=self.battery_input.text().strip() or None if is_used else None,
                cosmetic_condition=self.cosmetic_input.text().strip() or None if is_used else None,
                unit_cost=cost_dec,
                currency=curr,
                exchange_rate=rate_dec,
                supplier_name=self.supplier_name or None,
                paid_amount=self.paid_amount,
                notes=self.notes_input.text().strip() or None,
            )
            self.committed_model = model_name
            self.committed_imei1 = imei1
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Telefony kabul edip bolmady:\n{err}")


class IncomingQueuePage(QWidget):
    """Mobil skanerden gelen harytlary we telefonlary kabul etmek üçin PK nobaty."""

    queueChanged = Signal(int)
    stockCommitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        self._known_items: list[dict[str, Any]] = []
        self._unknown_items: list[dict[str, Any]] = []
        self._phone_items: list[dict[str, Any]] = []
        self._known_editors: dict[int, tuple[QSpinBox, QDoubleSpinBox]] = {}

        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # Header
        header = QHBoxLayout()
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Kabul ediş nobaty")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Mobil skanerden gelen harytlar we telefonlar tassyklanyp sklada geçirilýär"
        )
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        self.refresh_btn = make_button("↻ Täzele")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(self.refresh_btn)

        self.clear_btn = make_button("🗑 Nobaty arassala", "danger")
        self.clear_btn.clicked.connect(self._clear_all_queue)
        header.addWidget(self.clear_btn)

        layout.addLayout(header)

        # Shared batch parameters card
        params_card = Card(margins=(16, 12, 16, 12), spacing=8)
        params_row = QHBoxLayout()
        params_row.setSpacing(10)

        params_row.addWidget(QLabel("Üpjün ediji:"))
        self.supplier_input = QLineEdit()
        self.supplier_input.setClearButtonEnabled(True)
        self.supplier_input.setPlaceholderText(
            "Üpjün ediji (boş goýulsa — şahsy çeşme, bergisiz)"
        )
        params_row.addWidget(self.supplier_input, 2)

        params_row.addWidget(QLabel("Walýuta:"))
        self.currency_combo = style_combo(QComboBox())
        self.currency_combo.addItems(["USD", "TMT"])
        def_curr = SettingsService.get("default_currency", "USD").strip().upper()
        if def_curr in ("USD", "TMT"):
            self.currency_combo.setCurrentText(def_curr)
        self.currency_combo.setMinimumWidth(88)
        params_row.addWidget(self.currency_combo)

        params_row.addWidget(QLabel("Kurs:"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100_000.0)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.rate_spin.setMinimumWidth(98)
        params_row.addWidget(self.rate_spin)

        params_row.addWidget(QLabel("Töleg (kassadan):"))
        self.paid_spin = QDoubleSpinBox()
        self.paid_spin.setRange(0.0, 10_000_000.0)
        self.paid_spin.setDecimals(2)
        self.paid_spin.setValue(0.0)
        self.paid_spin.setMinimumWidth(110)
        self.paid_spin.setToolTip(
            "0.00 = kassadan pul çykarylmaýar. Üpjün ediji boş goýulsa — şahsy çeşme hasaplanýar we bergi ýazylmaýar."
        )
        params_row.addWidget(self.paid_spin)

        params_card.body.addLayout(params_row)
        layout.addWidget(params_card)

        # 3-tab QTabWidget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_known_tab(), "✅ Belli harytlar (0)")
        self.tabs.addTab(self._build_unknown_tab(), "❓ Näbelli harytlar (0)")
        self.tabs.addTab(self._build_phone_tab(), "📱 Telefonlar (IMEI) (0)")
        layout.addWidget(self.tabs, 1)

    def _build_known_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(12)

        self.known_table = QTableWidget(0, 7)
        self.known_table.setHorizontalHeaderLabels([
            "ID",
            "Haryt",
            "Kategoriýa • Brend/Model",
            "Sany",
            "Alyş bahasy",
            "Skladdaky galyndy",
            "Skaner / Wagt",
        ])
        configure_table(self.known_table, stretch_col=[1, 2], row_height=46)
        hdr = self.known_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.known_table.setColumnWidth(3, 96)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.known_table.setColumnWidth(4, 138)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.known_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.commit_selected_known_btn = make_button("✓ Saýlanany sklada geçir", "primary")
        self.commit_selected_known_btn.clicked.connect(self._commit_selected_known)
        actions.addWidget(self.commit_selected_known_btn)

        self.commit_all_known_btn = make_button(
            "✓✓ Ähli belli harytlary bir alyş bilen geçir",
            "success",
        )
        self.commit_all_known_btn.clicked.connect(self._commit_all_known)
        actions.addWidget(self.commit_all_known_btn)

        actions.addStretch()

        self.delete_known_btn = make_button("🗑 Poz", "danger")
        self.delete_known_btn.clicked.connect(lambda: self._delete_selected_from(self.known_table))
        actions.addWidget(self.delete_known_btn)

        v.addLayout(actions)
        return tab

    def _build_unknown_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(12)

        self.unknown_table = _EnterActivatedTable(0, 6)
        self.unknown_table.setHorizontalHeaderLabels([
            "ID",
            "Ştrihkod",
            "OCR tekst / Bellik",
            "Sany",
            "Alyş bahasy",
            "Skaner / Wagt",
        ])
        configure_table(self.unknown_table, stretch_col=2, row_height=46)
        hdr = self.unknown_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.unknown_table.cellDoubleClicked.connect(lambda _r, _c: self._open_unknown_dialog())
        self.unknown_table.enterActivated.connect(self._open_unknown_dialog)
        v.addWidget(self.unknown_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.commit_unknown_btn = make_button("📝 Karty doldur we sklada geçir", "primary")
        self.commit_unknown_btn.clicked.connect(self._open_unknown_dialog)
        actions.addWidget(self.commit_unknown_btn)

        actions.addStretch()

        self.delete_unknown_btn = make_button("🗑 Poz", "danger")
        self.delete_unknown_btn.clicked.connect(lambda: self._delete_selected_from(self.unknown_table))
        actions.addWidget(self.delete_unknown_btn)

        v.addLayout(actions)
        return tab

    def _build_phone_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(12)

        self.phone_table = _EnterActivatedTable(0, 7)
        self.phone_table.setHorizontalHeaderLabels([
            "ID",
            "IMEI 1",
            "IMEI 2 / S/N",
            "Ýagdaýy (Täze / B/U)",
            "Bellik / OCR",
            "Alyş bahasy",
            "Skaner / Wagt",
        ])
        configure_table(self.phone_table, stretch_col=4, row_height=46)
        hdr = self.phone_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.phone_table.cellDoubleClicked.connect(lambda _r, _c: self._open_phone_dialog())
        self.phone_table.enterActivated.connect(self._open_phone_dialog)
        v.addWidget(self.phone_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.commit_phone_btn = make_button("📱 Maglumaty doldur we kabul et", "primary")
        self.commit_phone_btn.clicked.connect(self._open_phone_dialog)
        actions.addWidget(self.commit_phone_btn)

        actions.addStretch()

        self.delete_phone_btn = make_button("🗑 Poz", "danger")
        self.delete_phone_btn.clicked.connect(lambda: self._delete_selected_from(self.phone_table))
        actions.addWidget(self.delete_phone_btn)

        v.addLayout(actions)
        return tab

    def _batch_params(self) -> tuple[str, str, Decimal, Decimal]:
        supplier = self.supplier_input.text().strip()
        currency = self.currency_combo.currentText().strip().upper() or "USD"
        rate = Decimal(f"{self.rate_spin.value():.4f}")
        paid = Decimal(f"{self.paid_spin.value():.2f}")
        return supplier, currency, rate, paid

    def refresh_data(self) -> None:
        try:
            self._known_items = list_queue_items("known")
            self._unknown_items = list_queue_items("unknown")
            self._phone_items = list_queue_items("phone_imei")
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Nobaty ýükläp bolmady:\n{err}")
            return

        self._populate_known_table()
        self._populate_unknown_table()
        self._populate_phone_table()

        n_known = len(self._known_items)
        n_unknown = len(self._unknown_items)
        n_phone = len(self._phone_items)
        total = n_known + n_unknown + n_phone

        self.tabs.setTabText(0, f"✅ Belli harytlar ({n_known})")
        self.tabs.setTabText(1, f"❓ Näbelli harytlar ({n_unknown})")
        self.tabs.setTabText(2, f"📱 Telefonlar (IMEI) ({n_phone})")

        self.clear_btn.setEnabled(total > 0)
        self.commit_selected_known_btn.setEnabled(n_known > 0)
        self.commit_all_known_btn.setEnabled(n_known > 0)
        self.delete_known_btn.setEnabled(n_known > 0)
        self.commit_unknown_btn.setEnabled(n_unknown > 0)
        self.delete_unknown_btn.setEnabled(n_unknown > 0)
        self.commit_phone_btn.setEnabled(n_phone > 0)
        self.delete_phone_btn.setEnabled(n_phone > 0)

        self.queueChanged.emit(total)

    def _populate_known_table(self) -> None:
        self._known_editors.clear()
        self.known_table.setRowCount(len(self._known_items))

        inline_style = (
            f"QSpinBox, QDoubleSpinBox {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; "
            f"border-radius: 6px; padding: 3px 6px; min-height: 24px; font-weight: 600; }}"
            f"QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {theme.ACCENT}; }}"
        )

        for r, item in enumerate(self._known_items):
            qid = int(item["id"])
            id_cell = QTableWidgetItem(f"#{qid}")
            id_cell.setData(Qt.ItemDataRole.UserRole, qid)
            id_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.known_table.setItem(r, 0, id_cell)

            name_text = item.get("product_name") or f"Haryt #{item.get('product_id')}"
            if item.get("barcode"):
                name_text = f"{name_text}  [{item['barcode']}]"
            self.known_table.setItem(r, 1, QTableWidgetItem(name_text))

            bm = " / ".join(filter(None, [item.get("brand"), item.get("model")]))
            cat_bm = " • ".join(filter(None, [item.get("category") or "—", bm]))
            self.known_table.setItem(r, 2, QTableWidgetItem(cat_bm))

            qty_spin = QSpinBox()
            qty_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            qty_spin.setRange(1, 1_000_000)
            qty_spin.setValue(max(1, int(item.get("quantity") or 1)))
            qty_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_spin.setStyleSheet(inline_style)
            qty_spin.editingFinished.connect(
                lambda q=qid, sp=qty_spin: self._persist_known_qty(q, sp.value())
            )
            self.known_table.setCellWidget(r, 3, qty_spin)

            cost_spin = QDoubleSpinBox()
            cost_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            cost_spin.setRange(0.0, 10_000_000.0)
            cost_spin.setDecimals(2)
            cost_spin.setValue(float(item.get("unit_cost") or 0))
            cost_spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            curr_sfx = (item.get("currency") or "USD").upper()
            cost_spin.setSuffix(f" {curr_sfx}")
            cost_spin.setStyleSheet(inline_style)
            cost_spin.editingFinished.connect(
                lambda q=qid, sp=cost_spin: self._persist_known_cost(q, sp.value())
            )
            self.known_table.setCellWidget(r, 4, cost_spin)

            self._known_editors[qid] = (qty_spin, cost_spin)

            stock_cell = QTableWidgetItem(f"{int(item.get('current_stock') or 0)} sany")
            stock_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock_cell.setForeground(QColor(theme.MUTED))
            self.known_table.setItem(r, 5, stock_cell)

            scan_cell = QTableWidgetItem(
                _format_scanner_time(item.get("device_name", ""), item.get("created_at"))
            )
            scan_cell.setForeground(QColor(theme.MUTED))
            self.known_table.setItem(r, 6, scan_cell)

        if self._known_items and self.known_table.currentRow() < 0:
            self.known_table.selectRow(0)

    def _populate_unknown_table(self) -> None:
        self.unknown_table.setRowCount(len(self._unknown_items))
        for r, item in enumerate(self._unknown_items):
            qid = int(item["id"])
            id_cell = QTableWidgetItem(f"#{qid}")
            id_cell.setData(Qt.ItemDataRole.UserRole, qid)
            id_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.unknown_table.setItem(r, 0, id_cell)

            bc_cell = QTableWidgetItem(item.get("barcode") or "—")
            self.unknown_table.setItem(r, 1, bc_cell)

            ocr_parts = [p for p in (item.get("model_hint"), item.get("ocr_raw_text")) if p]
            ocr_text = " • ".join(ocr_parts) if ocr_parts else "—"
            ocr_cell = QTableWidgetItem(ocr_text)
            ocr_cell.setToolTip(ocr_text)
            self.unknown_table.setItem(r, 2, ocr_cell)

            qty_cell = QTableWidgetItem(f"{int(item.get('quantity') or 1)}")
            qty_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.unknown_table.setItem(r, 3, qty_cell)

            u_cost = Decimal(str(item.get("unit_cost") or 0))
            cost_str = f"{money_str(u_cost)} {item.get('currency', 'USD')}" if u_cost > 0 else "—"
            cost_cell = QTableWidgetItem(cost_str)
            cost_cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.unknown_table.setItem(r, 4, cost_cell)

            scan_cell = QTableWidgetItem(
                _format_scanner_time(item.get("device_name", ""), item.get("created_at"))
            )
            scan_cell.setForeground(QColor(theme.MUTED))
            self.unknown_table.setItem(r, 5, scan_cell)

        if self._unknown_items and self.unknown_table.currentRow() < 0:
            self.unknown_table.selectRow(0)

    def _populate_phone_table(self) -> None:
        self.phone_table.setRowCount(len(self._phone_items))
        for r, item in enumerate(self._phone_items):
            qid = int(item["id"])
            id_cell = QTableWidgetItem(f"#{qid}")
            id_cell.setData(Qt.ItemDataRole.UserRole, qid)
            id_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.phone_table.setItem(r, 0, id_cell)

            imei1_cell = QTableWidgetItem(item.get("imei1") or "—")
            self.phone_table.setItem(r, 1, imei1_cell)

            extra_ids = " / ".join(
                filter(None, [item.get("imei2"), item.get("serial_number")])
            ) or "—"
            self.phone_table.setItem(r, 2, QTableWidgetItem(extra_ids))

            is_used = str(item.get("condition") or "new").lower() in ("used", "b/u")
            cond_cell = QTableWidgetItem("B/U (Ulanylan)" if is_used else "Täze")
            cond_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cond_cell.setForeground(QColor(theme.ACCENT if is_used else theme.GREEN))
            self.phone_table.setItem(r, 3, cond_cell)

            note_parts = [p for p in (item.get("model_hint"), item.get("ocr_raw_text")) if p]
            note_txt = " • ".join(note_parts) if note_parts else "—"
            note_cell = QTableWidgetItem(note_txt)
            note_cell.setToolTip(note_txt)
            self.phone_table.setItem(r, 4, note_cell)

            u_cost = Decimal(str(item.get("unit_cost") or 0))
            cost_str = f"{money_str(u_cost)} {item.get('currency', 'USD')}" if u_cost > 0 else "—"
            cost_cell = QTableWidgetItem(cost_str)
            cost_cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.phone_table.setItem(r, 5, cost_cell)

            scan_cell = QTableWidgetItem(
                _format_scanner_time(item.get("device_name", ""), item.get("created_at"))
            )
            scan_cell.setForeground(QColor(theme.MUTED))
            self.phone_table.setItem(r, 6, scan_cell)

        if self._phone_items and self.phone_table.currentRow() < 0:
            self.phone_table.selectRow(0)

    def _persist_known_qty(self, queue_id: int, qty: int) -> None:
        try:
            update_queue_item(queue_id, quantity=int(qty))
        except (ValueError, SQLAlchemyError):
            pass

    def _persist_known_cost(self, queue_id: int, cost: float) -> None:
        try:
            update_queue_item(queue_id, unit_cost=Decimal(f"{cost:.2f}"))
        except (ValueError, SQLAlchemyError):
            pass

    def _selected_queue_id(self, table: QTableWidget) -> int | None:
        row = table.currentRow()
        if row < 0:
            return None
        cell = table.item(row, 0)
        if cell is None:
            return None
        raw_id = cell.data(Qt.ItemDataRole.UserRole)
        return int(raw_id) if raw_id is not None else None

    def _collect_known_overrides(self, queue_ids: list[int]) -> dict[int, dict[str, Any]]:
        overrides: dict[int, dict[str, Any]] = {}
        for qid in queue_ids:
            pair = self._known_editors.get(qid)
            if pair is not None:
                qty_spin, cost_spin = pair
                overrides[qid] = {
                    "quantity": int(qty_spin.value()),
                    "unit_cost": Decimal(f"{cost_spin.value():.2f}"),
                }
        return overrides

    def _commit_selected_known(self) -> None:
        qid = self._selected_queue_id(self.known_table)
        if qid is None:
            show_toast(self, "Geçirmek üçin belli haryt setirini saýlaň.", kind="info")
            return
        supplier, currency, rate, paid = self._batch_params()
        overrides = self._collect_known_overrides([qid])
        try:
            purchase_id = commit_known_items(
                queue_ids=[qid],
                supplier_name=supplier or None,
                currency=currency,
                exchange_rate=rate,
                paid_amount=paid,
                overrides=overrides,
            )
            show_toast(
                self,
                f"Haryt üstünlikli sklada geçirildi (Alyş #{purchase_id}).",
                kind="success",
            )
            self.refresh_data()
            self.stockCommitted.emit()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Harydy sklada geçirip bolmady:\n{err}")

    def _commit_all_known(self) -> None:
        if not self._known_items:
            show_toast(self, "Belli harytlar nobaty boş.", kind="info")
            return
        all_ids = [int(it["id"]) for it in self._known_items]
        supplier, currency, rate, paid = self._batch_params()
        overrides = self._collect_known_overrides(all_ids)
        try:
            purchase_id = commit_known_items(
                queue_ids=all_ids,
                supplier_name=supplier or None,
                currency=currency,
                exchange_rate=rate,
                paid_amount=paid,
                overrides=overrides,
            )
            show_toast(
                self,
                f"{len(all_ids)} belli haryt bir alyş bilen sklada geçirildi (Alyş #{purchase_id}).",
                kind="success",
            )
            self.refresh_data()
            self.stockCommitted.emit()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Harytlary sklada geçirip bolmady:\n{err}")

    def _open_unknown_dialog(self) -> None:
        qid = self._selected_queue_id(self.unknown_table)
        if qid is None:
            show_toast(self, "Karty doldurmak üçin näbelli haryt setirini saýlaň.", kind="info")
            return
        item = next((it for it in self._unknown_items if int(it["id"]) == qid), None)
        if item is None:
            self.refresh_data()
            return

        supplier, currency, rate, paid = self._batch_params()
        dlg = CommitUnknownItemDialog(
            item=item,
            supplier_name=supplier,
            currency=currency,
            exchange_rate=rate,
            paid_amount=paid,
            parent=self,
        )
        if dlg.exec():
            show_toast(
                self,
                f"«{dlg.created_product_name}» ({dlg.committed_qty} sany) sklada geçirildi.",
                kind="success",
            )
            self.refresh_data()
            self.stockCommitted.emit()

    def _open_phone_dialog(self) -> None:
        qid = self._selected_queue_id(self.phone_table)
        if qid is None:
            show_toast(self, "Kabul etmek üçin telefon setirini saýlaň.", kind="info")
            return
        item = next((it for it in self._phone_items if int(it["id"]) == qid), None)
        if item is None:
            self.refresh_data()
            return

        supplier, currency, rate, paid = self._batch_params()
        dlg = CommitQueuedPhoneDialog(
            item=item,
            supplier_name=supplier,
            currency=currency,
            exchange_rate=rate,
            paid_amount=paid,
            parent=self,
        )
        if dlg.exec():
            show_toast(
                self,
                f"📱 «{dlg.committed_model}» (IMEI {dlg.committed_imei1}) sklada kabul edildi.",
                kind="success",
            )
            self.refresh_data()
            self.stockCommitted.emit()

    def _delete_selected_from(self, table: QTableWidget) -> None:
        qid = self._selected_queue_id(table)
        if qid is None:
            show_toast(self, "Pozmak üçin tablisadan setir saýlaň.", kind="info")
            return
        ans = QMessageBox.question(
            self,
            "Nobatdan pozmak",
            f"#{qid} belgili ýazgyny kabul ediş nobatyndan pozmalymy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_queue_item(qid)
            show_toast(self, "Ýazgy nobatdan pozuldy.", kind="success")
            self.refresh_data()
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Ýazgyny pozup bolmady:\n{err}")

    def _clear_all_queue(self) -> None:
        total = len(self._known_items) + len(self._unknown_items) + len(self._phone_items)
        if total == 0:
            show_toast(self, "Kabul ediş nobaty eýýäm boş.", kind="info")
            return
        ans = QMessageBox.question(
            self,
            "Nobaty arassalamak",
            f"Kabul ediş nobatyndaky ähli {total} ýazgyny hakykatdan hem pozmalymy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_queue()
            show_toast(self, f"Nobat arassalandy ({removed} ýazgy pozuldy).", kind="success")
            self.refresh_data()
        except SQLAlchemyError as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Nobaty arassalap bolmady:\n{err}")
