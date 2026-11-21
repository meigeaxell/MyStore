from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_movement import CashMovement
from app.models.device_exchange import DeviceExchange
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.stock_item import StockItem
from app.services.cash_service import CashService, _decimal, _money, _validate_rate
from app.services.sales_service import SalesService, _convert_currency


class ExchangeService:
    """Сервис обмена устройств (Trade-in / Exchange — приём по IMEI без обязательного чека)."""

    @staticmethod
    def inspect_incoming_imei(
        session: Session,
        imei: str,
    ) -> dict:
        """Проверяет IMEI принимаемого по Trade-In устройства в базе данных.

        Возвращает словарь:
        - exists: bool
        - status: 'not_found' | 'in_stock' | 'sold'
        - eligible: bool (нельзя принять повторно, если уже in_stock)
        - message: понятное описание статуса для сотрудника
        - stock_item_id, product_id, product_name, sku, condition
        - last_sale_id, last_sale_item_id, receipt_number, last_sale_price, last_sale_currency
        """
        clean_imei = (imei or "").strip()
        if not clean_imei:
            return {
                "exists": False,
                "status": "empty",
                "eligible": False,
                "message": "Müşderiniň köne enjamynyň IMEI-sini giriziň ýa-da skanirläň.",
            }

        row = session.execute(
            select(StockItem, Product)
            .join(Product, StockItem.product_id == Product.id)
            .where((StockItem.imei1 == clean_imei) | (StockItem.imei2 == clean_imei))
        ).first()

        if row is None:
            return {
                "exists": False,
                "status": "not_found",
                "eligible": True,
                "imei": clean_imei,
                "stock_item_id": None,
                "product_id": None,
                "product_name": None,
                "sku": None,
                "condition": "used",
                "last_sale_id": None,
                "last_sale_item_id": None,
                "receipt_number": None,
                "last_sale_price": None,
                "last_sale_currency": None,
                "message": (
                    f"IMEI {clean_imei} baza üçin täze. Enjamyň modelini saýlaň we bahasyny görkeziň "
                    "— enjam sklada B/U hökmünde goşular."
                ),
            }

        st, product = row
        if st.status == "in_stock":
            return {
                "exists": True,
                "status": "in_stock",
                "eligible": False,
                "imei": st.imei1,
                "stock_item_id": st.id,
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "condition": st.condition,
                "last_sale_id": None,
                "last_sale_item_id": None,
                "receipt_number": None,
                "last_sale_price": None,
                "last_sale_currency": None,
                "message": (
                    f"«{product.name}» (IMEI: {st.imei1}) enjam EÝÝÄM dükanyň skladynda bar. "
                    "Gaýtadan kabul edip bolmaýar."
                ),
            }

        # Устройство ранее было в базе и сейчас продано — ищем последний активный чек (если есть)
        sale_row = session.execute(
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

        last_sale_id = None
        last_sale_item_id = None
        receipt_number = None
        last_price = None
        last_curr = None

        if sale_row is not None:
            s_item, sale = sale_row
            last_sale_id = sale.id
            last_sale_item_id = s_item.id
            receipt_number = sale.receipt_number
            last_price = _money(
                _decimal(s_item.unit_price)
                - (_decimal(s_item.discount) / Decimal(str(max(1, s_item.quantity))))
            )
            last_curr = s_item.currency

        sale_note = (
            f" (öň {receipt_number} çeki bilen {last_price} {last_curr} bahadan satyldy)"
            if receipt_number
            else ""
        )
        return {
            "exists": True,
            "status": "sold",
            "eligible": True,
            "imei": st.imei1,
            "stock_item_id": st.id,
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "condition": "used",
            "last_sale_id": last_sale_id,
            "last_sale_item_id": last_sale_item_id,
            "receipt_number": receipt_number,
            "last_sale_price": last_price,
            "last_sale_currency": last_curr,
            "message": (
                f"Bazada tapyldy: «{product.name}» ({product.sku}){sale_note}. "
                "Enjam Trade-In kabul ediş we sklada gaýtarmak üçin elýeterli."
            ),
        }

    @staticmethod
    def find_sale_items_for_exchange(
        session: Session,
        search_query: str,
    ) -> list[dict]:
        """Ищет позиции проданных чеков по номеру чека, IMEI или имени клиента."""
        q = (search_query or "").strip()
        if not q:
            return []

        stmt = (
            select(SaleItem, Sale, Product)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
            .where(
                (Sale.receipt_number.ilike(f"%{q}%"))
                | (SaleItem.imei.ilike(f"%{q}%"))
                | (Sale.customer_name.ilike(f"%{q}%"))
            )
            .order_by(Sale.sale_date.desc(), SaleItem.id.asc())
            .limit(50)
        )

        rows = session.execute(stmt).all()
        results = []

        for s_item, sale, product in rows:
            stock_item = (
                session.get(StockItem, s_item.stock_item_id)
                if s_item.stock_item_id
                else None
            )
            if stock_item is None and s_item.imei:
                stock_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == s_item.product_id,
                        (StockItem.imei1 == s_item.imei) | (StockItem.imei2 == s_item.imei),
                    )
                )

            net_unit_price = _money(
                _decimal(s_item.unit_price)
                - (_decimal(s_item.discount) / Decimal(str(max(1, s_item.quantity))))
            )

            eligible = True
            ineligible_reason = ""
            if sale.status == "cancelled":
                eligible = False
                ineligible_reason = "Asyl çek ýatyryldy"
            elif s_item.is_exchanged:
                eligible = False
                ineligible_reason = "Enjam eýýäm çalşyldy"
            elif stock_item is not None and stock_item.status == "in_stock":
                eligible = False
                ineligible_reason = "Enjam eýýäm skladda bar"

            results.append({
                "sale_id": sale.id,
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "sale_status": sale.status,
                "customer_name": sale.customer_name or "Bölek müşderi",
                "sale_item_id": s_item.id,
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "imei": s_item.imei,
                "stock_item_id": stock_item.id if stock_item else s_item.stock_item_id,
                "unit_price": net_unit_price,
                "currency": s_item.currency,
                "exchange_rate": _validate_rate(sale.exchange_rate or Decimal("1.0000")),
                "is_exchanged": s_item.is_exchanged,
                "eligible": eligible,
                "ineligible_reason": ineligible_reason,
            })

        return results

    @staticmethod
    def find_available_replacement_items(
        session: Session,
        search_query: str = "",
        exclude_stock_item_id: int | None = None,
    ) -> list[dict]:
        """Возвращает доступные на складе устройства (с IMEI) и товары для выбора в качестве замены."""
        q = (search_query or "").strip().lower()
        results = []

        stock_rows = session.execute(
            select(StockItem, Product)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                StockItem.status == "in_stock",
                Product.is_active.is_(True),
                Product.stock_quantity > 0,
            )
            .order_by(Product.name.asc(), StockItem.id.desc())
        ).all()

        imei_cnt_by_prod: dict[int, int] = {}
        for st_item, product in stock_rows:
            imei_cnt_by_prod[product.id] = imei_cnt_by_prod.get(product.id, 0) + 1
            if exclude_stock_item_id and st_item.id == exclude_stock_item_id:
                continue
            hay = f"{product.name} {product.sku} {st_item.imei1} {st_item.imei2 or ''}".lower()
            if q and q not in hay:
                continue
            results.append({
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "stock_item_id": st_item.id,
                "imei": st_item.imei1,
                "condition": st_item.condition,
                "stock_quantity": product.stock_quantity,
                "label": f"{product.name} • IMEI: {st_item.imei1} ({st_item.condition})",
            })

        products = session.scalars(
            select(Product)
            .where(
                Product.is_active.is_(True),
                Product.stock_quantity > 0,
            )
            .order_by(Product.name.asc())
        ).all()

        for product in products:
            non_imei_qty = product.stock_quantity - imei_cnt_by_prod.get(product.id, 0)
            if non_imei_qty <= 0:
                continue
            hay = f"{product.name} {product.sku} {product.brand or ''} {product.model or ''}".lower()
            if q and q not in hay:
                continue
            results.append({
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "stock_item_id": None,
                "imei": None,
                "condition": "new",
                "stock_quantity": non_imei_qty,
                "label": f"{product.name} ({product.sku}) • IMEI-siz (galyndy: {non_imei_qty} sany)",
            })

        return results

    @staticmethod
    def process_exchange(
        session: Session,
        original_sale_id: int | None = None,
        original_sale_item_id: int | None = None,
        new_product_id: int = 0,
        new_price: Decimal | float | str = Decimal("0.00"),
        reason: str = "",
        new_stock_item_id: int | None = None,
        new_imei: str | None = None,
        currency: str | None = None,
        exchange_rate: Decimal | float | str = Decimal("1.0000"),
        payments: list[dict] | None = None,
        note: str | None = None,
        old_product_id: int | None = None,
        old_imei: str | None = None,
        old_imei2: str | None = None,
        old_serial_number: str | None = None,
        old_price: Decimal | float | str | None = None,
        old_condition: str = "used",
    ) -> DeviceExchange:
        """Выполняет обмен устройства/товара как с исходным чеком, так и без чека (по IMEI и оценке)."""
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Çalyşygyň sebäbini ýa-da düşündirişini görkeziň.")
        if len(reason) > 255:
            raise ValueError("Çalyşyk sebäbi 255 simwoldan uzyn bolmaly däl.")

        clean_note = (note or "").strip() or None
        clean_cond = "new" if str(old_condition).lower() in ("new", "täze", "новый") else "used"
        rate = _validate_rate(exchange_rate)
        now = datetime.now()

        sale = None
        sale_item = None
        old_product = None
        old_stock_item = None

        if original_sale_id is not None and original_sale_item_id is not None:
            sale = session.get(Sale, original_sale_id)
            if not sale:
                raise ValueError(f"ID {original_sale_id} asyl çek tapylmady.")
            if sale.status == "cancelled":
                raise ValueError("Ýatyrylan çek boýunça çalyşyk edip bolmaýar.")

            sale_item = session.get(SaleItem, original_sale_item_id)
            if not sale_item or sale_item.sale_id != sale.id:
                raise ValueError("Saýlanan setir görkezilen çeke degişli däl.")
            if sale_item.is_exchanged:
                raise ValueError("Bu enjam/haryt öň eýýäm çalşyldy.")

            existing_ex = session.scalar(
                select(DeviceExchange).where(
                    DeviceExchange.original_sale_item_id == sale_item.id
                )
            )
            if existing_ex is not None:
                raise ValueError("Bu çek setiri boýunça eýýäm çalyşyk hasaba alnan.")

            old_product = session.get(Product, sale_item.product_id)
            if not old_product:
                raise ValueError("Asyl haryt katalogda tapylmady.")

            if sale_item.stock_item_id:
                old_stock_item = session.get(StockItem, sale_item.stock_item_id)
            elif sale_item.imei:
                old_stock_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == sale_item.product_id,
                        (StockItem.imei1 == sale_item.imei) | (StockItem.imei2 == sale_item.imei),
                    )
                )

            if old_stock_item is not None:
                if old_stock_item.status == "in_stock":
                    raise ValueError("Köne enjam eýýäm skladda bar.")
                already_exchanged_imei = session.scalar(
                    select(DeviceExchange).where(
                        DeviceExchange.old_stock_item_id == old_stock_item.id
                    )
                )
                if already_exchanged_imei is not None:
                    raise ValueError(f"IMEI {old_stock_item.imei1} enjam öň eýýäm çalşyldy.")

            doc_currency = (currency or sale_item.currency or sale.currency).strip().upper()
            if doc_currency not in ("USD", "TMT"):
                raise ValueError("Rugsat berlen çalyşyk walýutalary: USD, TMT.")

            if old_price is not None:
                old_price_doc = _money(_decimal(old_price))
            else:
                raw_old_unit_price = _money(
                    _decimal(sale_item.unit_price)
                    - (_decimal(sale_item.discount) / Decimal(str(max(1, sale_item.quantity))))
                )
                old_price_doc = _convert_currency(
                    raw_old_unit_price,
                    sale_item.currency,
                    doc_currency,
                    rate,
                )
            resolved_old_imei = (
                old_stock_item.imei1 if old_stock_item else (sale_item.imei or (old_imei or "").strip() or None)
            )

        else:
            doc_currency = (currency or "TMT").strip().upper()
            if doc_currency not in ("USD", "TMT"):
                raise ValueError("Rugsat berlen çalyşyk walýutalary: USD, TMT.")

            clean_old_imei = (old_imei or "").strip()
            clean_old_imei2 = (old_imei2 or "").strip() or None
            if not clean_old_imei:
                raise ValueError("Müşderiniň köne enjamynyň IMEI-sini giriziň.")
            if clean_old_imei2 and clean_old_imei == clean_old_imei2:
                raise ValueError("Köne enjamyň IMEI 1 we IMEI 2 belgileri birmeňzeş bolup bilmez.")

            if old_price is None:
                raise ValueError("Köne enjamyň bahasyny görkeziň.")
            old_price_doc = _money(_decimal(old_price))
            if old_price_doc <= Decimal("0.00"):
                raise ValueError("Köne enjamyň bahasy noldan uly bolmaly.")

            old_stock_item = session.scalar(
                select(StockItem).where(
                    (StockItem.imei1 == clean_old_imei)
                    | (StockItem.imei2 == clean_old_imei)
                    | (
                        (StockItem.imei1 == clean_old_imei2) | (StockItem.imei2 == clean_old_imei2)
                        if clean_old_imei2
                        else False
                    )
                )
            )

            if old_stock_item is not None:
                if old_stock_item.status == "in_stock":
                    raise ValueError(
                        f"IMEI {old_stock_item.imei1} enjam eýýäm dükanyň skladynda bar."
                    )
                old_product = session.get(Product, old_stock_item.product_id)
                last_sale_row = session.execute(
                    select(SaleItem, Sale)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .where(
                        Sale.status != "cancelled",
                        (SaleItem.stock_item_id == old_stock_item.id)
                        | (SaleItem.imei == old_stock_item.imei1),
                    )
                    .order_by(Sale.sale_date.desc())
                ).first()
                if last_sale_row is not None:
                    sale_item, sale = last_sale_row
            else:
                if not old_product_id:
                    raise ValueError("Kabul edilýän köne enjam üçin model (haryt) saýlaň.")
                old_product = session.get(Product, int(old_product_id))
                if not old_product or not old_product.is_active:
                    raise ValueError("Köne enjamyň modeli katalogda tapylmady.")

            resolved_old_imei = old_stock_item.imei1 if old_stock_item else clean_old_imei

        new_price_doc = _money(_decimal(new_price))
        if new_price_doc <= 0:
            raise ValueError("Täze enjamyň bahasy noldan uly bolmaly.")

        if new_price_doc < old_price_doc:
            raise ValueError(
                f"Çalyşyk gadagan: täze enjam ({new_price_doc} {doc_currency}) "
                f"köneden ({old_price_doc} {doc_currency}) arzan. Müşderä tapawut gaýtarylmaýar."
            )

        price_diff = _money(new_price_doc - old_price_doc)

        new_product = session.get(Product, new_product_id)
        if not new_product or not new_product.is_active:
            raise ValueError("Çalşylýan haryt tapylmady ýa-da öçürilen.")

        new_stock_item = None
        if new_stock_item_id is not None:
            new_stock_item = session.get(StockItem, new_stock_item_id)
            if not new_stock_item or new_stock_item.product_id != new_product.id:
                raise ValueError("Çalşylýan enjam skladda tapylmady.")
        elif new_imei:
            new_imei = str(new_imei).strip()
            new_stock_item = session.scalar(
                select(StockItem).where(
                    StockItem.product_id == new_product.id,
                    (StockItem.imei1 == new_imei) | (StockItem.imei2 == new_imei),
                )
            )
            if not new_stock_item:
                raise ValueError(f"IMEI {new_imei} enjam skladda tapylmady.")

        if new_stock_item is not None:
            if new_stock_item.status != "in_stock":
                raise ValueError(
                    f"Çalşylýan enjam (IMEI {new_stock_item.imei1}) eýýäm satyldy ýa-da elýeterli däl."
                )
            if old_stock_item is not None and new_stock_item.id == old_stock_item.id:
                raise ValueError("Enjamy öz-özüne çalyşyp bolmaýar.")
            if resolved_old_imei and new_stock_item.imei1 == resolved_old_imei:
                raise ValueError("Enjamy öz-özüne çalyşyp bolmaýar.")

        if new_product.stock_quantity < 1:
            raise ValueError(f"«{new_product.name}» harydy skladda ýok.")

        payments = payments or []
        if price_diff == Decimal("0.00") and payments:
            non_zero = [p for p in payments if _money(_decimal(p.get("amount", 0))) > 0]
            if non_zero:
                raise ValueError("Enjamlaryň bahasy deň bolanda goşmaça töleg gerek däl.")
            payments = []

        if price_diff > Decimal("0.00"):
            if not payments:
                raise ValueError(
                    f"Çalyşyk üçin {price_diff} {doc_currency} goşmaça töleg girizmeli."
                )
            total_paid_doc = Decimal("0.00")
            for p in payments:
                p_amt = _money(_decimal(p.get("amount", 0)))
                if p_amt <= 0:
                    raise ValueError("Goşmaça töleg mukdary noldan uly bolmaly.")
                p_cur = str(p.get("currency", doc_currency)).strip().upper()
                p_rate = _validate_rate(p.get("exchange_rate", rate))
                total_paid_doc += _convert_currency(p_amt, p_cur, doc_currency, p_rate)

            total_paid_doc = _money(total_paid_doc)
            if total_paid_doc < price_diff:
                raise ValueError(
                    f"Goşmaça töleg ({total_paid_doc} {doc_currency}) baha tapawudyndan "
                    f"({price_diff} {doc_currency}) az."
                )

        # Принимаем старое устройство на склад (обновляем или создаём StockItem)
        old_product.stock_quantity += 1
        if old_stock_item is not None:
            old_stock_item.status = "in_stock"
            old_stock_item.condition = clean_cond
            old_stock_item.unit_cost = old_price_doc
            old_stock_item.cost_currency = doc_currency
            old_stock_item.cost_exchange_rate = rate
            old_stock_item.acquisition_source = "trade_in"
            if clean_note:
                old_stock_item.notes = clean_note
        elif resolved_old_imei:
            old_stock_item = StockItem(
                product_id=old_product.id,
                imei1=resolved_old_imei,
                imei2=(old_imei2 or "").strip() or None,
                serial_number=(old_serial_number or "").strip() or None,
                condition=clean_cond,
                status="in_stock",
                unit_cost=old_price_doc,
                cost_currency=doc_currency,
                cost_exchange_rate=rate,
                acquisition_source="trade_in",
                notes=clean_note or reason,
                created_at=now,
            )
            session.add(old_stock_item)
            session.flush()

        if sale_item is not None:
            sale_item.is_exchanged = True

        # Списываем новое устройство со склада
        new_product.stock_quantity -= 1
        if new_stock_item is not None:
            new_stock_item.status = "sold"

        new_cost, new_cost_curr, new_cost_rate = SalesService._resolve_item_cost_basis(
            session=session,
            product_id=new_product.id,
            stock_item=new_stock_item,
            fallback_currency=doc_currency,
            fallback_rate=rate,
        )

        ex_number = f"EX-{now.strftime('%Y%m%d%H%M%S-%f')}"
        exchange_doc = DeviceExchange(
            exchange_number=ex_number,
            exchange_date=now,
            original_sale_id=sale.id if sale else None,
            original_sale_item_id=sale_item.id if sale_item else None,
            old_product_id=old_product.id,
            old_stock_item_id=old_stock_item.id if old_stock_item else None,
            old_imei=resolved_old_imei,
            old_condition=clean_cond,
            old_price=old_price_doc,
            new_product_id=new_product.id,
            new_stock_item_id=new_stock_item.id if new_stock_item else None,
            new_imei=new_stock_item.imei1 if new_stock_item else None,
            new_price=new_price_doc,
            new_unit_cost=new_cost,
            new_cost_currency=new_cost_curr,
            new_cost_exchange_rate=new_cost_rate,
            price_difference=price_diff,
            currency=doc_currency,
            exchange_rate=rate,
            reason=reason,
            note=clean_note,
        )
        session.add(exchange_doc)
        session.flush()

        if price_diff > Decimal("0.00"):
            regs = SalesService.ensure_default_registers(session)
            total_paid_doc = Decimal("0.00")
            ref_sale_id = sale.id if sale else None
            doc_ref = f"çek {sale.receipt_number}" if sale else f"IMEI {resolved_old_imei or '—'}"

            for p in payments:
                p_amt = _money(_decimal(p.get("amount", 0)))
                p_cur = str(p.get("currency", doc_currency)).strip().upper()
                p_rate = _validate_rate(p.get("exchange_rate", rate))
                reg_id = p.get("cash_register_id") or regs[p_cur].id
                desc = f"{ex_number} çalyşyk goşmaça tölegi ({doc_ref})"

                CashService.adjust_register_balance(
                    session=session,
                    cash_register_id=reg_id,
                    amount=p_amt,
                    transaction_type="income",
                    currency=p_cur,
                    exchange_rate=p_rate,
                    description=desc,
                    sale_id=ref_sale_id,
                )
                session.add(
                    CashMovement(
                        movement_date=now,
                        movement_type="exchange_payment",
                        currency=p_cur,
                        amount=p_amt,
                        exchange_rate=p_rate,
                        cash_register_id=reg_id,
                        sale_id=ref_sale_id,
                        description=desc,
                    )
                )
                total_paid_doc += _convert_currency(p_amt, p_cur, doc_currency, p_rate)

            change_amt = _money(total_paid_doc - price_diff)
            if change_amt > Decimal("0.00"):
                change_reg = regs[doc_currency]
                c_desc = f"{ex_number} çalyşyk goşmaça töleginden gaýtargy"
                CashService.adjust_register_balance(
                    session=session,
                    cash_register_id=change_reg.id,
                    amount=change_amt,
                    transaction_type="expense",
                    currency=doc_currency,
                    exchange_rate=rate,
                    description=c_desc,
                    sale_id=ref_sale_id,
                )
                session.add(
                    CashMovement(
                        movement_date=now,
                        movement_type="sale_change",
                        currency=doc_currency,
                        amount=change_amt,
                        exchange_rate=rate,
                        cash_register_id=change_reg.id,
                        sale_id=ref_sale_id,
                        description=c_desc,
                    )
                )

        session.flush()
        return exchange_doc

    @staticmethod
    def get_exchange_history(
        session: Session,
        search_query: str = "",
    ) -> list[dict]:
        """Возвращает историю всех обменов устройств (с чеком и без чека)."""
        exchanges = session.scalars(
            select(DeviceExchange).order_by(DeviceExchange.exchange_date.desc())
        ).all()

        results = []
        q = (search_query or "").strip().lower()

        for ex in exchanges:
            sale = session.get(Sale, ex.original_sale_id) if ex.original_sale_id else None
            old_prod = session.get(Product, ex.old_product_id)
            new_prod = session.get(Product, ex.new_product_id)

            receipt_num = sale.receipt_number if sale else "Çeksiz (Trade-in)"
            old_name = old_prod.name if old_prod else f"ID {ex.old_product_id}"
            new_name = new_prod.name if new_prod else f"ID {ex.new_product_id}"

            entry = {
                "id": ex.id,
                "exchange_number": ex.exchange_number,
                "exchange_date": ex.exchange_date,
                "original_sale_id": ex.original_sale_id,
                "receipt_number": receipt_num,
                "old_product_name": old_name,
                "old_imei": ex.old_imei or "—",
                "old_condition": ex.old_condition or "used",
                "old_price": _money(_decimal(ex.old_price)),
                "new_product_name": new_name,
                "new_imei": ex.new_imei or "—",
                "new_price": _money(_decimal(ex.new_price)),
                "price_difference": _money(_decimal(ex.price_difference)),
                "currency": ex.currency,
                "exchange_rate": _validate_rate(ex.exchange_rate),
                "reason": ex.reason,
                "note": ex.note or "",
            }

            if q:
                hay = (
                    f"{entry['exchange_number']} {entry['receipt_number']} "
                    f"{entry['old_product_name']} {entry['old_imei']} "
                    f"{entry['new_product_name']} {entry['new_imei']} {entry['reason']}"
                ).lower()
                if q not in hay:
                    continue

            results.append(entry)

        return results
