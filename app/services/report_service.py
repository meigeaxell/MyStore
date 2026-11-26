from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.device_exchange import DeviceExchange
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.stock_item import StockItem
from app.services.cash_service import _decimal, _money, _validate_rate
from app.services.purchase_service import (
    PERSONAL_SOURCE_LABEL,
    _get_supplier_debt_amount,
    is_personal_source_purchase,
)
from app.services.purchase_service import (
    _get_paid_amount as _get_purchase_paid_amount,
)
from app.services.sales_service import SalesService, _convert_currency


class ReportService:
    """Сервис аналитики, отчетности (Фаза III) и прослеживаемости истории товаров/IMEI (Фаза V)."""

    @staticmethod
    def resolve_date_range(
        preset: str,
        custom_from: date | None = None,
        custom_to: date | None = None,
    ) -> tuple[datetime | None, datetime | None]:
        """Преобразует пресет периода в (date_from, date_to)."""
        today = date.today()
        if preset == "today":
            d1, d2 = today, today
        elif preset == "yesterday":
            y = today - timedelta(days=1)
            d1, d2 = y, y
        elif preset == "current_week":
            d1 = today - timedelta(days=today.weekday())
            d2 = today
        elif preset == "current_month":
            d1 = today.replace(day=1)
            d2 = today
        elif preset == "previous_month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            d1 = last_prev.replace(day=1)
            d2 = last_prev
        elif preset == "custom":
            d1 = custom_from or today
            d2 = custom_to or today
        else:
            # all_time
            return None, None

        return datetime.combine(d1, time.min), datetime.combine(d2, time.max)

    @staticmethod
    def get_sales_report(
        session: Session,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        currency_filter: str | None = None,
    ) -> dict:
        """Отчет по продажам (Раздел 7.2). Отмененные чеки учитываются строго отдельно."""
        stmt = select(Sale).order_by(Sale.sale_date.desc())
        if date_from is not None:
            stmt = stmt.where(Sale.sale_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Sale.sale_date <= date_to)
        if currency_filter and currency_filter in ("USD", "TMT"):
            stmt = stmt.where(Sale.currency == currency_filter)

        sales = session.scalars(stmt).all()

        active_count = 0
        cancelled_count = 0
        units_sold = 0

        summary = {
            "USD": {
                "revenue": Decimal("0.00"),
                "paid": Decimal("0.00"),
                "customer_debt": Decimal("0.00"),
                "cancelled_value": Decimal("0.00"),
            },
            "TMT": {
                "revenue": Decimal("0.00"),
                "paid": Decimal("0.00"),
                "customer_debt": Decimal("0.00"),
                "cancelled_value": Decimal("0.00"),
            },
        }

        rows = []
        sale_ids = [s.id for s in sales]
        items_by_sale: dict[int, list[str]] = {}
        units_by_sale: dict[int, int] = {}
        if sale_ids:
            si_rows = session.execute(
                select(SaleItem, Product, Category.name)
                .join(Product, SaleItem.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(SaleItem.sale_id.in_(sale_ids))
                .order_by(SaleItem.id.asc())
            ).all()
            for si, prod, cat_name in si_rows:
                units_by_sale[si.sale_id] = units_by_sale.get(si.sale_id, 0) + int(si.quantity or 0)
                bm = " / ".join(filter(None, [(prod.brand or "").strip(), (prod.model or "").strip()]))
                if not bm and getattr(prod, "is_phone_unit", False) and prod.specification:
                    bm = prod.specification.strip()
                meta_parts = [p for p in (cat_name or "", bm) if p]
                meta = f" ({' • '.join(meta_parts)})" if meta_parts else ""
                qty_part = f" ×{si.quantity}" if int(si.quantity or 1) > 1 else ""
                items_by_sale.setdefault(si.sale_id, []).append(f"{prod.name}{meta}{qty_part}")

        for sale in sales:
            cur = sale.currency.strip().upper()
            if cur not in summary:
                continue

            total = _money(_decimal(sale.total_amount))
            paid = SalesService.get_sale_paid_amount(session, sale)
            sale_units = units_by_sale.get(sale.id, 0)

            if sale.status == "cancelled":
                cancelled_count += 1
                summary[cur]["cancelled_value"] = _money(
                    summary[cur]["cancelled_value"] + total
                )
                cust_debt = Decimal("0.00")
            else:
                active_count += 1
                units_sold += sale_units
                cust_debt = SalesService.get_customer_debt(session, sale)
                summary[cur]["revenue"] = _money(summary[cur]["revenue"] + total)
                summary[cur]["paid"] = _money(summary[cur]["paid"] + paid)
                summary[cur]["customer_debt"] = _money(
                    summary[cur]["customer_debt"] + cust_debt
                )

            item_list = items_by_sale.get(sale.id, [])
            if len(item_list) > 2:
                items_summary = f"{', '.join(item_list[:2])} (+{len(item_list) - 2})"
            else:
                items_summary = ", ".join(item_list) if item_list else "—"

            rows.append({
                "sale_id": sale.id,
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "customer_name": sale.customer_name or "Bölek müşderi",
                "items_summary": items_summary,
                "currency": cur,
                "exchange_rate": _validate_rate(sale.exchange_rate or Decimal("1.0000")),
                "units": sale_units,
                "total_amount": total,
                "paid_amount": paid,
                "customer_debt": cust_debt,
                "status": sale.status,
                "status_label": "Ýatyryldy" if sale.status == "cancelled" else "Işjeň",
            })

        return {
            "active_receipts_count": active_count,
            "cancelled_receipts_count": cancelled_count,
            "units_sold": units_sold,
            "by_currency": summary,
            "rows": rows,
        }

    @staticmethod
    def get_profit_report(
        session: Session,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        currency_filter: str | None = None,
    ) -> dict:
        """Отчет по прибыли (Раздел 7.3).

        Использует историческую себестоимость (unit_cost, cost_currency, cost_exchange_rate),
        записанную в SaleItem на момент продажи.
        Отмененные продажи исключены из активной прибыли.
        Обмены (DeviceExchange) учитываются корректно без двойного счета.
        Выручка, себестоимость, валовая прибыль и фактически полученные деньги разделены.
        """
        stmt = (
            select(SaleItem, Sale, Product, Category.name)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Sale.status != "cancelled")
            .order_by(Sale.sale_date.desc(), SaleItem.id.asc())
        )
        if date_from is not None:
            stmt = stmt.where(Sale.sale_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Sale.sale_date <= date_to)
        if currency_filter and currency_filter in ("USD", "TMT"):
            stmt = stmt.where(Sale.currency == currency_filter)

        item_rows = session.execute(stmt).all()

        # Карта обменов по original_sale_item_id для предотвращения двойного счета
        exchanges = session.scalars(select(DeviceExchange)).all()
        exchange_by_item_id = {
            ex.original_sale_item_id: ex
            for ex in exchanges
            if ex.original_sale_item_id is not None
        }

        totals = {
            "USD": {
                "revenue": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "cash_received": Decimal("0.00"),
            },
            "TMT": {
                "revenue": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "cash_received": Decimal("0.00"),
            },
        }

        seen_sales: set[int] = set()
        lines = []

        for s_item, sale, product, cat_name in item_rows:
            doc_cur = sale.currency.strip().upper()
            if doc_cur not in totals:
                continue

            sale_rate = _validate_rate(sale.exchange_rate or Decimal("1.0000"))

            if sale.id not in seen_sales:
                seen_sales.add(sale.id)
                paid = SalesService.get_sale_paid_amount(session, sale)
                totals[doc_cur]["cash_received"] = _money(
                    totals[doc_cur]["cash_received"] + paid
                )

            ex = exchange_by_item_id.get(s_item.id)
            eff_cat = cat_name or "—"
            eff_brand = (product.brand or "").strip()
            eff_model = (product.model or "").strip()
            if ex is not None:
                # Если позиция была обменяна, итоговой экономической реализацией является новое устройство
                new_prod = session.get(Product, ex.new_product_id)
                if new_prod:
                    new_cat = session.get(Category, new_prod.category_id)
                    eff_cat = new_cat.name if new_cat else eff_cat
                    eff_brand = (new_prod.brand or "").strip()
                    eff_model = (new_prod.model or "").strip()
                prod_name = (
                    f"{new_prod.name} (Çalyşyk {ex.exchange_number} ← {product.name})"
                    if new_prod
                    else product.name
                )
                imei_str = ex.new_imei or s_item.imei or "—"
                qty = 1
                ex_rate = _validate_rate(ex.exchange_rate or sale_rate)
                selling_price_doc = _convert_currency(
                    _decimal(ex.new_price),
                    ex.currency,
                    doc_cur,
                    ex_rate,
                )
                cost_rate = _validate_rate(ex.new_cost_exchange_rate or ex_rate)
                cogs_doc = _convert_currency(
                    _decimal(ex.new_unit_cost),
                    ex.new_cost_currency,
                    doc_cur,
                    cost_rate,
                )
            else:
                prod_name = product.name
                imei_str = s_item.imei or "—"
                qty = s_item.quantity
                line_rev_item_cur = _money(
                    (_decimal(s_item.unit_price) * qty) - _decimal(s_item.discount)
                )
                selling_price_doc = _convert_currency(
                    line_rev_item_cur,
                    s_item.currency,
                    doc_cur,
                    sale_rate,
                )
                cost_rate = _validate_rate(s_item.cost_exchange_rate or sale_rate)
                unit_cost_doc = _convert_currency(
                    _decimal(s_item.unit_cost),
                    s_item.cost_currency,
                    doc_cur,
                    cost_rate,
                )
                cogs_doc = _money(unit_cost_doc * qty)

            profit_doc = _money(selling_price_doc - cogs_doc)
            margin_pct = (
                _money((profit_doc / selling_price_doc) * Decimal(100))
                if selling_price_doc > Decimal("0.00")
                else Decimal("0.00")
            )

            totals[doc_cur]["revenue"] = _money(
                totals[doc_cur]["revenue"] + selling_price_doc
            )
            totals[doc_cur]["cogs"] = _money(totals[doc_cur]["cogs"] + cogs_doc)
            totals[doc_cur]["gross_profit"] = _money(
                totals[doc_cur]["gross_profit"] + profit_doc
            )

            bm = " / ".join(filter(None, [eff_brand, eff_model]))
            detail_parts = [p for p in (eff_cat, bm) if p and p != "—"]
            product_display = f"{prod_name} ({' • '.join(detail_parts)})" if detail_parts else prod_name

            lines.append({
                "sale_id": sale.id,
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "product_name": prod_name,
                "product_display": product_display,
                "category": eff_cat,
                "brand": eff_brand,
                "model": eff_model,
                "imei": imei_str,
                "quantity": qty,
                "currency": doc_cur,
                "selling_price": selling_price_doc,
                "cogs": cogs_doc,
                "gross_profit": profit_doc,
                "margin_pct": margin_pct,
                "is_exchanged": ex is not None,
            })

        return {
            "by_currency": totals,
            "rows": lines,
        }

    @staticmethod
    def get_product_report(
        session: Session,
        category_id: int | None = None,
        search_query: str = "",
    ) -> list[dict]:
        """Отчет по товарам (Раздел 7.4).

        Показывает текущий остаток, купленное и проданное количество, выручку, себестоимость,
        прибыль (отдельно по USD и TMT) и дату последней продажи.
        """
        stmt = (
            select(Product, Category.name)
            .join(Category, Product.category_id == Category.id)
            .order_by(Product.name.asc())
        )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)

        products = session.execute(stmt).all()
        q = (search_query or "").strip().lower()

        # Закупки по товарам (только активные)
        p_items = session.execute(
            select(PurchaseItem, Purchase)
            .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
            .where(Purchase.status == "active")
        ).all()
        purchased_qty_map: dict[int, int] = {}
        for pi, _pur in p_items:
            purchased_qty_map[pi.product_id] = (
                purchased_qty_map.get(pi.product_id, 0) + pi.quantity
            )

        # Продажи по товарам (только активные)
        s_items = session.execute(
            select(SaleItem, Sale)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.status != "cancelled")
        ).all()

        sold_qty_map: dict[int, int] = {}
        last_sale_map: dict[int, datetime] = {}
        fin_map: dict[int, dict] = {}

        for si, sale in s_items:
            pid = si.product_id
            sold_qty_map[pid] = sold_qty_map.get(pid, 0) + si.quantity
            if pid not in last_sale_map or sale.sale_date > last_sale_map[pid]:
                last_sale_map[pid] = sale.sale_date

            if pid not in fin_map:
                fin_map[pid] = {
                    "USD": {"rev": Decimal("0.00"), "cogs": Decimal("0.00"), "profit": Decimal("0.00")},
                    "TMT": {"rev": Decimal("0.00"), "cogs": Decimal("0.00"), "profit": Decimal("0.00")},
                }

            cur = sale.currency.strip().upper()
            if cur not in ("USD", "TMT"):
                continue
            rate = _validate_rate(sale.exchange_rate or Decimal("1.0000"))
            rev = _convert_currency(
                _money((_decimal(si.unit_price) * si.quantity) - _decimal(si.discount)),
                si.currency,
                cur,
                rate,
            )
            c_rate = _validate_rate(si.cost_exchange_rate or rate)
            cogs = _money(
                _convert_currency(_decimal(si.unit_cost), si.cost_currency, cur, c_rate)
                * si.quantity
            )
            prof = _money(rev - cogs)

            fin_map[pid][cur]["rev"] = _money(fin_map[pid][cur]["rev"] + rev)
            fin_map[pid][cur]["cogs"] = _money(fin_map[pid][cur]["cogs"] + cogs)
            fin_map[pid][cur]["profit"] = _money(fin_map[pid][cur]["profit"] + prof)

        rows = []
        for product, cat_name in products:
            if q:
                hay = f"{product.name} {product.sku} {cat_name} {product.brand or ''}".lower()
                if q not in hay:
                    continue

            f = fin_map.get(
                product.id,
                {
                    "USD": {"rev": Decimal("0.00"), "cogs": Decimal("0.00"), "profit": Decimal("0.00")},
                    "TMT": {"rev": Decimal("0.00"), "cogs": Decimal("0.00"), "profit": Decimal("0.00")},
                },
            )

            rows.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "category": cat_name,
                "current_stock": product.stock_quantity,
                "quantity_purchased": purchased_qty_map.get(product.id, 0),
                "quantity_sold": sold_qty_map.get(product.id, 0),
                "revenue_usd": f["USD"]["rev"],
                "cogs_usd": f["USD"]["cogs"],
                "profit_usd": f["USD"]["profit"],
                "revenue_tmt": f["TMT"]["rev"],
                "cogs_tmt": f["TMT"]["cogs"],
                "profit_tmt": f["TMT"]["profit"],
                "last_sale_date": last_sale_map.get(product.id),
            })

        return rows

    @staticmethod
    def get_product_history(session: Session, product_id: int) -> list[dict]:
        """Возвращает полную историю движений товара (Фаза V — Product History):
        поступления, продажи, отмены закупок, отмены продаж, возвраты и выдачи по обмену.
        """
        events = []

        # 1. Закупки и отмены закупок
        p_rows = session.execute(
            select(PurchaseItem, Purchase)
            .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
            .where(PurchaseItem.product_id == product_id)
        ).all()
        for pi, pur in p_rows:
            events.append({
                "date": pur.purchase_date,
                "event_type": "Giriş (Alyş)",
                "quantity_change": f"+{pi.quantity}",
                "document": f"Alyş №{pur.id}",
                "price_info": f"{_money(_decimal(pi.unit_cost))} {pur.currency}",
                "details": f"Üpjün ediji: {pur.supplier_name or '—'}",
            })
            if pur.status == "cancelled":
                events.append({
                    "date": pur.cancelled_at or pur.purchase_date,
                    "event_type": "Alyş ýatyryldy (Hasapdan çykaryldy)",
                    "quantity_change": f"−{pi.quantity}",
                    "document": f"Alyş №{pur.id}",
                    "price_info": f"{_money(_decimal(pi.unit_cost))} {pur.currency}",
                    "details": f"Sebäbi: {pur.cancellation_reason or '—'}",
                })

        s_rows = session.execute(
            select(SaleItem, Sale)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(SaleItem.product_id == product_id)
        ).all()
        for si, sale in s_rows:
            imei_info = f"IMEI: {si.imei}" if si.imei else "IMEI-siz"
            events.append({
                "date": sale.sale_date,
                "event_type": "Satyş",
                "quantity_change": f"−{si.quantity}",
                "document": f"Çek {sale.receipt_number}",
                "price_info": f"{_money(_decimal(si.unit_price))} {si.currency}",
                "details": f"{imei_info} • Müşderi: {sale.customer_name or 'Bölek'}",
            })
            if sale.status == "cancelled":
                events.append({
                    "date": sale.cancelled_at or sale.sale_date,
                    "event_type": "Satyş ýatyryldy (Sklada gaýtaryldy)",
                    "quantity_change": f"+{si.quantity}",
                    "document": f"Çek {sale.receipt_number}",
                    "price_info": f"{_money(_decimal(si.unit_price))} {si.currency}",
                    "details": f"Sebäbi: {sale.cancellation_reason or '—'}",
                })

        old_ex = session.scalars(
            select(DeviceExchange).where(DeviceExchange.old_product_id == product_id)
        ).all()
        for ex in old_ex:
            events.append({
                "date": ex.exchange_date,
                "event_type": "Çalyşykda kabul edildi (Trade-in)",
                "quantity_change": "+1",
                "document": f"Çalyşyk {ex.exchange_number}",
                "price_info": f"{_money(_decimal(ex.old_price))} {ex.currency}",
                "details": f"IMEI: {ex.old_imei or '—'} • Sebäbi: {ex.reason}",
            })

        new_ex = session.scalars(
            select(DeviceExchange).where(DeviceExchange.new_product_id == product_id)
        ).all()
        for ex in new_ex:
            events.append({
                "date": ex.exchange_date,
                "event_type": "Çalyşykda berildi (Trade-in)",
                "quantity_change": "−1",
                "document": f"Çalyşyk {ex.exchange_number}",
                "price_info": f"{_money(_decimal(ex.new_price))} {ex.currency}",
                "details": f"IMEI: {ex.new_imei or '—'} • Sebäbi: {ex.reason}",
            })

        events.sort(key=lambda e: e["date"] or datetime.min, reverse=True)
        return events

    @staticmethod
    def get_device_report(
        session: Session,
        search_query: str = "",
        status_filter: str | None = None,
    ) -> list[dict]:
        """Отчет по устройствам с IMEI (Раздел 7.5):
        полная прослеживаемость от закупки до продажи или обмена.
        """
        stmt = (
            select(StockItem, Product)
            .join(Product, StockItem.product_id == Product.id)
            .order_by(StockItem.id.desc())
        )
        if status_filter and status_filter in ("in_stock", "sold"):
            stmt = stmt.where(StockItem.status == status_filter)

        stock_rows = session.execute(stmt).all()
        q = (search_query or "").strip().lower()

        results = []
        for st, product in stock_rows:
            if q:
                hay = f"{st.imei1} {st.imei2 or ''} {st.serial_number or ''} {product.name} {product.sku}".lower()
                if q not in hay:
                    continue

            purchase = session.get(Purchase, st.purchase_id) if st.purchase_id else None
            purchase_date = purchase.purchase_date if purchase else st.created_at
            supplier_name = (
                (purchase.supplier_name or f"Alyş №{purchase.id}")
                if purchase
                else "Galyndy girizmek"
            )
            cost_amt = _money(_decimal(st.unit_cost or 0))
            cost_cur = (st.cost_currency or (purchase.currency if purchase else "USD")).strip().upper()

            # Ищем последнюю активную продажу этого IMEI
            active_sale_row = session.execute(
                select(SaleItem, Sale)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .where(
                    Sale.status != "cancelled",
                    (SaleItem.stock_item_id == st.id)
                    | (SaleItem.imei == st.imei1)
                    | ((SaleItem.imei == st.imei2) if st.imei2 else False),
                )
                .order_by(Sale.sale_date.desc())
            ).first()

            # Также проверим, не было ли устройство выдано как замена в DeviceExchange
            issued_exchange = session.scalar(
                select(DeviceExchange)
                .where(
                    (DeviceExchange.new_stock_item_id == st.id)
                    | (DeviceExchange.new_imei == st.imei1)
                )
                .order_by(DeviceExchange.exchange_date.desc())
            )

            sale_date = None
            selling_price = None
            sale_currency = None
            profit = None
            sale_doc_label = "—"

            if issued_exchange is not None and (
                active_sale_row is None
                or issued_exchange.exchange_date >= active_sale_row[1].sale_date
            ):
                sale_date = issued_exchange.exchange_date
                selling_price = _money(_decimal(issued_exchange.new_price))
                sale_currency = issued_exchange.currency
                ex_rate = _validate_rate(issued_exchange.exchange_rate)
                cost_in_sale_cur = _convert_currency(cost_amt, cost_cur, sale_currency, ex_rate)
                profit = _money(selling_price - cost_in_sale_cur)
                sale_doc_label = f"Çalyşyk {issued_exchange.exchange_number}"
            elif active_sale_row is not None:
                si, sale = active_sale_row
                sale_date = sale.sale_date
                selling_price = _money(_decimal(si.unit_price) - _decimal(si.discount))
                sale_currency = si.currency
                s_rate = _validate_rate(sale.exchange_rate or Decimal("1.0000"))
                cost_in_sale_cur = _convert_currency(cost_amt, cost_cur, sale_currency, s_rate)
                profit = _money(selling_price - cost_in_sale_cur)
                sale_doc_label = f"Çek {sale.receipt_number}"

            results.append({
                "stock_item_id": st.id,
                "imei1": st.imei1,
                "imei2": st.imei2 or "",
                "serial_number": st.serial_number or "",
                "product_id": product.id,
                "model_name": product.name,
                "sku": product.sku,
                "condition": st.condition,
                "purchase_date": purchase_date,
                "purchase_cost": cost_amt,
                "cost_currency": cost_cur,
                "supplier": supplier_name,
                "sale_date": sale_date,
                "selling_price": selling_price,
                "sale_currency": sale_currency,
                "profit": profit,
                "sale_doc_label": sale_doc_label,
                "status": st.status,
                "status_label": "Skladda bar" if st.status == "in_stock" else "Satyldy",
            })

        return results

    @staticmethod
    def get_imei_history(session: Session, stock_item_id: int) -> list[dict]:
        """Возвращает непрерывную историю конкретного IMEI от поступления до всех продаж, отмен и обменов (Фаза V)."""
        st = session.get(StockItem, stock_item_id)
        if st is None:
            return []

        events = []

        if st.purchase_id:
            pur = session.get(Purchase, st.purchase_id)
            if pur:
                events.append({
                    "date": pur.purchase_date,
                    "event": "Alyş boýunça giriş",
                    "document": f"Alyş №{pur.id}",
                    "amount": f"{_money(_decimal(st.unit_cost or 0))} {st.cost_currency or pur.currency}",
                    "details": f"Üpjün ediji: {pur.supplier_name or '—'}",
                })
        else:
            events.append({
                "date": st.created_at,
                "event": "Enjamy sklada hasaba almak",
                "document": f"Sklad #{st.id}",
                "amount": (
                    f"{_money(_decimal(st.unit_cost))} {st.cost_currency or ''}".strip()
                    if st.unit_cost is not None
                    else "—"
                ),
                "details": f"Ýagdaýy: {'Täze' if st.condition == 'new' else 'B/U'}",
            })

        sale_rows = session.execute(
            select(SaleItem, Sale)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(
                (SaleItem.stock_item_id == st.id)
                | (SaleItem.imei == st.imei1)
                | ((SaleItem.imei == st.imei2) if st.imei2 else False)
            )
        ).all()

        for si, sale in sale_rows:
            events.append({
                "date": sale.sale_date,
                "event": "Müşderä satyş",
                "document": f"Çek {sale.receipt_number}",
                "amount": f"{_money(_decimal(si.unit_price) - _decimal(si.discount))} {si.currency}",
                "details": f"Müşderi: {sale.customer_name or 'Bölek müşderi'}",
            })
            if sale.status == "cancelled":
                events.append({
                    "date": sale.cancelled_at or sale.sale_date,
                    "event": "Sklada gaýtaryldy (Çek ýatyryldy)",
                    "document": f"Çek {sale.receipt_number}",
                    "amount": f"{_money(_decimal(si.unit_price))} {si.currency}",
                    "details": f"Ýatyrma sebäbi: {sale.cancellation_reason or '—'}",
                })

        returned_ex = session.scalars(
            select(DeviceExchange).where(
                (DeviceExchange.old_stock_item_id == st.id)
                | (DeviceExchange.old_imei == st.imei1)
            )
        ).all()
        for ex in returned_ex:
            events.append({
                "date": ex.exchange_date,
                "event": "Çalyşykda sklada kabul edildi (Trade-in)",
                "document": f"Çalyşyk {ex.exchange_number}",
                "amount": f"{_money(_decimal(ex.old_price))} {ex.currency}",
                "details": f"IMEI {ex.new_imei or '—'} bilen çalşyldy • Sebäbi: {ex.reason}",
            })

        issued_ex = session.scalars(
            select(DeviceExchange).where(
                (DeviceExchange.new_stock_item_id == st.id)
                | (DeviceExchange.new_imei == st.imei1)
            )
        ).all()
        for ex in issued_ex:
            events.append({
                "date": ex.exchange_date,
                "event": "Çalyşykda müşderä berildi (Trade-in)",
                "document": f"Çalyşyk {ex.exchange_number}",
                "amount": f"{_money(_decimal(ex.new_price))} {ex.currency}",
                "details": f"Köne IMEI {ex.old_imei or '—'} ýerine • Goşmaça töleg: {_money(_decimal(ex.price_difference))} {ex.currency}",
            })

        events.sort(key=lambda e: e["date"] or datetime.min)
        return events

    @staticmethod
    def get_inventory_report(session: Session) -> dict:
        """Складской отчет (Раздел 7.6):
        остатки по категориям, по моделям, количество IMEI-устройств vs аксессуаров,
        товары с низким остатком и товары вне наличия.
        """
        rows = session.execute(
            select(Product, Category.name)
            .join(Category, Product.category_id == Category.id)
            .where(Product.is_active.is_(True))
            .order_by(Category.name.asc(), Product.name.asc())
        ).all()

        in_stock_imeis = session.scalars(
            select(StockItem).where(StockItem.status == "in_stock")
        ).all()
        imei_count_by_product: dict[int, int] = {}
        for st in in_stock_imeis:
            imei_count_by_product[st.product_id] = (
                imei_count_by_product.get(st.product_id, 0) + 1
            )

        total_units = 0
        total_devices = len(in_stock_imeis)
        total_accessories = 0
        low_stock_count = 0
        out_of_stock_count = 0

        by_category: dict[str, int] = {}
        product_rows = []

        for product, cat_name in rows:
            qty = product.stock_quantity
            dev_cnt = imei_count_by_product.get(product.id, 0)
            acc_cnt = max(0, qty - dev_cnt)

            total_units += qty
            total_accessories += acc_cnt
            by_category[cat_name] = by_category.get(cat_name, 0) + qty

            if qty == 0:
                out_of_stock_count += 1
                state = "Skladda ýok"
            elif product.min_stock_quantity > 0 and qty <= product.min_stock_quantity:
                low_stock_count += 1
                state = "Az galyndy"
            else:
                state = "Bar"

            product_rows.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "category": cat_name,
                "brand": product.brand or "—",
                "model": product.model or "—",
                "stock_quantity": qty,
                "imei_devices": dev_cnt,
                "quantitative_units": acc_cnt,
                "min_stock_quantity": product.min_stock_quantity,
                "state": state,
            })

        return {
            "total_units": total_units,
            "total_devices": total_devices,
            "total_accessories": total_accessories,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "by_category": by_category,
            "rows": product_rows,
        }

    @staticmethod
    def get_supplier_report(session: Session, search_query: str = "") -> list[dict]:
        """Отчет по поставщикам (Раздел 7.7)."""
        purchases = session.scalars(
            select(Purchase).order_by(Purchase.purchase_date.desc())
        ).all()

        # Подсчет поставленных единиц/устройств по закупкам
        p_items = session.scalars(select(PurchaseItem)).all()
        qty_by_purchase: dict[int, int] = {}
        for pi in p_items:
            qty_by_purchase[pi.purchase_id] = (
                qty_by_purchase.get(pi.purchase_id, 0) + pi.quantity
            )

        suppliers: dict[str, dict] = {}
        q = (search_query or "").strip().lower()

        for pur in purchases:
            is_personal = is_personal_source_purchase(pur)
            name = (pur.supplier_name or PERSONAL_SOURCE_LABEL).strip()
            if q and q not in name.lower():
                continue

            if name not in suppliers:
                suppliers[name] = {
                    "supplier_name": name,
                    "active_purchases": 0,
                    "cancelled_purchases": 0,
                    "units_supplied": 0,
                    "total_usd": Decimal("0.00"),
                    "paid_usd": Decimal("0.00"),
                    "debt_usd": Decimal("0.00"),
                    "supplier_owes_usd": Decimal("0.00"),
                    "total_tmt": Decimal("0.00"),
                    "paid_tmt": Decimal("0.00"),
                    "debt_tmt": Decimal("0.00"),
                    "supplier_owes_tmt": Decimal("0.00"),
                }

            s = suppliers[name]
            cur = pur.currency.strip().upper()
            total = _money(_decimal(pur.total_amount))
            paid = _get_purchase_paid_amount(session, pur)

            if pur.status == "cancelled":
                s["cancelled_purchases"] += 1
                sup_debt = Decimal("0.00") if is_personal else _get_supplier_debt_amount(session, pur)
                if cur == "USD":
                    s["supplier_owes_usd"] = _money(s["supplier_owes_usd"] + sup_debt)
                elif cur == "TMT":
                    s["supplier_owes_tmt"] = _money(s["supplier_owes_tmt"] + sup_debt)
            else:
                s["active_purchases"] += 1
                s["units_supplied"] += qty_by_purchase.get(pur.id, 0)
                rem = Decimal("0.00") if is_personal else max(Decimal("0.00"), _money(total - paid))
                if cur == "USD":
                    s["total_usd"] = _money(s["total_usd"] + total)
                    s["paid_usd"] = _money(s["paid_usd"] + paid)
                    s["debt_usd"] = _money(s["debt_usd"] + rem)
                elif cur == "TMT":
                    s["total_tmt"] = _money(s["total_tmt"] + total)
                    s["paid_tmt"] = _money(s["paid_tmt"] + paid)
                    s["debt_tmt"] = _money(s["debt_tmt"] + rem)

        return list(suppliers.values())

    @staticmethod
    def get_customer_report(session: Session, search_query: str = "") -> list[dict]:
        """Отчет по клиентам (Раздел 7.8)."""
        sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc())).all()
        exchanges = session.scalars(select(DeviceExchange)).all()
        ex_count_by_sale: dict[int, int] = {}
        for ex in exchanges:
            ex_count_by_sale[ex.original_sale_id] = (
                ex_count_by_sale.get(ex.original_sale_id, 0) + 1
            )

        customers: dict[str, dict] = {}
        q = (search_query or "").strip().lower()

        for sale in sales:
            cname = (sale.customer_name or "Bölek müşderi").strip()
            cphone = (sale.customer_phone or "").strip()
            key = f"{cname} ({cphone})" if cphone else cname
            if q and q not in key.lower():
                continue

            if key not in customers:
                customers[key] = {
                    "customer_label": key,
                    "active_sales": 0,
                    "cancelled_sales": 0,
                    "exchanges_count": 0,
                    "total_usd": Decimal("0.00"),
                    "paid_usd": Decimal("0.00"),
                    "debt_usd": Decimal("0.00"),
                    "store_owes_usd": Decimal("0.00"),
                    "total_tmt": Decimal("0.00"),
                    "paid_tmt": Decimal("0.00"),
                    "debt_tmt": Decimal("0.00"),
                    "store_owes_tmt": Decimal("0.00"),
                }

            c = customers[key]
            c["exchanges_count"] += ex_count_by_sale.get(sale.id, 0)
            cur = sale.currency.strip().upper()
            total = _money(_decimal(sale.total_amount))
            paid = SalesService.get_sale_paid_amount(session, sale)

            if sale.status == "cancelled":
                c["cancelled_sales"] += 1
                s_owes = SalesService.get_store_debt_to_customer(session, sale)
                if cur == "USD":
                    c["store_owes_usd"] = _money(c["store_owes_usd"] + s_owes)
                elif cur == "TMT":
                    c["store_owes_tmt"] = _money(c["store_owes_tmt"] + s_owes)
            else:
                c["active_sales"] += 1
                c_debt = SalesService.get_customer_debt(session, sale)
                if cur == "USD":
                    c["total_usd"] = _money(c["total_usd"] + total)
                    c["paid_usd"] = _money(c["paid_usd"] + paid)
                    c["debt_usd"] = _money(c["debt_usd"] + c_debt)
                elif cur == "TMT":
                    c["total_tmt"] = _money(c["total_tmt"] + total)
                    c["paid_tmt"] = _money(c["paid_tmt"] + paid)
                    c["debt_tmt"] = _money(c["debt_tmt"] + c_debt)

        return list(customers.values())

    @staticmethod
    def get_stock_valuation(
        session: Session,
        exchange_rate: Decimal | float | str | None = None,
    ) -> dict:
        """Рассчитывает общую стоимость всех активных товаров на складе в обеих валютах (USD и TMT).

        Для IMEI-устройств используется фактическая себестоимость каждого in_stock StockItem.
        Для количественных остатков — себестоимость единицы (из последней закупки или базовой цены).
        """
        from app.services.settings_service import SettingsService

        if exchange_rate is None:
            rate = _validate_rate(SettingsService.get_default_exchange_rate())
        else:
            rate = _validate_rate(exchange_rate)

        prod_rows = session.execute(
            select(Product, Category.name)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Product.is_active.is_(True), Product.stock_quantity > 0)
        ).all()

        in_stock_items = session.scalars(
            select(StockItem).where(StockItem.status == "in_stock")
        ).all()
        items_by_prod: dict[int, list[StockItem]] = {}
        for st in in_stock_items:
            items_by_prod.setdefault(st.product_id, []).append(st)

        usd_native = Decimal("0.00")
        tmt_native = Decimal("0.00")
        total_units = 0
        devices_count = 0
        accessories_count = 0
        by_cat_map: dict[int, dict] = {}

        for prod, cat_name in prod_rows:
            qty = int(prod.stock_quantity or 0)
            if qty <= 0:
                continue
            total_units += qty
            imei_items = items_by_prod.get(prod.id, [])
            imei_cnt = len(imei_items)
            devices_count += imei_cnt

            cat_id = int(prod.category_id or 0)
            cat_entry = by_cat_map.get(cat_id)
            if cat_entry is None:
                cat_entry = {
                    "category_id": cat_id,
                    "category_name": cat_name or "Kategoriýasyz",
                    "products_count": 0,
                    "devices_count": 0,
                    "accessories_count": 0,
                    "total_units": 0,
                    "usd_native": Decimal("0.00"),
                    "tmt_native": Decimal("0.00"),
                }
                by_cat_map[cat_id] = cat_entry

            cat_entry["products_count"] += 1
            cat_entry["devices_count"] += imei_cnt
            cat_entry["total_units"] += qty

            for st in imei_items:
                u_cost, u_curr, _u_rate = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=prod.id,
                    stock_item=st,
                    fallback_currency="USD",
                    fallback_rate=rate,
                )
                if u_curr == "USD":
                    usd_native = _money(usd_native + u_cost)
                    cat_entry["usd_native"] = _money(cat_entry["usd_native"] + u_cost)
                else:
                    tmt_native = _money(tmt_native + u_cost)
                    cat_entry["tmt_native"] = _money(cat_entry["tmt_native"] + u_cost)

            rem_qty = max(0, qty - imei_cnt)
            if rem_qty > 0:
                accessories_count += rem_qty
                cat_entry["accessories_count"] += rem_qty
                u_cost, u_curr, _u_rate = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=prod.id,
                    stock_item=None,
                    fallback_currency="USD",
                    fallback_rate=rate,
                )
                line_val = _money(u_cost * rem_qty)
                if u_curr == "USD":
                    usd_native = _money(usd_native + line_val)
                    cat_entry["usd_native"] = _money(cat_entry["usd_native"] + line_val)
                else:
                    tmt_native = _money(tmt_native + line_val)
                    cat_entry["tmt_native"] = _money(cat_entry["tmt_native"] + line_val)

        by_category: list[dict] = []
        for entry in by_cat_map.values():
            c_usd = entry["usd_native"]
            c_tmt = entry["tmt_native"]
            entry["total_in_usd"] = _money(c_usd + (c_tmt / rate))
            entry["total_in_tmt"] = _money(c_tmt + (c_usd * rate))
            by_category.append(entry)
        by_category.sort(key=lambda x: x["total_in_tmt"], reverse=True)

        total_in_usd = _money(usd_native + (tmt_native / rate))
        total_in_tmt = _money(tmt_native + (usd_native * rate))

        return {
            "usd_native": usd_native,
            "tmt_native": tmt_native,
            "total_in_usd": total_in_usd,
            "total_in_tmt": total_in_tmt,
            "exchange_rate": rate,
            "total_units": total_units,
            "devices_count": devices_count,
            "accessories_count": accessories_count,
            "by_category": by_category,
        }
