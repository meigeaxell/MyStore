"""Единое окно глобального умного поиска (Ctrl+K) по товарам, IMEI, чекам, клиентам и поставщикам."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.stock_item import StockItem
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
        self.setMinimumSize(820, 520)
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
            "Harydyň adyny, brend, SKU, IMEI soňky sanlaryny, müşderini, telefony, çeki ýa-da üpjün edijini giriziň..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self._run_search)
        root.addWidget(self.search_input)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "Bölüm",
            "Obýekt / Resminama",
            "Jikme-jik / Belgi",
            "Status / Galyndy / Jemi",
        ])
        configure_table(self.table, stretch_col=[1, 2], row_height=42)
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
        self.results = []

        with SessionLocal() as session:
            prod_stmt = select(Product).where(Product.is_active.is_(True))
            if q:
                prod_stmt = prod_stmt.where(
                    (Product.name.ilike(f"%{q}%"))
                    | (Product.sku.ilike(f"%{q}%"))
                    | (Product.barcode.ilike(f"%{q}%"))
                    | (Product.brand.ilike(f"%{q}%"))
                    | (Product.model.ilike(f"%{q}%"))
                )
            for p in session.scalars(prod_stmt.order_by(Product.name).limit(15)).all():
                bc_part = f"  •  Ştrihkod: {p.barcode}" if p.barcode else ""
                self.results.append({
                    "kind": "product",
                    "type_label": "Haryt",
                    "title": p.name,
                    "details": f"SKU: {p.sku}{bc_part}  •  {' / '.join(filter(None, [p.brand, p.model])) or '—'}",
                    "status": f"Skladda: {p.stock_quantity} sany",
                    "color": theme.GREEN if p.stock_quantity > 0 else theme.RED,
                    "product_id": p.id,
                    "product_name": p.name,
                    "imei": None,
                    "can_pos": p.stock_quantity > 0,
                })

            imei_stmt = (
                select(StockItem, Product)
                .join(Product, StockItem.product_id == Product.id)
            )
            if q:
                imei_stmt = imei_stmt.where(
                    (StockItem.imei1.ilike(f"%{q}%"))
                    | (StockItem.imei2.ilike(f"%{q}%"))
                    | (StockItem.serial_number.ilike(f"%{q}%"))
                    | (Product.name.ilike(f"%{q}%"))
                )
            for st, prod in session.execute(imei_stmt.order_by(StockItem.id.desc()).limit(15)).all():
                in_stock = st.status == "in_stock"
                cond = "Täze" if st.condition == "new" else "B/U"
                self.results.append({
                    "kind": "imei",
                    "type_label": f"IMEI ({cond})",
                    "title": prod.name,
                    "details": f"IMEI: {st.imei1}" + (f" / {st.imei2}" if st.imei2 else ""),
                    "status": "Bar" if in_stock else "Satyldy",
                    "color": theme.BLUE if in_stock else theme.MUTED,
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "imei": st.imei1,
                    "can_pos": in_stock and prod.stock_quantity > 0,
                })

            sale_stmt = select(Sale)
            if q:
                sale_stmt = sale_stmt.where(
                    (Sale.receipt_number.ilike(f"%{q}%"))
                    | (Sale.customer_name.ilike(f"%{q}%"))
                    | (Sale.customer_phone.ilike(f"%{q}%"))
                    | (Sale.comment.ilike(f"%{q}%"))
                )
            for s in session.scalars(sale_stmt.order_by(Sale.sale_date.desc()).limit(15)).all():
                cust = s.customer_name or "Bölek müşderi"
                if s.customer_phone:
                    cust += f" ({s.customer_phone})"
                self.results.append({
                    "kind": "sale",
                    "type_label": "Satyş / Çek",
                    "title": f"Çek {s.receipt_number}",
                    "details": f"Müşderi: {cust}  •  {s.sale_date:%d.%m.%Y %H:%M}",
                    "status": f"{money_str(s.total_amount)} {s.currency}",
                    "color": theme.RED if s.status == "cancelled" else theme.ACCENT,
                    "sale_id": s.id,
                    "can_pos": False,
                })

            pur_stmt = select(Purchase)
            if q:
                pur_stmt = pur_stmt.where(
                    (Purchase.supplier_name.ilike(f"%{q}%"))
                    | (Purchase.note.ilike(f"%{q}%"))
                )
            for pur in session.scalars(pur_stmt.order_by(Purchase.purchase_date.desc()).limit(10)).all():
                self.results.append({
                    "kind": "purchase",
                    "type_label": "Alyş",
                    "title": f"Alyş №{pur.id}",
                    "details": f"Üpjün ediji: {pur.supplier_name or '—'}  •  {pur.purchase_date:%d.%m.%Y %H:%M}",
                    "status": f"{money_str(pur.total_amount)} {pur.currency}",
                    "color": theme.TEAL,
                    "purchase_id": pur.id,
                    "can_pos": False,
                })

        self.table.setRowCount(len(self.results))
        self.count_label.setText(f"Tapylan netijeler: {len(self.results)}")
        for r, item in enumerate(self.results):
            vals = [
                item["type_label"],
                item["title"],
                item["details"],
                item["status"],
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (0, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
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
