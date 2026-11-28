from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_movement import CashMovement
from app.models.cash_register import CashRegister, CashTransaction
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.sale_payment import SalePayment
from app.models.stock_item import StockItem
from app.services.cash_service import CashService, _decimal, _money, _validate_rate


def _convert_currency(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    exchange_rate: Decimal,
) -> Decimal:
    """Пересчитывает сумму в целевую валюту (курс выражен как 1 USD = X TMT)."""
    src = source_currency.strip().upper()
    dst = target_currency.strip().upper()
    if src == dst:
        return _money(amount)
    if src == "TMT" and dst == "USD":
        return _money(amount / exchange_rate)
    if src == "USD" and dst == "TMT":
        return _money(amount * exchange_rate)
    raise ValueError("Walýutalar gabat gelmeýär.")


class SalesService:
    @staticmethod
    def ensure_default_registers(session: Session) -> dict[str, CashRegister]:
        """Гарантирует наличие базовых касс USD и TMT."""
        registers = session.scalars(select(CashRegister)).all()
        by_currency: dict[str, CashRegister] = {}
        for reg in registers:
            cur = reg.currency.strip().upper()
            if cur not in by_currency:
                by_currency[cur] = reg

        defaults = (
            ("USD", "Kassa USD"),
            ("TMT", "Kassa TMT"),
        )
        created = False
        for cur, default_name in defaults:
            if cur not in by_currency:
                existing_name = session.scalar(
                    select(CashRegister).where(CashRegister.name == default_name)
                )
                name = default_name if not existing_name else f"{default_name} ({cur})"
                reg = CashRegister(
                    name=name,
                    currency=cur,
                    balance=Decimal("0.00"),
                )
                session.add(reg)
                by_currency[cur] = reg
                created = True

        if created:
            session.flush()

        return by_currency

    @staticmethod
    def _resolve_item_cost_basis(
        session: Session,
        product_id: int,
        stock_item: StockItem | None,
        fallback_currency: str,
        fallback_rate: Decimal,
    ) -> tuple[Decimal, str, Decimal]:
        """Определяет историческую себестоимость товара на момент продажи."""
        if stock_item is not None and stock_item.unit_cost is not None:
            cost = _money(_decimal(stock_item.unit_cost))
            curr = (stock_item.cost_currency or fallback_currency).strip().upper()
            rate = (
                _validate_rate(stock_item.cost_exchange_rate)
                if stock_item.cost_exchange_rate
                else fallback_rate
            )
            return cost, curr, rate

        if stock_item is not None and stock_item.purchase_id is not None:
            row = session.execute(
                select(PurchaseItem, Purchase)
                .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
                .where(
                    PurchaseItem.purchase_id == stock_item.purchase_id,
                    PurchaseItem.product_id == product_id,
                )
                .order_by(PurchaseItem.id.desc())
            ).first()
            if row:
                p_item, purchase = row
                return (
                    _money(_decimal(p_item.unit_cost)),
                    purchase.currency.strip().upper(),
                    _validate_rate(purchase.exchange_rate),
                )

        if stock_item is None:
            from app.services.settings_service import SettingsService

            default_cost = SettingsService.get_product_default_cost(product_id)
            if default_cost is not None:
                d_cost, d_curr = default_cost
                return _money(d_cost), d_curr, fallback_rate

        latest_row = session.execute(
            select(PurchaseItem, Purchase)
            .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
            .where(
                PurchaseItem.product_id == product_id,
                Purchase.status == "active",
            )
            .order_by(Purchase.purchase_date.desc(), PurchaseItem.id.desc())
        ).first()
        if latest_row:
            p_item, purchase = latest_row
            return (
                _money(_decimal(p_item.unit_cost)),
                purchase.currency.strip().upper(),
                _validate_rate(purchase.exchange_rate),
            )

        from app.services.settings_service import SettingsService

        default_cost = SettingsService.get_product_default_cost(product_id)
        if default_cost is not None:
            d_cost, d_curr = default_cost
            return _money(d_cost), d_curr, fallback_rate

        return Decimal("0.00"), fallback_currency, fallback_rate

    @staticmethod
    def get_sale_paid_amount(
        session: Session,
        sale: Sale,
        include_write_off: bool = False,
    ) -> Decimal:
        """Возвращает чистую оплаченную клиентом сумму в валюте чека."""
        allowed_types = ("payment", "write_off") if include_write_off else ("payment",)
        payments = session.scalars(
            select(SalePayment).where(
                SalePayment.sale_id == sale.id,
                SalePayment.payment_type.in_(allowed_types),
            )
        ).all()

        if payments:
            paid = Decimal("0.00")
            for p in payments:
                if not include_write_off and p.cash_register_id is None and p.payment_type != "payment":
                    continue
                p_rate = _validate_rate(p.exchange_rate or sale.exchange_rate or Decimal("1.0000"))
                paid += _convert_currency(
                    _decimal(p.amount),
                    p.currency,
                    sale.currency,
                    p_rate,
                )
            change_txs = session.scalars(
                select(CashTransaction).where(
                    CashTransaction.sale_id == sale.id,
                    CashTransaction.transaction_type == "expense",
                )
            ).all()
            for ctx in change_txs:
                c_rate = _validate_rate(ctx.exchange_rate or sale.exchange_rate or Decimal("1.0000"))
                paid -= _convert_currency(
                    _decimal(ctx.amount),
                    ctx.currency,
                    sale.currency,
                    c_rate,
                )
            return max(Decimal("0.00"), _money(paid))

        # Обратная совместимость для чеков без записей в sale_payments (по CashTransaction)
        income_txs = session.scalars(
            select(CashTransaction).where(
                CashTransaction.sale_id == sale.id,
                CashTransaction.transaction_type == "income",
            )
        ).all()
        paid = Decimal("0.00")
        for tx in income_txs:
            t_rate = _validate_rate(tx.exchange_rate or sale.exchange_rate or Decimal("1.0000"))
            paid += _convert_currency(
                _decimal(tx.amount),
                tx.currency,
                sale.currency,
                t_rate,
            )
        change_txs = session.scalars(
            select(CashTransaction).where(
                CashTransaction.sale_id == sale.id,
                CashTransaction.transaction_type == "expense",
            )
        ).all()
        for ctx in change_txs:
            c_rate = _validate_rate(ctx.exchange_rate or sale.exchange_rate or Decimal("1.0000"))
            paid -= _convert_currency(
                _decimal(ctx.amount),
                ctx.currency,
                sale.currency,
                c_rate,
            )
        return max(Decimal("0.00"), _money(paid))

    @staticmethod
    def get_customer_debt(session: Session, sale: Sale) -> Decimal:
        """Возвращает остаток долга клиента по активному чеку в валюте чека.

        Если чек отменен, неоплаченный долг клиента равен 0.00 (Правило 14).
        """
        if sale.status == "cancelled":
            return Decimal("0.00")
        paid = SalesService.get_sale_paid_amount(session, sale, include_write_off=True)
        total = _money(_decimal(sale.total_amount))
        return max(Decimal("0.00"), _money(total - paid))

    @staticmethod
    def get_store_debt_to_customer(session: Session, sale: Sale) -> Decimal:
        """Возвращает долг магазина перед клиентом по отмененному чеку в валюте чека (Правило 13)."""
        if sale.status != "cancelled":
            return Decimal("0.00")
        paid = SalesService.get_sale_paid_amount(session, sale)
        settlements = session.scalars(
            select(SalePayment).where(
                SalePayment.sale_id == sale.id,
                SalePayment.payment_type.in_(("reversal", "customer_debt_settlement")),
            )
        ).all()
        settled = Decimal("0.00")
        for s in settlements:
            s_rate = _validate_rate(s.exchange_rate or sale.exchange_rate or Decimal("1.0000"))
            settled += _convert_currency(
                _decimal(s.amount),
                s.currency,
                sale.currency,
                s_rate,
            )
        return max(Decimal("0.00"), _money(paid - settled))

    @staticmethod
    def create_sale(
        session: Session,
        items: list[dict],
        payments: list[dict] | None = None,
        currency: str = "TMT",
        exchange_rate: Decimal = Decimal("1.0000"),
        receipt_number: str | None = None,
        note: str | None = None,
        comment: str | None = None,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        allow_credit: bool = False,
        is_simurg: bool = False,
        simurg_payout_date: datetime | None = None,
    ) -> Sale:
        """Создает продажу (чек) с позициями, проверяет склад и IMEI, списывает остатки и принимает оплату."""
        if not isinstance(currency, str):
            raise TypeError("Rugsat edilýän çek walýutalary: USD, TMT.")
        currency = currency.strip().upper()
        if currency not in ("USD", "TMT"):
            raise ValueError("Rugsat edilýän çek walýutalary: USD, TMT.")

        exchange_rate = _validate_rate(exchange_rate)

        if not items:
            raise ValueError("Çek boş bolup bilmez.")

        if is_simurg:
            allow_credit = True

        payments = payments or []
        if not payments and not allow_credit:
            raise ValueError("Iň azyndan bir töleg usulyny görkezmeli.")

        if not receipt_number:
            receipt_number = f"REC-{datetime.now().strftime('%Y%m%d%H%M%S-%f')}"

        if comment is not None:
            comment = str(comment).strip() or None
        if note is not None:
            note = str(note).strip() or None
        if customer_name is not None:
            customer_name = str(customer_name).strip() or None
        if customer_phone is not None:
            customer_phone = str(customer_phone).strip() or None

        sale_dt = datetime.now()
        payout_dt = simurg_payout_date
        if is_simurg and payout_dt is None:
            payout_dt = sale_dt + timedelta(days=5)

        sale = Sale(
            receipt_number=receipt_number,
            sale_date=sale_dt,
            currency=currency,
            exchange_rate=exchange_rate,
            total_amount=Decimal("0.00"),
            customer_name=customer_name,
            customer_phone=customer_phone,
            status="completed",
            note=note,
            comment=comment,
            is_simurg=bool(is_simurg),
            simurg_payout_date=payout_dt,
        )
        session.add(sale)
        session.flush()

        total_sale_amount_doc_curr = Decimal("0.00")
        seen_imeis: set[str] = set()
        requested_quantities: dict[int, int] = {}

        for item_data in items:
            product_id = item_data.get("product_id")
            raw_qty = item_data.get("quantity", 1)
            if isinstance(raw_qty, bool):
                raise TypeError("Haryt sany položitel bitin san bolmaly.")
            qty_dec = _decimal(raw_qty)
            if qty_dec != qty_dec.to_integral_value() or qty_dec <= 0:
                raise ValueError("Haryt sany noldan uly bolmaly.")
            quantity = int(qty_dec)

            unit_price = _money(_decimal(item_data.get("unit_price")))
            discount = _money(_decimal(item_data.get("discount", 0)))
            imei = item_data.get("imei")
            raw_item_curr = item_data.get("currency", currency)
            item_currency = str(raw_item_curr).strip().upper() if raw_item_curr else currency

            if unit_price < 0:
                raise ValueError("Satyş bahasy otrisatel bolup bilmez.")
            if discount < 0:
                raise ValueError("Arzanladyş otrisatel bolup bilmez.")

            product = session.get(Product, product_id)
            if not product:
                raise ValueError(f"ID {product_id} bolan haryt tapylmady.")
            if not product.is_active:
                raise ValueError(f"'{product.name}' harydy öçürilen we satyş üçin elýeterli däl.")

            stock_item_id = None
            stock_item = None

            if imei:
                imei = str(imei).strip()
                if imei in seen_imeis:
                    raise ValueError(f"IMEI {imei} çekde bir gezekden köp görkezildi.")
                seen_imeis.add(imei)

                stock_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == product_id,
                        (StockItem.imei1 == imei) | (StockItem.imei2 == imei),
                    )
                )
                if not stock_item:
                    raise ValueError(f"IMEI {imei} bolan haryt skladda tapylmady.")
                if stock_item.status != "in_stock":
                    raise ValueError(f"IMEI {imei} bolan haryt eýýäm satyldy ýa-da elýeterli däl.")

                if stock_item.imei1:
                    seen_imeis.add(stock_item.imei1)
                if stock_item.imei2:
                    seen_imeis.add(stock_item.imei2)

                stock_item.status = "sold"
                stock_item_id = stock_item.id
                quantity = 1

            requested_quantities[product.id] = requested_quantities.get(product.id, 0) + quantity
            if product.stock_quantity < quantity:
                raise ValueError(
                    f"Skladda '{product.name}' harydy ýeterlik däl "
                    f"(galyndy: {product.stock_quantity}, gerek: {quantity})."
                )

            product.stock_quantity -= quantity

            line_amount_item_curr = _money((unit_price * quantity) - discount)
            if line_amount_item_curr < 0:
                raise ValueError("Arzanladyş hasaba alnanda harydyň jemi otrisatel bolup bilmez.")

            if item_currency == currency:
                line_amount_doc_curr = line_amount_item_curr
            elif item_currency == "TMT" and currency == "USD":
                line_amount_doc_curr = _money(line_amount_item_curr / exchange_rate)
            elif item_currency == "USD" and currency == "TMT":
                line_amount_doc_curr = _money(line_amount_item_curr * exchange_rate)
            else:
                raise ValueError("Harytlaryň we çekiň walýutasy gabat gelmeýär.")

            total_sale_amount_doc_curr += line_amount_doc_curr

            # Определяем историческую себестоимость на момент продажи
            if "unit_cost" in item_data and item_data["unit_cost"] is not None:
                unit_cost = _money(_decimal(item_data["unit_cost"]))
                cost_currency = str(item_data.get("cost_currency", currency)).strip().upper()
                cost_rate = _validate_rate(item_data.get("cost_exchange_rate", exchange_rate))
            else:
                unit_cost, cost_currency, cost_rate = SalesService._resolve_item_cost_basis(
                    session=session,
                    product_id=product.id,
                    stock_item=stock_item,
                    fallback_currency=currency,
                    fallback_rate=exchange_rate,
                )

            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                stock_item_id=stock_item_id,
                imei=imei,
                quantity=quantity,
                unit_price=unit_price,
                discount=discount,
                currency=item_currency,
                unit_cost=unit_cost,
                cost_currency=cost_currency,
                cost_exchange_rate=cost_rate,
                is_exchanged=False,
            )
            session.add(sale_item)

        sale.total_amount = _money(total_sale_amount_doc_curr)

        total_paid_in_sale_curr = Decimal("0.00")

        for payment in payments:
            cash_register_id = payment.get("cash_register_id")
            pay_amount = _money(_decimal(payment.get("amount")))
            raw_pay_curr = payment.get("currency", currency)
            pay_currency = str(raw_pay_curr).strip().upper() if raw_pay_curr else currency
            pay_rate = _validate_rate(payment.get("exchange_rate", exchange_rate))

            if pay_amount <= 0:
                raise ValueError("Töleg mukdary noldan uly bolmaly.")

            if cash_register_id is None:
                regs = SalesService.ensure_default_registers(session)
                if pay_currency not in regs:
                    raise ValueError(f"{pay_currency} walýutasy üçin kassa tapylmady.")
                cash_register_id = regs[pay_currency].id

            CashService.adjust_register_balance(
                session=session,
                cash_register_id=cash_register_id,
                amount=pay_amount,
                transaction_type="income",
                currency=pay_currency,
                exchange_rate=pay_rate,
                description=f"Satyş tölegi {sale.receipt_number}",
                sale_id=sale.id,
            )

            session.add(
                SalePayment(
                    sale_id=sale.id,
                    payment_date=sale.sale_date,
                    currency=pay_currency,
                    amount=pay_amount,
                    exchange_rate=pay_rate,
                    cash_register_id=cash_register_id,
                    payment_type="payment",
                    description=f"Satyş tölegi {sale.receipt_number}",
                )
            )
            session.add(
                CashMovement(
                    movement_date=sale.sale_date,
                    movement_type="sale_payment",
                    currency=pay_currency,
                    amount=pay_amount,
                    exchange_rate=pay_rate,
                    cash_register_id=cash_register_id,
                    sale_id=sale.id,
                    description=f"Satyş tölegi {sale.receipt_number}",
                )
            )

            if pay_currency == currency:
                conv_paid = pay_amount
            elif pay_currency == "TMT" and currency == "USD":
                conv_paid = _money(pay_amount / pay_rate)
            elif pay_currency == "USD" and currency == "TMT":
                conv_paid = _money(pay_amount * pay_rate)
            else:
                raise ValueError("Tölegiň we çekiň walýutasy gabat gelmeýär.")

            total_paid_in_sale_curr += conv_paid

        total_paid_in_sale_curr = _money(total_paid_in_sale_curr)
        if not allow_credit and total_paid_in_sale_curr < sale.total_amount:
            raise ValueError(
                f"Tölenen mukdar ({total_paid_in_sale_curr} {currency}) "
                f"çekiň jeminden ({sale.total_amount} {currency}) az."
            )

        if allow_credit and total_paid_in_sale_curr < sale.total_amount and not customer_name:
            raise ValueError(
                "Bergä (bölekleýin töleg) satylanda müşderiniň adyny görkeziň."
            )

        change_in_sale_curr = _money(total_paid_in_sale_curr - sale.total_amount)
        if change_in_sale_curr > Decimal("0.00"):
            change_register = session.scalar(
                select(CashRegister).where(CashRegister.currency == currency)
            )
            change_reg_id = (
                change_register.id
                if change_register
                else (payments[0].get("cash_register_id") if payments else None)
            )
            if change_reg_id is not None:
                CashService.adjust_register_balance(
                    session=session,
                    cash_register_id=change_reg_id,
                    amount=change_in_sale_curr,
                    transaction_type="expense",
                    currency=currency,
                    exchange_rate=exchange_rate,
                    description=f"Çek boýunça gaýtargy {sale.receipt_number}",
                    sale_id=sale.id,
                )
                session.add(
                    CashMovement(
                        movement_date=sale.sale_date,
                        movement_type="sale_change",
                        currency=currency,
                        amount=change_in_sale_curr,
                        exchange_rate=exchange_rate,
                        cash_register_id=change_reg_id,
                        sale_id=sale.id,
                        description=f"Çek boýunça gaýtargy {sale.receipt_number}",
                    )
                )

        session.flush()
        return sale

    @staticmethod
    def add_sale_payment(
        session: Session,
        sale_id: int,
        currency: str,
        amount: Decimal | float | str,
        exchange_rate: Decimal | float | str,
        cash_register_id: int | None = None,
        payment_date: datetime | None = None,
        description: str | None = None,
    ) -> SalePayment:
        """Регистрирует доплату клиента по чеку с долгом."""
        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"ID {sale_id} bolan satyş tapylmady.")
        if sale.status == "cancelled":
            raise ValueError("Ýatyrylan çek boýunça töleg kabul edip bolmaýar.")

        pay_currency = str(currency).strip().upper()
        if pay_currency not in ("USD", "TMT"):
            raise ValueError("Rugsat edilýän töleg walýutalary: USD, TMT.")

        pay_amount = _money(_decimal(amount))
        if pay_amount <= 0:
            raise ValueError("Töleg mukdary noldan uly bolmaly.")

        pay_rate = _validate_rate(exchange_rate)
        remaining_debt = SalesService.get_customer_debt(session, sale)

        conv_amount = _convert_currency(pay_amount, pay_currency, sale.currency, pay_rate)
        if conv_amount > remaining_debt:
            raise ValueError(
                f"Töleg mukdary ({conv_amount} {sale.currency}) çek boýunça galan bergiden "
                f"({remaining_debt} {sale.currency}) köp."
            )

        if cash_register_id is None:
            regs = SalesService.ensure_default_registers(session)
            if pay_currency not in regs:
                raise ValueError(f"{pay_currency} walýutasy üçin kassa tapylmady.")
            cash_register_id = regs[pay_currency].id

        payment_date = payment_date or datetime.now()
        desc = (description or "").strip() or f"Çek boýunça bergini ýapmak {sale.receipt_number}"

        CashService.adjust_register_balance(
            session=session,
            cash_register_id=cash_register_id,
            amount=pay_amount,
            transaction_type="income",
            currency=pay_currency,
            exchange_rate=pay_rate,
            description=desc,
            sale_id=sale.id,
        )

        sale_payment = SalePayment(
            sale_id=sale.id,
            payment_date=payment_date,
            currency=pay_currency,
            amount=pay_amount,
            exchange_rate=pay_rate,
            cash_register_id=cash_register_id,
            payment_type="payment",
            description=desc,
        )
        session.add(sale_payment)
        session.add(
            CashMovement(
                movement_date=payment_date,
                movement_type="customer_debt_payment",
                currency=pay_currency,
                amount=pay_amount,
                exchange_rate=pay_rate,
                cash_register_id=cash_register_id,
                sale_id=sale.id,
                description=desc,
            )
        )
        session.flush()
        return sale_payment

    @staticmethod
    def settle_store_debt_to_customer(
        session: Session,
        sale_id: int,
        currency: str,
        amount: Decimal | float | str,
        exchange_rate: Decimal | float | str,
        cash_register_id: int | None = None,
        settlement_date: datetime | None = None,
        description: str | None = None,
    ) -> SalePayment:
        """Погашает задолженность магазина перед клиентом по отмененному чеку."""
        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"ID {sale_id} bolan satyş tapylmady.")
        if sale.status != "cancelled":
            raise ValueError("Dükanyň bergisini diňe ýatyrylan çek boýunça ýapyp bolýar.")

        pay_currency = str(currency).strip().upper()
        if pay_currency not in ("USD", "TMT"):
            raise ValueError("Rugsat edilýän walýutalar: USD, TMT.")

        pay_amount = _money(_decimal(amount))
        if pay_amount <= 0:
            raise ValueError("Tölenýän mukdar noldan uly bolmaly.")

        pay_rate = _validate_rate(exchange_rate)
        remaining_debt = SalesService.get_store_debt_to_customer(session, sale)

        conv_amount = _convert_currency(pay_amount, pay_currency, sale.currency, pay_rate)
        if conv_amount > remaining_debt:
            raise ValueError(
                f"Tölenýän mukdar ({conv_amount} {sale.currency}) dükanyň müşderä bolan bergisinden "
                f"({remaining_debt} {sale.currency}) köp."
            )

        if cash_register_id is None:
            regs = SalesService.ensure_default_registers(session)
            if pay_currency not in regs:
                raise ValueError(f"{pay_currency} walýutasy üçin kassa tapylmady.")
            cash_register_id = regs[pay_currency].id

        settlement_date = settlement_date or datetime.now()
        desc = (description or "").strip() or (
            f"Ýatyrylan çek {sale.receipt_number} boýunça müşderä bergi tölegi"
        )

        CashService.adjust_register_balance(
            session=session,
            cash_register_id=cash_register_id,
            amount=pay_amount,
            transaction_type="refund",
            currency=pay_currency,
            exchange_rate=pay_rate,
            description=desc,
            sale_id=sale.id,
        )

        settlement = SalePayment(
            sale_id=sale.id,
            payment_date=settlement_date,
            currency=pay_currency,
            amount=pay_amount,
            exchange_rate=pay_rate,
            cash_register_id=cash_register_id,
            payment_type="customer_debt_settlement",
            description=desc,
        )
        session.add(settlement)
        session.add(
            CashMovement(
                movement_date=settlement_date,
                movement_type="sale_refund",
                currency=pay_currency,
                amount=pay_amount,
                exchange_rate=pay_rate,
                cash_register_id=cash_register_id,
                sale_id=sale.id,
                description=desc,
            )
        )
        session.flush()
        return settlement

    @staticmethod
    def cancel_sale(
        session: Session,
        sale_id: int,
        reason: str,
        refund_cash_register_id: int | None = None,
        refund_to_cash: bool = True,
    ) -> Sale:
        """Аудит-совместимая отмена продажи, возврат товара на склад и точный возврат денег из кассы."""
        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"ID {sale_id} bolan satyş tapylmady.")

        if sale.status == "cancelled":
            raise ValueError("Satyş eýýäm ýatyryldy.")

        reason = str(reason).strip() if reason is not None else ""
        if not reason:
            raise ValueError("Satyşy ýatyrmagyň sebäbini görkeziň.")
        if len(reason) > 255:
            raise ValueError("Ýatyrma sebäbi 255 nyşandan köp bolmaly däl.")

        sale_items = session.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id)
        ).all()

        for item in sale_items:
            if item.is_exchanged:
                raise ValueError(
                    "Enjam çalyşygy edilen çeki ýatyryp bolmaýar."
                )

        now = datetime.now()
        sale.status = "cancelled"
        sale.cancellation_reason = reason
        sale.cancelled_at = now

        for item in sale_items:
            product = session.get(Product, item.product_id)
            if product:
                product.stock_quantity += item.quantity

            if item.stock_item_id:
                stock_item = session.get(StockItem, item.stock_item_id)
                if stock_item:
                    stock_item.status = "in_stock"
            elif item.imei:
                stock_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == item.product_id,
                        (StockItem.imei1 == item.imei) | (StockItem.imei2 == item.imei),
                    )
                )
                if stock_item:
                    stock_item.status = "in_stock"

        all_sale_txs = session.scalars(
            select(CashTransaction).where(CashTransaction.sale_id == sale.id)
        ).all()
        income_txs = [tx for tx in all_sale_txs if tx.transaction_type == "income"]

        refund_rate = _validate_rate(sale.exchange_rate or Decimal("1.0000"))
        if refund_rate == Decimal("1.0000"):
            for tx in income_txs:
                tx_rate = Decimal(str(tx.exchange_rate or 0))
                if tx_rate != Decimal("1.0000") and tx_rate > 0:
                    refund_rate = tx_rate
                    break

        desc = f"Çek boýunça yzyna gaýtarma {sale.receipt_number}: {reason}"[:255]

        if refund_cash_register_id is not None:
            register = session.get(CashRegister, refund_cash_register_id)
            if not register:
                raise ValueError(f"ID {refund_cash_register_id} bolan kassa tapylmady.")

            paid_in_sale_curr = SalesService.get_sale_paid_amount(
                session, sale, include_write_off=False
            )
            if paid_in_sale_curr > Decimal("0.00"):
                CashService.adjust_register_balance(
                    session=session,
                    cash_register_id=refund_cash_register_id,
                    amount=paid_in_sale_curr,
                    transaction_type="refund",
                    currency=sale.currency,
                    exchange_rate=refund_rate,
                    description=desc,
                    sale_id=sale.id,
                )
                session.add(
                    SalePayment(
                        sale_id=sale.id,
                        payment_date=now,
                        currency=sale.currency,
                        amount=paid_in_sale_curr,
                        exchange_rate=refund_rate,
                        cash_register_id=refund_cash_register_id,
                        payment_type="reversal",
                        description=desc,
                    )
                )
                session.add(
                    CashMovement(
                        movement_date=now,
                        movement_type="sale_refund",
                        currency=sale.currency,
                        amount=paid_in_sale_curr,
                        exchange_rate=refund_rate,
                        cash_register_id=refund_cash_register_id,
                        sale_id=sale.id,
                        description=desc,
                    )
                )
        elif refund_to_cash:
            # Считаем фактический чистый приход в разрезе каждой конкретной кассы (USD / TMT),
            # чтобы при отмене (в том числе со сдачей или смешанной оплатой) вернуть ровно те же суммы.
            net_by_reg: dict[int, Decimal] = {}
            reg_cache: dict[int, CashRegister] = {}
            for tx in all_sale_txs:
                reg = reg_cache.get(tx.cash_register_id)
                if reg is None:
                    reg = session.get(CashRegister, tx.cash_register_id)
                    if reg is None:
                        continue
                    reg_cache[tx.cash_register_id] = reg

                tx_rate = _validate_rate(tx.exchange_rate or refund_rate)
                tx_in_reg_curr = _convert_currency(
                    _decimal(tx.amount),
                    tx.currency,
                    reg.currency,
                    tx_rate,
                )
                prev = net_by_reg.get(reg.id, Decimal("0.00"))
                if tx.transaction_type == "income":
                    net_by_reg[reg.id] = _money(prev + tx_in_reg_curr)
                elif tx.transaction_type in ("expense", "refund"):
                    net_by_reg[reg.id] = _money(prev - tx_in_reg_curr)

            for reg_id, net_amt in net_by_reg.items():
                if net_amt <= Decimal("0.00"):
                    continue
                reg = reg_cache[reg_id]
                CashService.adjust_register_balance(
                    session=session,
                    cash_register_id=reg.id,
                    amount=net_amt,
                    transaction_type="refund",
                    currency=reg.currency,
                    exchange_rate=refund_rate,
                    description=desc,
                    sale_id=sale.id,
                )
                session.add(
                    SalePayment(
                        sale_id=sale.id,
                        payment_date=now,
                        currency=reg.currency,
                        amount=net_amt,
                        exchange_rate=refund_rate,
                        cash_register_id=reg.id,
                        payment_type="reversal",
                        description=desc,
                    )
                )
                session.add(
                    CashMovement(
                        movement_date=now,
                        movement_type="sale_refund",
                        currency=reg.currency,
                        amount=net_amt,
                        exchange_rate=refund_rate,
                        cash_register_id=reg.id,
                        sale_id=sale.id,
                        description=desc,
                    )
                )

        session.flush()
        return sale


