from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database.engine import SessionLocal
from app.repositories.product_repository import (
    deactivate_product,
    delete_stock_item,
    get_product_with_devices,
    list_distinct_phone_models,
    list_products_inventory,
    register_standalone_phone,
    register_stock_item,
    restore_product,
    update_standalone_phone,
    update_stock_item,
)
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.category_management_dialog import CategoryManagementDialog
from app.ui.product_dialog import ProductDialog
from app.ui.widgets import (
    Card,
    configure_dialog_buttons,
    configure_table,
    make_button,
    make_stat_card,
    money_str,
    show_toast,
    style_combo,
)

SOURCES = [
    ("Üpjün ediji / Alyş", "supplier"),
    ("Müşderiden satyn alma (B/U)", "direct_buyout"),
    ("Trade-In (Çalyşyk)", "trade_in"),
    ("Başlangyç galyndy girizmek", "initial_stock"),
]

SOURCE_LABELS = {code: label for label, code in SOURCES}

STOCK_ITEM_STATUSES = [
    ("Skladda bar (in_stock)", "in_stock"),
    ("Satyldy (sold)", "sold"),
    ("Hasapdan çykaryldy (written_off)", "written_off"),
]

ROLE_ITEM_TYPE = Qt.ItemDataRole.UserRole
ROLE_PRODUCT_ID = Qt.ItemDataRole.UserRole + 1
ROLE_PRODUCT_NAME = Qt.ItemDataRole.UserRole + 2
ROLE_IS_ACTIVE = Qt.ItemDataRole.UserRole + 3
ROLE_TOTAL_DEVICES = Qt.ItemDataRole.UserRole + 4
ROLE_IS_PHONE_UNIT = Qt.ItemDataRole.UserRole + 5
ROLE_PRIMARY_STOCK_ITEM_ID = Qt.ItemDataRole.UserRole + 6
ROLE_GROUP_KEY = Qt.ItemDataRole.UserRole + 7


def _apply_phone_category_badge(label: QLabel, is_used: bool) -> None:
    if is_used:
        label.setText("🔒 Kategoriýa: Telefon B/U")
        label.setStyleSheet(
            f"font-weight: 700; color: {theme.ACCENT}; background: #FFF8F1; "
            "border: 1px solid #FDBA74; padding: 5px 10px; border-radius: 6px;"
        )
    else:
        label.setText("🔒 Kategoriýa: Telefon Täze")
        label.setStyleSheet(
            f"font-weight: 700; color: {theme.BLUE}; background: #EFF6FF; "
            "border: 1px solid #93C5FD; padding: 5px 10px; border-radius: 6px;"
        )


class StandalonePhoneIntakeDialog(QDialog):
    """Özbaşdak IMEI telefon kabul ediş penjiresi (katalogdan saýlamazdan, hemişelik kategoriýa bilen)."""

    def __init__(self, default_condition: str = "new", parent=None) -> None:
        super().__init__(parent)
        self.default_condition = "used" if default_condition == "used" else "new"
        self.session_added_count = 0

        self.setWindowTitle("Telefony sklada kabul etmek (IMEI)")
        self.setMinimumSize(860, 720)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._refresh_model_completer()
        self._sync_condition_ui()
        self._load_in_stock_phones()
        self.model_input.setFocus()

    @staticmethod
    def _wrap_row(hbox: QHBoxLayout) -> QWidget:
        box = QWidget()
        hbox.setContentsMargins(0, 1, 0, 1)
        box.setMinimumHeight(40)
        box.setLayout(hbox)
        return box

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Telefony sklada goşmak (IMEI)")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Her telefon öz IMEI belgisi bilen aýratyn hasaba alynýar we awtomatiki hemişelik "
            "«Telefon Täze» ýa-da «Telefon B/U» kategoriýasyna düşýär."
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        card = Card(margins=(18, 16, 18, 16), spacing=10)

        self._form = QFormLayout()
        self._form.setSpacing(10)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Mysal: iPhone 15 Pro Max, Samsung S24 Ultra, Redmi Note 14...")
        self._form.addRow("Model ady *:", self.model_input)

        spec_row = QHBoxLayout()
        spec_row.setSpacing(8)
        self.memory_input = QLineEdit()
        self.memory_input.setPlaceholderText("128GB, 256GB, 512GB...")
        self.color_input = QLineEdit()
        self.color_input.setPlaceholderText("Black, Natural Titanium...")
        spec_row.addWidget(QLabel("Ýat (Memory):"))
        spec_row.addWidget(self.memory_input, 1)
        spec_row.addWidget(QLabel("Reňk (Color):"))
        spec_row.addWidget(self.color_input, 1)
        self._form.addRow("Aýratynlyklar:", self._wrap_row(spec_row))

        imei_row = QHBoxLayout()
        imei_row.setSpacing(8)
        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 (hökmany)*")
        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi (S/N)")
        imei_row.addWidget(self.imei1_input, 2)
        imei_row.addWidget(self.imei2_input, 2)
        imei_row.addWidget(self.sn_input, 1)
        self._form.addRow("IMEI / S/N:", self._wrap_row(imei_row))

        cond_row = QHBoxLayout()
        cond_row.setSpacing(10)
        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        if self.default_condition == "used":
            self.condition_combo.setCurrentIndex(1)
        self.condition_combo.currentIndexChanged.connect(self._sync_condition_ui)

        self.category_badge = QLabel()
        self.category_badge.setToolTip("Telefonlaryň kategoriýasy ýagdaýyna görä awtomatiki berkidilýär.")
        cond_row.addWidget(self.condition_combo)
        cond_row.addWidget(self.category_badge)
        cond_row.addStretch()
        self._form.addRow("Ýagdaýy:", self._wrap_row(cond_row))

        # Conditional optional fields shown ONLY when B/U is selected
        self.used_fields_box = QWidget()
        self.used_fields_box.setMinimumHeight(40)
        used_layout = QHBoxLayout(self.used_fields_box)
        used_layout.setContentsMargins(0, 1, 0, 1)
        used_layout.setSpacing(8)
        self.battery_input = QLineEdit()
        self.battery_input.setPlaceholderText("88%, 92%...")
        self.cosmetic_input = QLineEdit()
        self.cosmetic_input.setPlaceholderText("Arassa, korpusda çyzyk ýok, komplekt...")
        used_layout.addWidget(QLabel("Batareýa %:"))
        used_layout.addWidget(self.battery_input, 1)
        used_layout.addWidget(QLabel("Umumy ýagdaýy:"))
        used_layout.addWidget(self.cosmetic_input, 2)
        self._form.addRow("B/U maglumat:", self.used_fields_box)

        cost_row = QHBoxLayout()
        cost_row.setSpacing(8)
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.source_combo = style_combo(QComboBox())
        for label, code in SOURCES:
            self.source_combo.addItem(label, code)
        if self.default_condition == "used":
            self.source_combo.setCurrentIndex(1)

        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.cost_curr_combo)
        cost_row.addWidget(QLabel("Kurs:"))
        cost_row.addWidget(self.rate_spin)
        cost_row.addWidget(QLabel("Çeşme:"))
        cost_row.addWidget(self.source_combo, 1)
        self._form.addRow("Öz bahasy:", self._wrap_row(cost_row))

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Goşmaça bellik (hökmany däl)...")
        self._form.addRow("Bellik:", self.notes_input)

        card.body.addLayout(self._form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        clear_btn = make_button("↺ Arassala")
        clear_btn.setToolTip("Ähli öýjükleri arassalamak")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()

        self.add_phone_btn = make_button("+ Telefony sklada goş", "primary")
        self.add_phone_btn.clicked.connect(self._add_phone)
        btn_row.addWidget(self.add_phone_btn)
        card.body.addLayout(btn_row)

        root.addWidget(card)

        list_header = QHBoxLayout()
        self.list_title = QLabel("Skladdaky özbaşdak telefonlar (IMEI)")
        self.list_title.setObjectName("cardTitle")
        list_header.addWidget(self.list_title, 1)
        self.session_badge = QLabel("Şu sessiýada goşulan: 0")
        self.session_badge.setObjectName("mutedText")
        list_header.addWidget(self.session_badge)
        root.addLayout(list_header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "Model",
            "Ýat / Reňk",
            "IMEI 1",
            "Ýagdaýy",
            "Öz bahasy",
            "Kategoriýa",
        ])
        configure_table(self.table, stretch_col=[1, 2], row_height=40)
        self.table.setMinimumHeight(165)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._edit_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        edit_btn = make_button("✏ Saýlanan telefony üýtget")
        edit_btn.clicked.connect(self._edit_selected)
        footer.addWidget(edit_btn)
        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, self.add_phone_btn, close_btn)

    def _refresh_model_completer(self) -> None:
        try:
            models = list_distinct_phone_models()
        except SQLAlchemyError:
            models = []
        completer = QCompleter(models, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.model_input.setCompleter(completer)

    def _sync_condition_ui(self) -> None:
        is_used = self.condition_combo.currentData() == "used"
        _apply_phone_category_badge(self.category_badge, is_used)
        self._form.setRowVisible(self.used_fields_box, is_used)

    def _clear_all(self) -> None:
        self.model_input.clear()
        self.memory_input.clear()
        self.color_input.clear()
        self.imei1_input.clear()
        self.imei2_input.clear()
        self.sn_input.clear()
        self.condition_combo.setCurrentIndex(0)
        self.battery_input.clear()
        self.cosmetic_input.clear()
        self.cost_spin.setValue(0.0)
        self.cost_curr_combo.setCurrentText("USD")
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.source_combo.setCurrentIndex(0)
        self.notes_input.clear()
        self._sync_condition_ui()
        self.model_input.setFocus()

    def _add_phone(self) -> None:
        cond = self.condition_combo.currentData() or "new"
        is_used = cond == "used"
        try:
            register_standalone_phone(
                model_name=self.model_input.text(),
                imei1=self.imei1_input.text(),
                memory=self.memory_input.text(),
                color=self.color_input.text(),
                imei2=self.imei2_input.text(),
                serial_number=self.sn_input.text(),
                condition=cond,
                battery_health=self.battery_input.text() if is_used else None,
                cosmetic_condition=self.cosmetic_input.text() if is_used else None,
                unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                cost_currency=self.cost_curr_combo.currentText(),
                cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                acquisition_source=self.source_combo.currentData(),
                notes=self.notes_input.text(),
            )
            self.session_added_count += 1
            self.session_badge.setText(f"Şu sessiýada goşulan: {self.session_added_count}")
            # Clear ONLY IMEI 1 / IMEI 2 / S/N for fast consecutive phone entry
            self.imei1_input.clear()
            self.imei2_input.clear()
            self.sn_input.clear()
            self._refresh_model_completer()
            self._load_in_stock_phones()
            self.imei1_input.setFocus()
            show_toast(self, "Telefon sklada üstünlikli goşuldy.", kind="success")
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Telefony ýatda saklap bolmady:\n{err}")

    def _load_in_stock_phones(self) -> None:
        from app.models.category import Category
        from app.models.product import Product
        from app.models.stock_item import StockItem

        with SessionLocal() as session:
            rows = session.execute(
                select(StockItem, Product, Category.name)
                .join(Product, StockItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(
                    Product.is_active.is_(True),
                    Product.is_phone_unit.is_(True),
                    StockItem.status == "in_stock",
                )
                .order_by(StockItem.id.desc())
                .limit(100)
            ).all()

        self.table.setRowCount(len(rows))
        for r, (st, prod, cat_name) in enumerate(rows):
            spec_parts = [x for x in (st.memory, st.color) if x]
            if st.condition != "new" and st.battery_health:
                bh = st.battery_health.strip()
                spec_parts.append(bh if bh.lower().startswith("bat") else f"Bat: {bh}")
            spec_text = " • ".join(spec_parts) or "—"
            cond_text = "Täze" if st.condition == "new" else "B/U"
            cost_text = (
                f"{money_str(st.unit_cost)} {st.cost_currency or ''}".strip()
                if st.unit_cost is not None and Decimal(str(st.unit_cost)) > 0
                else "—"
            )
            vals = [
                str(st.id),
                prod.name,
                spec_text,
                st.imei1,
                cond_text,
                cost_text,
                cat_name or ("Telefon Täze" if st.condition == "new" else "Telefon B/U"),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (0, 3, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    cell.setForeground(
                        QColor(theme.BLUE if st.condition == "new" else theme.ACCENT)
                    )
                self.table.setItem(r, c, cell)

    def _edit_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Üýtgetmek üçin tablisadan telefon saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        if not id_cell:
            return
        dlg = EditStockItemDialog(int(id_cell.text()), self)
        if dlg.exec():
            self._refresh_model_completer()
            self._load_in_stock_phones()


class EditStockItemDialog(QDialog):
    """Полное редактирование отдельного устройства (StockItem) по IMEI."""

    def __init__(self, stock_item_id: int, parent=None) -> None:
        super().__init__(parent)
        self.stock_item_id = stock_item_id
        self.is_phone_unit = False
        self._product_name = ""
        self._imei1_loaded = ""
        self.setWindowTitle(f"Enjamy üýtgetmek (ID #{stock_item_id})")
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._load_data()
        if self.is_phone_unit:
            self.model_name_input.setFocus()
        else:
            self.imei1_input.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        self.title_label = QLabel(f"Enjamyň (ID #{self.stock_item_id}) maglumatlaryny üýtgetmek")
        self.title_label.setObjectName("pageTitle")
        root.addWidget(self.title_label)

        # Legacy product selector (hidden for standalone phones)
        self.legacy_product_box = QWidget()
        legacy_form = QFormLayout(self.legacy_product_box)
        legacy_form.setContentsMargins(0, 0, 0, 0)
        legacy_form.setSpacing(10)
        self.product_combo = style_combo(QComboBox())
        legacy_form.addRow("Model / Haryt *:", self.product_combo)
        root.addWidget(self.legacy_product_box)

        # Standalone phone direct fields (shown only for standalone phones)
        self.phone_identity_box = QWidget()
        phone_form = QFormLayout(self.phone_identity_box)
        phone_form.setContentsMargins(0, 0, 0, 0)
        phone_form.setSpacing(10)

        self.model_name_input = QLineEdit()
        self.model_name_input.setPlaceholderText("Mysal: iPhone 15 Pro Max, Samsung S24 Ultra...")
        phone_form.addRow("Model ady *:", self.model_name_input)

        mem_col_box = QWidget()
        mem_col_box.setMinimumHeight(40)
        mem_col_row = QHBoxLayout(mem_col_box)
        mem_col_row.setContentsMargins(0, 1, 0, 1)
        mem_col_row.setSpacing(8)
        self.memory_input = QLineEdit()
        self.memory_input.setPlaceholderText("128GB, 256GB, 512GB...")
        self.color_input = QLineEdit()
        self.color_input.setPlaceholderText("Black, Natural Titanium...")
        mem_col_row.addWidget(QLabel("Ýat:"))
        mem_col_row.addWidget(self.memory_input, 1)
        mem_col_row.addWidget(QLabel("Reňk:"))
        mem_col_row.addWidget(self.color_input, 1)
        phone_form.addRow("Ýat / Reňk:", mem_col_box)
        root.addWidget(self.phone_identity_box)

        form = QFormLayout()
        form.setSpacing(10)

        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 *")
        form.addRow("IMEI 1 *:", self.imei1_input)

        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        form.addRow("IMEI 2:", self.imei2_input)

        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi S/N (hökmany däl)")
        form.addRow("Seriýa belgisi (S/N):", self.sn_input)

        cond_box = QWidget()
        cond_box.setMinimumHeight(40)
        cond_row = QHBoxLayout(cond_box)
        cond_row.setContentsMargins(0, 1, 0, 1)
        cond_row.setSpacing(10)
        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        self.condition_combo.currentIndexChanged.connect(self._sync_condition_ui)
        self.category_badge = QLabel()
        cond_row.addWidget(self.condition_combo)
        cond_row.addWidget(self.category_badge)
        cond_row.addStretch()
        form.addRow("Ýagdaýy:", cond_box)

        root.addLayout(form)

        # Conditional B/U fields (shown only for standalone phones when B/U is selected)
        self.used_fields_box = QWidget()
        used_form = QFormLayout(self.used_fields_box)
        used_form.setContentsMargins(0, 0, 0, 0)
        used_form.setSpacing(10)
        self.battery_input = QLineEdit()
        self.battery_input.setPlaceholderText("88%, 92%...")
        used_form.addRow("Batareýa %:", self.battery_input)
        self.cosmetic_input = QLineEdit()
        self.cosmetic_input.setPlaceholderText("Arassa, korpusda çyzyk ýok, komplekt...")
        used_form.addRow("Umumy ýagdaýy:", self.cosmetic_input)
        root.addWidget(self.used_fields_box)

        form2 = QFormLayout()
        form2.setSpacing(10)

        self.status_combo = style_combo(QComboBox())
        for label, code in STOCK_ITEM_STATUSES:
            self.status_combo.addItem(label, code)
        form2.addRow("Status:", self.status_combo)

        self.source_combo = style_combo(QComboBox())
        self.source_combo.addItem("— Görkezilmedik —", "")
        for label, code in SOURCES:
            self.source_combo.addItem(label, code)
        form2.addRow("Çeşme:", self.source_combo)

        cost_box = QWidget()
        cost_box.setMinimumHeight(40)
        cost_row = QHBoxLayout(cost_box)
        cost_row.setContentsMargins(0, 1, 0, 1)
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        cost_row.addWidget(self.cost_spin, 1)
        cost_row.addWidget(self.cost_curr_combo)
        cost_row.addWidget(QLabel("Kurs:"))
        cost_row.addWidget(self.rate_spin)
        form2.addRow("Öz bahasy:", cost_box)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Goşmaça bellik...")
        form2.addRow("Bellik:", self.notes_input)

        root.addLayout(form2)

        footer = QHBoxLayout()
        self.delete_btn = make_button("🗑 Poz", "danger")
        self.delete_btn.clicked.connect(self._delete_item)
        self.delete_btn.hide()
        footer.addWidget(self.delete_btn)

        self.history_btn = make_button("📜 IMEI taryhy")
        self.history_btn.clicked.connect(self._open_imei_history)
        self.history_btn.hide()
        footer.addWidget(self.history_btn)

        footer.addStretch()
        cancel_btn = make_button("Ýatyr")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("Üýtgeşmeleri ýatda sakla", "primary")
        save_btn.clicked.connect(self._save)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, save_btn, cancel_btn)

    def _sync_condition_ui(self) -> None:
        if not self.is_phone_unit:
            self.category_badge.hide()
            self.used_fields_box.hide()
            return
        is_used = self.condition_combo.currentData() == "used"
        self.category_badge.show()
        _apply_phone_category_badge(self.category_badge, is_used)
        self.used_fields_box.setVisible(is_used)

    def _load_data(self) -> None:
        from app.models.product import Product
        from app.models.stock_item import StockItem

        with SessionLocal() as session:
            st = session.get(StockItem, self.stock_item_id)
            if st is None:
                QMessageBox.warning(self, "Tapylmady", "Enjam bazada tapylmady.")
                self.reject()
                return
            prod = session.get(Product, st.product_id)
            self.is_phone_unit = bool(prod is not None and getattr(prod, "is_phone_unit", False))
            self._product_name = prod.name if prod is not None else ""
            self._imei1_loaded = st.imei1 or ""

            if self.is_phone_unit:
                self.setWindowTitle(f"Telefony üýtgetmek — {self._product_name}")
                self.title_label.setText(f"Telefony üýtgetmek — {self._product_name}")
                self.legacy_product_box.hide()
                self.phone_identity_box.show()
                self.delete_btn.show()
                self.history_btn.show()

                try:
                    models = list_distinct_phone_models()
                except SQLAlchemyError:
                    models = []
                completer = QCompleter(models, self)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                self.model_name_input.setCompleter(completer)

                self.model_name_input.setText(prod.name if prod is not None else "")
                self.memory_input.setText(st.memory or "")
                self.color_input.setText(st.color or "")
                self.battery_input.setText(st.battery_health or "")
                self.cosmetic_input.setText(st.cosmetic_condition or "")
            else:
                self.legacy_product_box.show()
                self.phone_identity_box.hide()
                self.used_fields_box.hide()
                self.category_badge.hide()

                products, _cats = list_products_inventory(include_archived=True)
                self.product_combo.clear()
                for p in products:
                    if p.get("is_phone_unit") and p["id"] != st.product_id:
                        continue
                    suffix = " [ARHIW]" if not p.get("is_active", True) else ""
                    cat_part = f" ({p['category']})" if p.get("category") else ""
                    self.product_combo.addItem(f"{p['name']}{cat_part}{suffix}", p["id"])
                idx = self.product_combo.findData(st.product_id)
                if idx >= 0:
                    self.product_combo.setCurrentIndex(idx)

            self.imei1_input.setText(st.imei1 or "")
            self.imei2_input.setText(st.imei2 or "")
            self.sn_input.setText(st.serial_number or "")
            c_idx = self.condition_combo.findData("used" if st.condition != "new" else "new")
            if c_idx >= 0:
                self.condition_combo.setCurrentIndex(c_idx)
            s_idx = self.status_combo.findData(st.status)
            if s_idx >= 0:
                self.status_combo.setCurrentIndex(s_idx)
            src_idx = self.source_combo.findData(st.acquisition_source or "")
            if src_idx >= 0:
                self.source_combo.setCurrentIndex(src_idx)
            if st.unit_cost is not None:
                self.cost_spin.setValue(float(st.unit_cost))
            if st.cost_currency in ("USD", "TMT"):
                self.cost_curr_combo.setCurrentText(st.cost_currency)
            if st.cost_exchange_rate is not None and float(st.cost_exchange_rate) > 0:
                self.rate_spin.setValue(float(st.cost_exchange_rate))
            self.notes_input.setText(st.notes or "")

        self._sync_condition_ui()

    def _delete_item(self) -> None:
        ans = QMessageBox.question(
            self,
            "Telefony pozmak",
            f"«{self._product_name}» (IMEI: {self._imei1_loaded}) telefonyny skladyň sanawyndan pozmalymy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_stock_item(self.stock_item_id)
            show_toast(self.parentWidget() or self, "Telefon üstünlikli pozuldy.", kind="success")
            self.accept()
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Pozup bolmady", str(err))

    def _open_imei_history(self) -> None:
        from app.ui.reports_page import ImeiHistoryDialog

        dlg = ImeiHistoryDialog(
            self.stock_item_id,
            self.imei1_input.text().strip() or self._imei1_loaded,
            self.model_name_input.text().strip() or self._product_name,
            self,
        )
        dlg.exec()

    def _save(self) -> None:
        try:
            if self.is_phone_unit:
                cond = self.condition_combo.currentData() or "new"
                is_used = cond == "used"
                update_standalone_phone(
                    stock_item_id=self.stock_item_id,
                    model_name=self.model_name_input.text(),
                    imei1=self.imei1_input.text(),
                    memory=self.memory_input.text(),
                    color=self.color_input.text(),
                    imei2=self.imei2_input.text(),
                    serial_number=self.sn_input.text(),
                    condition=cond,
                    status=self.status_combo.currentData(),
                    battery_health=self.battery_input.text() if is_used else None,
                    cosmetic_condition=self.cosmetic_input.text() if is_used else None,
                    unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                    cost_currency=self.cost_curr_combo.currentText(),
                    cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                    acquisition_source=self.source_combo.currentData() or None,
                    notes=self.notes_input.text(),
                )
            else:
                pid = self.product_combo.currentData()
                if pid is None:
                    QMessageBox.warning(self, "Ýalňyşlyk", "Haryt modelini saýlaň.")
                    return
                update_stock_item(
                    stock_item_id=self.stock_item_id,
                    product_id=int(pid),
                    imei1=self.imei1_input.text(),
                    imei2=self.imei2_input.text(),
                    serial_number=self.sn_input.text(),
                    condition=self.condition_combo.currentData(),
                    status=self.status_combo.currentData(),
                    unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                    cost_currency=self.cost_curr_combo.currentText(),
                    cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                    acquisition_source=self.source_combo.currentData() or None,
                    notes=self.notes_input.text(),
                )
            show_toast(
                self.parentWidget() or self,
                "Enjamyň maglumatlary üstünlikli täzelendi.",
                kind="success",
            )
            self.accept()
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Üýtgeşmeleri saklap bolmady:\n{err}")


class StockItemDialog(QDialog):
    """Haryt karty: IMEI boýunça enjamlar (täze we B/U), hasaba alyş we hereket taryhy."""

    def __init__(
        self,
        product_id: int | None = None,
        product_name: str = "",
        default_condition: str = "new",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.product_id = product_id
        self.product_name = product_name
        self.default_condition = default_condition
        self._products_cache: list[dict] = []

        self.setWindowTitle(
            f"Haryt karty we enjamlar — {product_name}"
            if product_name
            else "Enjamy hasaba almak (IMEI)"
        )
        self.setMinimumSize(880, 620)
        self.setStyleSheet(theme.STYLE)

        self._build_ui()
        self._reload_products_combo()
        self._load_items()
        self.imei1_input.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.title_label = QLabel("Haryt karty we aýratyn enjamlar (IMEI)")
        self.title_label.setObjectName("pageTitle")
        top.addWidget(self.title_label, 1)

        edit_prod_btn = make_button("✏ Harydy üýtget")
        edit_prod_btn.clicked.connect(self._edit_current_product)
        top.addWidget(edit_prod_btn)
        root.addLayout(top)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedText")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_devices_tab(), "📱 Enjamlar (IMEI) we hasaba alyş")
        self.tabs.addTab(self._build_history_tab(), "📜 Alyş, satyş we hereket taryhy")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        edit_imei_btn = make_button("✏ Saýlanan enjamy üýtget", "primary")
        edit_imei_btn.clicked.connect(self._edit_selected_stock_item)
        footer.addWidget(edit_imei_btn)

        del_imei_btn = make_button("🗑 Enjamy poz", "danger")
        del_imei_btn.clicked.connect(self._delete_selected_stock_item)
        footer.addWidget(del_imei_btn)

        imei_hist_btn = make_button("📜 Saýlanan IMEI-niň doly taryhy")
        imei_hist_btn.clicked.connect(self._open_selected_imei_history)
        footer.addWidget(imei_hist_btn)
        footer.addStretch()

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, self.add_device_btn, close_btn)

    def _build_devices_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        add_card = Card(margins=(16, 14, 16, 14), spacing=10)
        add_title = QLabel("Enjamy sklada hasaba al (Täze ýa-da B/U)")
        add_title.setObjectName("cardTitle")
        add_card.body.addWidget(add_title)

        form = QFormLayout()
        form.setSpacing(8)

        prod_row = QHBoxLayout()
        self.product_combo = style_combo(QComboBox())
        self.product_combo.currentIndexChanged.connect(self._on_product_combo_changed)
        prod_row.addWidget(self.product_combo, 1)
        new_prod_btn = make_button("+ Täze model döret")
        new_prod_btn.clicked.connect(self._create_new_product)
        prod_row.addWidget(new_prod_btn)
        form.addRow("Model / Haryt *:", prod_row)

        row1 = QHBoxLayout()
        self.imei1_input = QLineEdit()
        self.imei1_input.setPlaceholderText("IMEI 1 (hökmany)*")
        self.imei2_input = QLineEdit()
        self.imei2_input.setPlaceholderText("IMEI 2 (hökmany däl)")
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("Seriýa belgisi (S/N)")
        row1.addWidget(self.imei1_input, 2)
        row1.addWidget(self.imei2_input, 2)
        row1.addWidget(self.sn_input, 1)
        form.addRow("Belgiler:", row1)

        row2 = QHBoxLayout()
        self.condition_combo = style_combo(QComboBox())
        self.condition_combo.addItem("Täze", "new")
        self.condition_combo.addItem("B/U (Ulanylan)", "used")
        if self.default_condition == "used":
            self.condition_combo.setCurrentIndex(1)

        self.source_combo = style_combo(QComboBox())
        for label, code in SOURCES:
            self.source_combo.addItem(label, code)
        if self.default_condition == "used":
            self.source_combo.setCurrentIndex(1)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 10000000)
        self.cost_spin.setDecimals(2)
        self.cost_curr_combo = style_combo(QComboBox())
        self.cost_curr_combo.addItems(["USD", "TMT"])
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0001, 100000)
        self.rate_spin.setDecimals(4)
        self.rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))

        row2.addWidget(QLabel("Ýagdaýy:"))
        row2.addWidget(self.condition_combo)
        row2.addWidget(QLabel("Çeşme:"))
        row2.addWidget(self.source_combo)
        row2.addWidget(QLabel("Öz bahasy:"))
        row2.addWidget(self.cost_spin)
        row2.addWidget(self.cost_curr_combo)
        row2.addWidget(QLabel("Kurs:"))
        row2.addWidget(self.rate_spin)
        form.addRow("Şertler:", row2)

        row3 = QHBoxLayout()
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(
            "Bellik: korpusyň ýagdaýy, batareýa %, komplekt (hökmany däl)..."
        )
        self.add_device_btn = make_button("+ Enjamy sklada goş", "primary")
        self.add_device_btn.clicked.connect(self._add_stock_item)
        row3.addWidget(self.notes_input, 1)
        row3.addWidget(self.add_device_btn)
        form.addRow("Bellik:", row3)

        add_card.body.addLayout(form)
        layout.addWidget(add_card)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "IMEI 1",
            "IMEI 2 / S/N",
            "Ýagdaýy",
            "Çeşme",
            "Öz bahasy",
            "Status",
            "Bellik",
        ])
        configure_table(self.table, stretch_col=[1, 7], row_height=42)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._edit_selected_stock_item())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._edit_selected_stock_item)
        layout.addWidget(self.table, 1)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels([
            "Sene",
            "Amal",
            "Üýtgeşme",
            "Resminama",
            "Baha / Öz bahasy",
            "Jikme-jik",
        ])
        configure_table(self.history_table, stretch_col=5, row_height=42)
        layout.addWidget(self.history_table, 1)
        return tab

    def _reload_products_combo(self) -> None:
        products, _cats = list_products_inventory()
        self._products_cache = products
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        for p in products:
            if p.get("is_phone_unit") and p["id"] != self.product_id:
                continue
            cat_part = f" ({p['category']})" if p.get("category") else ""
            self.product_combo.addItem(f"{p['name']}{cat_part}", p["id"])
        if self.product_id is not None:
            idx = self.product_combo.findData(self.product_id)
            if idx >= 0:
                self.product_combo.setCurrentIndex(idx)
        elif self.product_combo.count() > 0:
            self.product_combo.setCurrentIndex(0)
            self.product_id = self.product_combo.currentData()
        self.product_combo.blockSignals(False)

    def _on_product_combo_changed(self) -> None:
        self.product_id = self.product_combo.currentData()
        self._load_items()

    def _create_new_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec() and dlg.created_product_id is not None:
            self.product_id = dlg.created_product_id
            self._reload_products_combo()
            self._load_items()

    def _edit_current_product(self) -> None:
        if self.product_id is None:
            return
        dlg = ProductDialog(self, product_id=self.product_id)
        if dlg.exec():
            self._reload_products_combo()
            self._load_items()

    def _load_items(self) -> None:
        if self.product_id is None:
            return
        product, in_stock_cnt, items = get_product_with_devices(self.product_id)
        if product is None:
            return

        self.product_name = product.name
        self.title_label.setText(f"{product.name} ({product.sku})")
        new_in_stock = sum(1 for i in items if i.status == "in_stock" and i.condition == "new")
        used_in_stock = sum(1 for i in items if i.status == "in_stock" and i.condition != "new")
        brand_model = " / ".join(filter(None, [product.brand, product.model])) or "—"

        self.summary_label.setText(
            f"Brend / Model: {brand_model}   |   "
            f"Skladdaky jemi galyndy: {product.stock_quantity} sany (iň azy: {product.min_stock_quantity})   |   "
            f"IMEI-li bar enjamlar: {in_stock_cnt} (Täze: {new_in_stock}, B/U: {used_in_stock})   |   "
            f"Jemi IMEI ýazgysy: {len(items)}"
        )

        self.table.setRowCount(len(items))
        now = datetime.now()
        for r, it in enumerate(items):
            cost_text = (
                f"{money_str(it.unit_cost)} {it.cost_currency or ''}".strip()
                if it.unit_cost is not None
                else "—"
            )
            if it.status == "in_stock":
                days = max(0, (now - it.created_at).days) if it.created_at else 0
                status_text = f"Bar ({days} gün)"
            elif it.status == "written_off":
                status_text = "Hasapdan çykaryldy"
            else:
                status_text = "Satyldy"
            cond_text = "Täze" if it.condition == "new" else "B/U"
            imei2_sn = " / ".join(filter(None, [it.imei2, it.serial_number])) or "—"
            src_text = SOURCE_LABELS.get(it.acquisition_source or "", it.acquisition_source or "—")

            vals = [
                str(it.id),
                it.imei1,
                imei2_sn,
                cond_text,
                src_text,
                cost_text,
                status_text,
                it.notes or "—",
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 3, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    cell.setForeground(
                        QColor(theme.BLUE if it.condition == "new" else theme.ACCENT)
                    )
                if c == 6:
                    cell.setForeground(
                        QColor(theme.GREEN if it.status == "in_stock" else theme.MUTED)
                    )
                self.table.setItem(r, c, cell)

        with SessionLocal() as session:
            events = ReportService.get_product_history(session, self.product_id)

        self.history_table.setRowCount(len(events))
        for i, ev in enumerate(events):
            d_str = ev["date"].strftime("%d.%m.%Y %H:%M") if ev["date"] else "—"
            vals = [
                d_str,
                ev["event_type"],
                ev["quantity_change"],
                ev["document"],
                ev["price_info"],
                ev["details"],
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (2, 3, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 2:
                    cell.setForeground(
                        QColor(theme.GREEN if val.startswith("+") else theme.RED)
                    )
                self.history_table.setItem(i, c, cell)

    def _add_stock_item(self) -> None:
        if self.product_id is None:
            QMessageBox.warning(self, "Haryt saýlaň", "Ilki haryt modelini saýlaň ýa-da dörediň.")
            return
        try:
            register_stock_item(
                product_id=self.product_id,
                imei1=self.imei1_input.text(),
                imei2=self.imei2_input.text(),
                serial_number=self.sn_input.text(),
                condition=self.condition_combo.currentData(),
                unit_cost=Decimal(f"{self.cost_spin.value():.2f}"),
                cost_currency=self.cost_curr_combo.currentText(),
                cost_exchange_rate=Decimal(f"{self.rate_spin.value():.4f}"),
                acquisition_source=self.source_combo.currentData(),
                notes=self.notes_input.text(),
                increment_stock=True,
            )
            self.imei1_input.clear()
            self.imei2_input.clear()
            self.sn_input.clear()
            self.notes_input.clear()
            self._load_items()
            self.imei1_input.setFocus()
            show_toast(self, "Enjam sklada üstünlikli hasaba alyndy.", kind="success")
        except ValueError as err:
            QMessageBox.warning(self, "Maglumatlary barlaň", str(err))
        except (IntegrityError, SQLAlchemyError) as err:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Enjamy ýatda saklap bolmady:\n{err}")

    def _edit_selected_stock_item(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Üýtgetmek üçin tablisadan enjam setirini saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        if not id_cell:
            return
        dlg = EditStockItemDialog(int(id_cell.text()), self)
        if dlg.exec():
            self._load_items()

    def _delete_selected_stock_item(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Pozmak üçin tablisadan enjam setirini saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        imei_cell = self.table.item(row, 1)
        if not id_cell or not imei_cell:
            return
        ans = QMessageBox.question(
            self,
            "Enjamy pozmak",
            f"IMEI {imei_cell.text()} enjamyny skladyň sanawyndan hakykatdan hem pozmalymy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_stock_item(int(id_cell.text()))
            self._load_items()
            show_toast(self, "Enjam üstünlikli pozuldy.", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Pozup bolmady", str(err))

    def _open_selected_imei_history(self) -> None:
        from app.ui.reports_page import ImeiHistoryDialog

        row = self.table.currentRow()
        if row < 0:
            show_toast(self, "Doly taryhyny görmek üçin tablisadan enjam setirini saýlaň.", kind="info")
            return
        id_cell = self.table.item(row, 0)
        imei_cell = self.table.item(row, 1)
        if not id_cell or not imei_cell:
            return
        dlg = ImeiHistoryDialog(
            int(id_cell.text()),
            imei_cell.text(),
            self.product_name,
            self,
        )
        dlg.exec()


class StockPage(QWidget):
    """Harytlar we sklad bölümi."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        self.products: list[dict] = []
        self.categories: dict[int, str] = {}

        self._build_ui()
        self._load_data()

    def refresh_data(self) -> None:
        self._load_data()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Harytlar we sklad")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Haryt katalogi, sklad galyndylary, täze we B/U telefonlaryň IMEI hasaby"
        )
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        self.count_label = QLabel("Jemi: 0")
        self.count_label.setObjectName("mutedText")
        header.addWidget(self.count_label)

        cat_btn = make_button("Kategoriýalar")
        cat_btn.clicked.connect(self._open_category_management)
        header.addWidget(cat_btn)

        used_btn = make_button("+ Enjam (IMEI)")
        used_btn.clicked.connect(lambda: self._open_device_intake(default_condition="new"))
        header.addWidget(used_btn)

        add_prod_btn = make_button("+ Haryt goş (Ctrl+N)", "primary")
        add_prod_btn.clicked.connect(self._open_add_product)
        header.addWidget(add_prod_btn)

        self.add_product_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.add_product_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.add_product_shortcut.activated.connect(self._open_add_product)

        refresh_btn = make_button("↻ Täzele")
        refresh_btn.clicked.connect(self._load_data)
        header.addWidget(refresh_btn)

        layout.addLayout(header)

        # Görkeziji kartlary
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(14)

        self.total_value = QLabel("0")
        self.devices_value = QLabel("0 (Täze: 0 • B/U: 0)")
        self.low_stock_value = QLabel("0")
        self.out_of_stock_value = QLabel("0")

        stats_layout.addWidget(
            make_stat_card("Katalogdaky harytlar", self.total_value, theme.NAVY, "Işjeň modeller we aksessuarlar")
        )
        stats_layout.addWidget(
            make_stat_card(
                "IMEI boýunça bar enjamlar",
                self.devices_value,
                theme.BLUE,
                "Telefonlaryň aýratyn hasaby",
                small_value=True,
            )
        )
        stats_layout.addWidget(
            make_stat_card("Az galyndy", self.low_stock_value, theme.ACCENT, "Üstüni ýetirmeli")
        )
        stats_layout.addWidget(
            make_stat_card("Skladda ýok", self.out_of_stock_value, theme.RED, "Galyndysy nol")
        )
        layout.addLayout(stats_layout)

        # Gözleg we süzgüçler
        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Ady, kategoriýa, brend, model, referens, ştrihkod ýa-da IMEI boýunça gözleg..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._filter_products)

        self.category_filter = style_combo(QComboBox())
        self.category_filter.setMinimumWidth(175)
        self.category_filter.setMinimumHeight(40)
        self.category_filter.addItem("Ähli kategoriýalar", None)
        self.category_filter.currentIndexChanged.connect(self._filter_products)

        self.status_filter = style_combo(QComboBox())
        self.status_filter.setMinimumWidth(190)
        self.status_filter.setMinimumHeight(40)
        self.status_filter.addItem("Ähli işjeň harytlar", "all")
        self.status_filter.addItem("Skladda bar", "in_stock")
        self.status_filter.addItem("B/U enjamlar bar", "has_used")
        self.status_filter.addItem("Köp duran (> 30 gün)", "stale_30")
        self.status_filter.addItem("Az galyndy", "low_stock")
        self.status_filter.addItem("Skladda ýok", "out_of_stock")
        self.status_filter.addItem("📦 Arhiwdäki harytlar", "archived")
        self.status_filter.currentIndexChanged.connect(self._filter_products)

        self.group_combo = style_combo(QComboBox())
        self.group_combo.setMinimumWidth(205)
        self.group_combo.setMinimumHeight(40)
        self.group_combo.addItem("Topar: Ady boýunça", "name")
        self.group_combo.addItem("Topar: Brend boýunça", "brand")
        self.group_combo.addItem("Topar: Kategoriýa boýunça", "category")
        self.group_combo.addItem("Toparlama: Öçük", "none")
        self._sync_group_combo()
        self.group_combo.currentIndexChanged.connect(self._on_group_mode_changed)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.category_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.group_combo)
        layout.addLayout(filters)

        # Harytlar we galyndylar agajy (toparlanan ýa-da adaty sanaw)
        self.tree = QTreeWidget()
        self.table = self.tree
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([
            "Harydyň ady",
            "Kategoriýa",
            "Brend / Model",
            "Öz bahasy",
            "Skladda",
            "IMEI (Täze / B/U)",
            "Status",
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(22)

        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 125), (2, 145), (3, 105), (4, 85), (5, 130), (6, 100)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(col, width)

        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._on_item_activated)
        layout.addWidget(self.tree, 1)

        # Sanawyň aşagyndaky amallar paneli
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(10)

        details_btn = make_button("📱 Haryt karty we enjamlar (IMEI)", "primary")
        details_btn.clicked.connect(self._open_selected_imei_dialog)
        actions_bar.addWidget(details_btn)

        edit_btn = make_button("✏ Harydy üýtget")
        edit_btn.clicked.connect(self._edit_selected_product)
        actions_bar.addWidget(edit_btn)

        self.archive_btn = make_button("📦 Arhiwe geçir / ♻ Dikelt")
        self.archive_btn.clicked.connect(self._toggle_archive_selected_product)
        actions_bar.addWidget(self.archive_btn)

        history_btn = make_button("📜 Hereket taryhy")
        history_btn.clicked.connect(self._open_selected_product_history)
        actions_bar.addWidget(history_btn)

        actions_bar.addStretch()
        hint = QLabel(
            "Iki gezek / Enter: telefon (IMEI) — enjamy üýtgetmek, sanly haryt — harydy üýtgetmek."
        )
        hint.setObjectName("mutedText")
        actions_bar.addWidget(hint)
        layout.addLayout(actions_bar)

    def _sync_group_combo(self) -> None:
        mode = SettingsService.get_stock_group_mode()
        self.group_combo.blockSignals(True)
        idx = self.group_combo.findData(mode)
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
        self.group_combo.blockSignals(False)

    def _on_group_mode_changed(self) -> None:
        mode = self.group_combo.currentData() or "name"
        SettingsService.set_stock_group_mode(mode)
        self._filter_products()

    def _load_data(self) -> None:
        self._sync_group_combo()
        self.products, self.categories = list_products_inventory(include_archived=True)
        self._update_statistics()
        self._update_category_filter()
        self._filter_products()

    def _update_statistics(self) -> None:
        active_products = [
            p
            for p in self.products
            if p.get("is_active", True) and not p.get("phone_sold", False)
        ]
        total = len(active_products)
        new_devs = sum(p["new_devices"] for p in active_products)
        used_devs = sum(p["used_devices"] for p in active_products)
        low_stock = sum(
            1
            for p in active_products
            if not p.get("is_phone_unit", False)
            and p["quantity"] > 0
            and p["minimum"] > 0
            and p["quantity"] <= p["minimum"]
        )
        out_of_stock = sum(
            1
            for p in active_products
            if not p.get("is_phone_unit", False) and p["quantity"] == 0
        )

        self.total_value.setText(str(total))
        self.devices_value.setText(f"{new_devs + used_devs} (Täze: {new_devs} • B/U: {used_devs})")
        self.low_stock_value.setText(str(low_stock))
        self.out_of_stock_value.setText(str(out_of_stock))

    def _update_category_filter(self) -> None:
        selected_category = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Ähli kategoriýalar", None)
        for category_id, name in self.categories.items():
            self.category_filter.addItem(name, category_id)
        index = self.category_filter.findData(selected_category)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _filter_products(self, *_args) -> None:
        search = self.search_input.text().strip().lower()
        tokens = search.split() if search else []
        category_id = self.category_filter.currentData()
        status_mode = self.status_filter.currentData()

        filtered = []
        for p in self.products:
            is_active = p.get("is_active", True)
            is_phone = bool(p.get("is_phone_unit", False))
            phone_sold = bool(p.get("phone_sold", False))

            if status_mode == "archived":
                if is_active:
                    continue
            else:
                if not is_active:
                    continue
                # Sold standalone phone units disappear from warehouse & active stock filters
                if phone_sold:
                    continue
            if category_id is not None and p["category_id"] != category_id:
                continue
            if status_mode == "in_stock":
                if is_phone:
                    if p.get("devices_in_stock", 0) <= 0:
                        continue
                elif p["quantity"] <= 0:
                    continue
            if status_mode == "has_used" and p["used_devices"] <= 0:
                continue
            if status_mode == "stale_30" and p.get("max_days_in_stock", 0) < 30:
                continue
            if status_mode == "low_stock" and (
                is_phone or not (0 < p["quantity"] <= p["minimum"] and p["minimum"] > 0)
            ):
                continue
            if status_mode == "out_of_stock" and (is_phone or p["quantity"] != 0):
                continue

            if tokens:
                searchable = " ".join([
                    p["name"],
                    p["category"],
                    p["brand"],
                    p["model"],
                    p.get("reference", ""),
                    p.get("barcode", ""),
                    p["imei_search_blob"],
                ]).lower()
                if not all(tok in searchable for tok in tokens):
                    continue

            filtered.append(p)

        self._show_products(filtered, has_search=bool(tokens))

    def _make_product_tree_item(self, p: dict) -> QTreeWidgetItem:
        is_phone = bool(p.get("is_phone_unit", False))

        if is_phone:
            spec_parts = [x for x in (p.get("memory"), p.get("color")) if x]
            if p.get("phone_condition") != "new" and p.get("battery_health"):
                bh = str(p["battery_health"]).strip()
                spec_parts.append(bh if bh.lower().startswith("bat") else f"Bat: {bh}")
            brand_model = " • ".join(spec_parts) or p.get("specification") or "—"

            stock_col = "IMEI"

            cond_lbl = "Täze" if p.get("phone_condition") == "new" else "B/U"
            if cond_lbl == "B/U" and p.get("battery_health"):
                cond_badge = f"B/U • {str(p['battery_health']).strip()}"
            else:
                cond_badge = cond_lbl
            imei1 = (p.get("imei1") or "").strip()
            imei_summary = f"{imei1} ({cond_badge})" if imei1 else cond_badge

            if not p.get("is_active", True):
                status = "Arhiw"
                color = theme.MUTED
            elif p.get("phone_sold"):
                status = "Satyldy"
                color = theme.MUTED
            else:
                status = "Bar"
                color = theme.GREEN
        else:
            brand_model = " / ".join(filter(None, [p["brand"], p["model"]])) or "—"
            stock_col = f"{p['quantity']} sany"
            if p["total_devices"] > 0:
                imei_summary = f"Täze: {p['new_devices']} • B/U: {p['used_devices']}"
            else:
                imei_summary = "San boýunça hasap"

            if not p.get("is_active", True):
                status = "Arhiw"
                color = theme.MUTED
            elif p["quantity"] == 0:
                status = "Skladda ýok"
                color = theme.RED
            elif p["minimum"] > 0 and p["quantity"] <= p["minimum"]:
                status = "Az galyndy"
                color = theme.ACCENT
            else:
                status = "Bar"
                color = theme.GREEN

        item = QTreeWidgetItem([
            p["name"],
            p["category"],
            brand_model,
            p.get("cost_display", "—"),
            stock_col,
            imei_summary,
            status,
        ])
        for col in (3, 4, 5, 6):
            item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

        if is_phone:
            item.setForeground(
                5,
                QColor(theme.BLUE if p.get("phone_condition") == "new" else theme.ACCENT),
            )

        status_font = QFont(self.tree.font())
        status_font.setBold(True)
        item.setFont(6, status_font)
        item.setForeground(6, QColor(color))
        item.setSizeHint(0, QSize(0, 42))

        tooltip_parts = []
        if is_phone:
            if p.get("imei1"):
                tooltip_parts.append(f"IMEI 1: {p['imei1']}")
            if p.get("imei2"):
                tooltip_parts.append(f"IMEI 2: {p['imei2']}")
            if p.get("serial_number"):
                tooltip_parts.append(f"S/N: {p['serial_number']}")
            if p.get("memory"):
                tooltip_parts.append(f"Ýat: {p['memory']}")
            if p.get("color"):
                tooltip_parts.append(f"Reňk: {p['color']}")
            if p.get("battery_health"):
                tooltip_parts.append(f"Batareýa: {p['battery_health']}")
            if p.get("cosmetic_condition"):
                tooltip_parts.append(f"Umumy ýagdaýy: {p['cosmetic_condition']}")
        else:
            if p.get("reference"):
                tooltip_parts.append(f"Referens (OCR): {p['reference']}")
            if p.get("barcode"):
                tooltip_parts.append(f"Ştrihkod: {p['barcode']}")
            if p.get("minimum"):
                tooltip_parts.append(f"Iň az galyndy: {p['minimum']} sany")
        if tooltip_parts:
            tip = "\n".join(tooltip_parts)
            for col in range(7):
                item.setToolTip(col, tip)

        item.setData(0, ROLE_ITEM_TYPE, "product")
        item.setData(0, ROLE_PRODUCT_ID, p["id"])
        item.setData(0, ROLE_PRODUCT_NAME, p["name"])
        item.setData(0, ROLE_IS_ACTIVE, bool(p.get("is_active", True)))
        item.setData(0, ROLE_TOTAL_DEVICES, int(p.get("total_devices", 0)))
        item.setData(0, ROLE_IS_PHONE_UNIT, is_phone)
        item.setData(0, ROLE_PRIMARY_STOCK_ITEM_ID, p.get("primary_stock_item_id"))
        return item

    def _iter_tree_items(self) -> list[QTreeWidgetItem]:
        """Возвращает плоский список всех элементов дерева в порядке отображения."""
        result: list[QTreeWidgetItem] = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is None:
                continue
            result.append(top)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch is not None:
                    result.append(ch)
        return result

    def _capture_tree_state(self) -> dict:
        cur = self.tree.currentItem()
        all_items = self._iter_tree_items()
        flat_idx = all_items.index(cur) if cur in all_items else -1
        collapsed_keys: set[str] = set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is not None and top.data(0, ROLE_ITEM_TYPE) == "group" and not top.isExpanded():
                gk = top.data(0, ROLE_GROUP_KEY)
                if gk:
                    collapsed_keys.add(str(gk))
        return {
            "item_type": cur.data(0, ROLE_ITEM_TYPE) if cur is not None else None,
            "product_id": cur.data(0, ROLE_PRODUCT_ID) if cur is not None else None,
            "stock_item_id": cur.data(0, ROLE_PRIMARY_STOCK_ITEM_ID) if cur is not None else None,
            "group_key": cur.data(0, ROLE_GROUP_KEY) if cur is not None else None,
            "flat_idx": flat_idx,
            "scroll_val": self.tree.verticalScrollBar().value(),
            "collapsed_keys": collapsed_keys,
            "had_focus": self.tree.hasFocus(),
        }

    def _restore_tree_state(
        self,
        state: dict | None,
        prefer_product_id: int | None = None,
        force_focus: bool = False,
    ) -> None:
        if not state and prefer_product_id is None:
            return
        all_items = self._iter_tree_items()
        if not all_items:
            return

        target: QTreeWidgetItem | None = None
        if prefer_product_id is not None:
            for it in all_items:
                if it.data(0, ROLE_ITEM_TYPE) == "product" and it.data(0, ROLE_PRODUCT_ID) == prefer_product_id:
                    target = it
                    break

        if target is None and state:
            if state.get("item_type") == "product":
                pid = state.get("product_id")
                sid = state.get("stock_item_id")
                for it in all_items:
                    if it.data(0, ROLE_ITEM_TYPE) != "product":
                        continue
                    if (pid is not None and it.data(0, ROLE_PRODUCT_ID) == pid) or (
                        sid is not None and it.data(0, ROLE_PRIMARY_STOCK_ITEM_ID) == sid
                    ):
                        target = it
                        break
            elif state.get("item_type") == "group" and state.get("group_key"):
                gk = state["group_key"]
                for it in all_items:
                    if it.data(0, ROLE_ITEM_TYPE) == "group" and it.data(0, ROLE_GROUP_KEY) == gk:
                        target = it
                        break

            if target is None and state.get("flat_idx", -1) >= 0:
                idx = min(state["flat_idx"], len(all_items) - 1)
                target = all_items[idx]

        if target is not None:
            parent = target.parent()
            if parent is not None and not parent.isExpanded():
                parent.setExpanded(True)
            self.tree.setCurrentItem(target)

        scroll_val = state.get("scroll_val", 0) if state else 0
        sb = self.tree.verticalScrollBar()
        sb.setValue(min(scroll_val, sb.maximum()))

        def _apply_scroll_and_focus() -> None:
            try:
                cur_sb = self.tree.verticalScrollBar()
                if scroll_val > 0 and cur_sb.maximum() > 0:
                    cur_sb.setValue(min(scroll_val, cur_sb.maximum()))
                if target is not None:
                    self.tree.scrollToItem(target, QAbstractItemView.ScrollHint.EnsureVisible)
            except RuntimeError:
                return
            if force_focus or (state and state.get("had_focus")):
                self.tree.setFocus()

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, _apply_scroll_and_focus)

    def _show_products(self, products: list[dict], has_search: bool = False) -> None:
        prev_state = self._capture_tree_state()
        collapsed_keys = prev_state.get("collapsed_keys", set())

        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            group_mode = self.group_combo.currentData() or "name"

            if group_mode == "none":
                self.tree.setRootIsDecorated(False)
                self.tree.setIndentation(0)
                for p in products:
                    self.tree.addTopLevelItem(self._make_product_tree_item(p))
                self.count_label.setText(f"Jemi: {len(products)}")
                return

            self.tree.setRootIsDecorated(True)
            self.tree.setIndentation(22)

            groups: dict[str, tuple[str, list[dict]]] = {}
            for p in products:
                if group_mode == "brand":
                    raw = (p.get("brand") or "").strip()
                    if raw:
                        key = raw.lower()
                        display = raw
                    elif p.get("is_phone_unit"):
                        key = "\ufffe__phones__"
                        display = "Telefonlar (IMEI)"
                    else:
                        key = "\uffff__no_brand__"
                        display = "Brendsiz"
                elif group_mode == "category":
                    raw = (p.get("category") or "").strip()
                    key = raw.lower() if raw else "\uffff__no_cat__"
                    display = raw if raw else "Kategoriýasyz"
                else:
                    raw = (p.get("name") or "").strip()
                    key = raw.lower() if raw else "\uffff__unnamed__"
                    display = raw if raw else "—"

                if key not in groups:
                    groups[key] = (display, [])
                groups[key][1].append(p)

            sorted_groups = sorted(groups.items(), key=lambda kv: kv[0])

            group_font = QFont(self.tree.font())
            group_font.setBold(True)
            group_bg = QColor("#EEF2F6")
            group_fg = QColor(theme.NAVY)

            for g_key, (label, items) in sorted_groups:
                quant_qty = sum(
                    int(x.get("quantity", 0)) for x in items if not x.get("is_phone_unit", False)
                )
                phone_cnt = sum(1 for x in items if x.get("is_phone_unit", False))
                total_devs = sum(int(x.get("total_devices", 0)) for x in items)
                g_new = sum(int(x.get("new_devices", 0)) for x in items)
                g_used = sum(int(x.get("used_devices", 0)) for x in items)

                if quant_qty > 0 and phone_cnt > 0:
                    qty_col = f"{quant_qty} sany / {phone_cnt} enjam"
                elif phone_cnt > 0:
                    qty_col = f"{phone_cnt} enjam"
                else:
                    qty_col = f"{quant_qty} sany"

                if group_mode == "name":
                    cats = list(dict.fromkeys(x["category"] for x in items if x.get("category")))
                    if len(cats) > 3:
                        cats_str = f"{', '.join(cats[:3])} +{len(cats) - 3}"
                    else:
                        cats_str = ", ".join(cats)
                    header_title = f"📁 {label}"
                    sub_col = f"{len(items)} enjam" if phone_cnt == len(items) else f"{len(items)} görnüş"
                    meta_col = cats_str
                elif group_mode == "brand":
                    header_title = f"🏷 {label}"
                    sub_col = f"{len(items)} haryt"
                    meta_col = ""
                else:
                    header_title = f"📂 {label}"
                    sub_col = f"{len(items)} haryt"
                    meta_col = ""

                imei_col = f"Täze: {g_new} • B/U: {g_used}" if total_devs > 0 else ""

                group_item = QTreeWidgetItem([
                    header_title,
                    sub_col,
                    meta_col,
                    "",
                    qty_col,
                    imei_col,
                    "",
                ])
                group_item.setData(0, ROLE_ITEM_TYPE, "group")
                group_item.setData(0, ROLE_GROUP_KEY, f"{group_mode}:{g_key}")
                group_item.setSizeHint(0, QSize(0, 38))
                for col in range(7):
                    group_item.setFont(col, group_font)
                    group_item.setBackground(col, group_bg)
                    group_item.setForeground(col, group_fg)
                for col in (4, 5):
                    group_item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

                for prod in items:
                    group_item.addChild(self._make_product_tree_item(prod))

                self.tree.addTopLevelItem(group_item)
                full_gk = f"{group_mode}:{g_key}"
                if (has_search or len(sorted_groups) <= 40) and full_gk not in collapsed_keys:
                    group_item.setExpanded(True)

            self.count_label.setText(f"Jemi: {len(products)} ({len(sorted_groups)} topar)")
        finally:
            self.tree.setUpdatesEnabled(True)
            self._restore_tree_state(
                prev_state,
                prefer_product_id=getattr(self, "_pending_select_product_id", None),
                force_focus=getattr(self, "_pending_restore_focus", False),
            )
            self._pending_select_product_id = None
            self._pending_restore_focus = False

    def _selected_product_meta(self, silent: bool = False) -> dict | None:
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_ITEM_TYPE) != "product":
            if not silent:
                show_toast(
                    self,
                    "Bu amaly ýerine ýetirmek üçin sanawdan haryt setirini saýlaň.",
                    kind="info",
                )
            return None
        return {
            "id": item.data(0, ROLE_PRODUCT_ID),
            "name": item.data(0, ROLE_PRODUCT_NAME) or item.text(0),
            "is_active": bool(item.data(0, ROLE_IS_ACTIVE)),
            "total_devices": int(item.data(0, ROLE_TOTAL_DEVICES) or 0),
            "is_phone_unit": bool(item.data(0, ROLE_IS_PHONE_UNIT)),
            "primary_stock_item_id": item.data(0, ROLE_PRIMARY_STOCK_ITEM_ID),
        }

    def _open_add_product(self) -> None:
        dlg = ProductDialog(self)
        if dlg.exec():
            self._pending_select_product_id = getattr(dlg, "created_product_id", None)
            self._pending_restore_focus = True
            self._load_data()

    def _edit_selected_product(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        if meta.get("is_phone_unit") and meta.get("primary_stock_item_id") is not None:
            dlg = EditStockItemDialog(int(meta["primary_stock_item_id"]), self)
            if dlg.exec():
                self._pending_select_product_id = meta["id"]
                self._pending_restore_focus = True
                self._load_data()
            else:
                self.tree.setFocus()
            return
        dlg = ProductDialog(self, product_id=meta["id"])
        if dlg.exec():
            self._pending_select_product_id = meta["id"]
            self._pending_restore_focus = True
            self._load_data()
        else:
            self.tree.setFocus()

    def _toggle_archive_selected_product(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        product_id = meta["id"]
        prod_name = meta["name"]
        is_active = meta["is_active"]

        if not is_active:
            try:
                restore_product(product_id)
                self._pending_select_product_id = product_id
                self._pending_restore_focus = True
                self._load_data()
                show_toast(
                    self,
                    f"«{prod_name}» harydy arhiwden işjeň kataloga gaýtaryldy.",
                    kind="success",
                )
            except (ValueError, SQLAlchemyError) as err:
                QMessageBox.warning(self, "Ýalňyşlyk", str(err))
            return

        ans = QMessageBox.question(
            self,
            "Harydy arhiwe geçirmek",
            f"«{prod_name}» harydyny arhiwe geçirmek isleýärsiňizmi?\n"
            "Skladda galyndy bolsa-da arhiwe geçiriler (galyndylar we taryh saklanar, islendik wagt dikeldip bolýar).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            self.tree.setFocus()
            return
        try:
            deactivate_product(product_id, force=True)
            self._pending_restore_focus = True
            self._load_data()
            show_toast(self, f"«{prod_name}» arhiwe geçirildi.", kind="success")
        except (ValueError, SQLAlchemyError) as err:
            QMessageBox.warning(self, "Ýalňyşlyk", str(err))

    def _open_category_management(self) -> None:
        dlg = CategoryManagementDialog(self)
        dlg.exec()
        self._load_data()

    def _open_device_intake(self, default_condition: str = "new") -> None:
        dlg = StandalonePhoneIntakeDialog(
            default_condition=default_condition,
            parent=self,
        )
        dlg.exec()
        self._load_data()

    def _open_selected_imei_dialog(self) -> None:
        meta = self._selected_product_meta()
        if meta is None:
            return
        if meta.get("is_phone_unit") and meta.get("primary_stock_item_id") is not None:
            dlg = EditStockItemDialog(int(meta["primary_stock_item_id"]), self)
            if dlg.exec():
                self._pending_select_product_id = meta["id"]
                self._pending_restore_focus = True
                self._load_data()
            else:
                self.tree.setFocus()
            return
        dlg = StockItemDialog(product_id=meta["id"], product_name=meta["name"], parent=self)
        dlg.exec()
        self._pending_select_product_id = meta["id"]
        self._pending_restore_focus = True
        self._load_data()

    def _open_selected_product_history(self) -> None:
        from app.ui.reports_page import ProductHistoryDialog

        meta = self._selected_product_meta()
        if meta is None:
            return
        dlg = ProductHistoryDialog(meta["id"], meta["name"], self)
        dlg.exec()
        self.tree.setFocus()

    def _activate_tree_item(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        item_type = item.data(0, ROLE_ITEM_TYPE)
        if item_type == "group":
            item.setExpanded(not item.isExpanded())
            return
        if item_type != "product":
            return

        prod_id = item.data(0, ROLE_PRODUCT_ID)
        prod_name = item.data(0, ROLE_PRODUCT_NAME) or item.text(0)
        total_devices = int(item.data(0, ROLE_TOTAL_DEVICES) or 0)
        is_phone_unit = bool(item.data(0, ROLE_IS_PHONE_UNIT))
        primary_stock_item_id = item.data(0, ROLE_PRIMARY_STOCK_ITEM_ID)

        if is_phone_unit and primary_stock_item_id is not None:
            dlg = EditStockItemDialog(int(primary_stock_item_id), self)
            if dlg.exec():
                self._pending_select_product_id = prod_id
                self._pending_restore_focus = True
                self._load_data()
            else:
                self.tree.setFocus()
        elif total_devices > 0:
            dlg = StockItemDialog(product_id=prod_id, product_name=prod_name, parent=self)
            dlg.exec()
            self._pending_select_product_id = prod_id
            self._pending_restore_focus = True
            self._load_data()
        else:
            dlg = ProductDialog(self, product_id=prod_id)
            if dlg.exec():
                self._pending_select_product_id = prod_id
                self._pending_restore_focus = True
                self._load_data()
            else:
                self.tree.setFocus()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        self._activate_tree_item(item)

    def _on_item_activated(self) -> None:
        self._activate_tree_item(self.tree.currentItem())
