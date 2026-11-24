"""Единое окно глобального умного поиска (Ctrl+K) по товарам, IMEI, чекам, клиентам и поставщикам."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.stock_item import StockItem
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService
from app.ui import theme
from app.ui.purchase_page import PurchaseDetailsDialog
from app.ui.sales_page import SaleDetailsDialog
from app.ui.stock_page import StockItemDialog
from app.ui.widgets import configure_dialog_buttons, configure_table, make_button, money_str


class QuickSearchDialog(QDialog):
    """Универсальный поиск по всей базе данных (товары, частичный IMEI, покупатели, чеки, поставщики)."""

    def __init__(self, initial_query: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dükan boýunça çalt gözleg (Ctrl+K)")
        self.setMinimumSize(960, 540)
        self.setStyleSheet(theme.STYLE)

        self.results: list[dict] = []
        self.selected_for_pos: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        title = QLabel("Ählumumy çalt gözleg (Harytlar • IMEI • Müşderiler • Çekler • Üpjün edijiler)")
        title.setObjectName("cardTitle")
        root.addWidget(title)

        self.search_input = QLineEdit(initial_query)
        self.search_input.setPlaceholderText(
            "Harydyň ady, kategoriýa, brend, model, referens, ştrihkod, IMEI, müşderi, çek ýa-da üpjün ediji..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._run_search)
        root.addWidget(self.search_input)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Bölüm",
            "Haryt / Resminama",
            "Kategoriýa • Brend / Model",
            "Öz bahasy / Jemi",
            "Status / Galyndy",
        ])
        configure_table(self.table, stretch_col=[1, 2], row_height=42)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 145)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(4, 165)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._open_selected())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("Netijeler: 0")
        self.count_label.setObjectName("mutedText")
        footer.addWidget(self.count_label)
        footer.addStretch()

        pos_btn = make_button("🛒 Saýlanan harydy / IMEI-ni kassa goş")
        pos_btn.clicked.connect(self._send_to_pos)
        footer.addWidget(pos_btn)

        open_btn = make_button("Karty / resminamany aç", "primary")
        open_btn.clicked.connect(self._open_selected)
        footer.addWidget(open_btn)

        close_btn = make_button("Ýap")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        configure_dialog_buttons(self, open_btn, close_btn)
        self._run_search()
        self.search_input.setFocus()

    def _run_search(self, *_args) -> None:
        q = self.search_input.text().strip()
        words = [w for w in q.lower().split() if w]
        self.results = []

        default_curr = SettingsService.get("default_currency", "TMT")
        default_rate = SettingsService.get_default_exchange_rate()

        with SessionLocal() as session:
            # Предзагружаем последние in_stock StockItem для корректного расчёта себестоимости
            in_stock_rows = session.scalars(
                select(StockItem)
                .where(StockItem.status == "in_stock")
                .order_by(StockItem.id.desc())
            ).all()
            latest_stock_by_prod: dict[int, StockItem] = {}
            for st in in_stock_rows:
                if st.product_id not in latest_stock_by_prod and st.unit_cost is not None:
                    latest_stock_by_prod[st.product_id] = st

            prod_rows = session.execute(
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(Product.is_active.is_(True))
                .order_by(Product.name.asc())
            ).all()
            prod_count = 0
            for p, cat_name in prod_rows:
                cat_label = cat_name or "—"
                if words:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                p.name,
                                cat_name,
                                p.brand,
                                p.model,
                                p.specification,
                                p.barcode,
                            ],
                        )
                    ).lower()
                    if not all(w in hay for w in words):
                        continue
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=p.id,
                    stock_item=latest_stock_by_prod.get(p.id),
                    fallback_currency=default_curr,
                    fallback_rate=default_rate,
                )
                cost_txt = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"
                bm = " / ".join(filter(None, [p.brand, p.model])) or "—"
                detail_parts = [cat_label, bm]
                if p.specification:
                    detail_parts.append(p.specification)
                if p.barcode:
                    detail_parts.append(f"Ştrihkod: {p.barcode}")
                self.results.append({
                    "kind": "product",
                    "type_label": "Haryt",
                    "title": p.name,
                    "details": "  •  ".join(detail_parts),
                    "cost_or_total": cost_txt,
                    "status": f"Skladda: {p.stock_quantity} sany",
                    "color": theme.GREEN if p.stock_quantity > 0 else theme.RED,
                    "product_id": p.id,
                    "product_name": p.name,
                    "imei": None,
                    "can_pos": p.stock_quantity > 0,
                })
                prod_count += 1
                if prod_count >= 15:
                    break

            imei_rows = session.execute(
                select(StockItem, Product, Category.name)
                .join(Product, StockItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .order_by(StockItem.id.desc())
            ).all()
            imei_count = 0
            for st, prod, cat_name in imei_rows:
                cat_label = cat_name or "—"
                if words:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                prod.name,
                                cat_name,
                                prod.brand,
                                prod.model,
                                prod.specification,
                                prod.barcode,
                                st.imei1,
                                st.imei2,
                                st.serial_number,
                            ],
                        )
                    ).lower()
                    if not all(w in hay for w in words):
                        continue
                in_stock = st.status == "in_stock"
                cond = "Täze" if st.condition == "new" else "B/U"
                bm = " / ".join(filter(None, [prod.brand, prod.model])) or "—"
                u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=prod.id,
                    stock_item=st,
                    fallback_currency=default_curr,
                    fallback_rate=default_rate,
                )
                cost_txt = f"{money_str(u_cost)} {c_curr}" if u_cost > 0 else "—"
                imei_part = f"IMEI: {st.imei1}" + (f" / {st.imei2}" if st.imei2 else "")
                self.results.append({
                    "kind": "imei",
                    "type_label": f"IMEI ({cond})",
                    "title": prod.name,
                    "details": f"{cat_label}  •  {bm}  •  {imei_part}",
                    "cost_or_total": cost_txt,
                    "status": "Bar" if in_stock else "Satyldy",
                    "color": theme.BLUE if in_stock else theme.MUTED,
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "imei": st.imei1,
                    "can_pos": in_stock and prod.stock_quantity > 0,
                })
                imei_count += 1
                if imei_count >= 15:
                    break

            sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc())).all()
            sale_count = 0
            for s in sales:
                if words:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                s.receipt_number,
                                s.customer_name,
                                s.customer_phone,
                                s.comment,
                            ],
                        )
                    ).lower()
                    if not all(w in hay for w in words):
                        continue
                cust = s.customer_name or "Bölek müşderi"
                if s.customer_phone:
                    cust += f" ({s.customer_phone})"
                self.results.append({
                    "kind": "sale",
                    "type_label": "Satyş / Çek",
                    "title": f"Çek {s.receipt_number}",
                    "details": f"Müşderi: {cust}  •  {s.sale_date:%d.%m.%Y %H:%M}",
                    "cost_or_total": f"{money_str(s.total_amount)} {s.currency}",
                    "status": "Ýatyryldy" if s.status == "cancelled" else "Aktiw",
                    "color": theme.RED if s.status == "cancelled" else theme.ACCENT,
                    "sale_id": s.id,
                    "can_pos": False,
                })
                sale_count += 1
                if sale_count >= 15:
                    break

            purchases = session.scalars(select(Purchase).order_by(Purchase.purchase_date.desc())).all()
            pur_count = 0
            for pur in purchases:
                if words:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                f"alyş {pur.id}",
                                pur.supplier_name,
                                pur.note,
                            ],
                        )
                    ).lower()
                    if not all(w in hay for w in words):
                        continue
                self.results.append({
                    "kind": "purchase",
                    "type_label": "Alyş",
                    "title": f"Alyş №{pur.id}",
                    "details": f"Üpjün ediji: {pur.supplier_name or '—'}  •  {pur.purchase_date:%d.%m.%Y %H:%M}",
                    "cost_or_total": f"{money_str(pur.total_amount)} {pur.currency}",
                    "status": "Ýatyryldy" if pur.status == "cancelled" else "Aktiw",
                    "color": theme.RED if pur.status == "cancelled" else theme.TEAL,
                    "purchase_id": pur.id,
                    "can_pos": False,
                })
                pur_count += 1
                if pur_count >= 10:
                    break

        self.table.setRowCount(len(self.results))
        self.count_label.setText(f"Tapylan netijeler: {len(self.results)}")
        for r, item in enumerate(self.results):
            vals = [
                item["type_label"],
                item["title"],
                item["details"],
                item["cost_or_total"],
                item["status"],
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 3, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    cell.setForeground(QColor(item["color"]))
                self.table.setItem(r, c, cell)
        if self.results:
            self.table.selectRow(0)

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.results)):
            return
        item = self.results[row]
        kind = item["kind"]
        if kind in ("product", "imei"):
            dlg = StockItemDialog(
                product_id=item["product_id"],
                product_name=item["product_name"],
                parent=self,
            )
            dlg.exec()
            self._run_search()
        elif kind == "sale":
            dlg = SaleDetailsDialog(item["sale_id"], self)
            dlg.exec()
            self._run_search()
        elif kind == "purchase":
            dlg = PurchaseDetailsDialog(item["purchase_id"], self)
            dlg.exec()
            self._run_search()

    def _send_to_pos(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.results)):
            return
        item = self.results[row]
        if not item.get("can_pos"):
            self._open_selected()
            return
        self.selected_for_pos = item
        self.accept()
