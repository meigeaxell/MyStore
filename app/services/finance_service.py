from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_movement import CashMovement
from app.models.cash_register import CashRegister
from app.models.expense import Expense
from app.models.purchase import Purchase
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund
from app.models.sale import Sale
from app.services.cash_service import CashService, _decimal, _money, _validate_rate
from app.services.purchase_service import (
    PERSONAL_SOURCE_LABEL,
    _get_supplier_debt_amount,
    is_personal_source_purchase,
)
from app.services.purchase_service import (
    _get_paid_amount as _get_purchase_paid_amount,
)
from app.services.purchase_service import (
    _get_refunded_amount as _get_purchase_refunded_amount,
)
from app.services.sales_service import SalesService


class FinanceService:
    """Сервис финансового управления: балансы касс, задолженности, журнал транзакций, расходы и корректировки."""

    @staticmethod
    def get_register_balances(session: Session) -> dict:
        """Возвращает текущие балансы по каждой кассе и отдельно итоги по валютам USD и TMT."""
        SalesService.ensure_default_registers(session)
        registers = session.scalars(
            select(CashRegister).order_by(CashRegister.currency, CashRegister.id)
        ).all()

        usd_total = Decimal("0.00")
        tmt_total = Decimal("0.00")
        reg_list = []

        for reg in registers:
            bal = _money(_decimal(reg.balance))
            cur = reg.currency.strip().upper()
            if cur == "USD":
                usd_total += bal
            elif cur == "TMT":
                tmt_total += bal
            reg_list.append({
                "id": reg.id,
                "name": reg.name,
                "currency": cur,
                "balance": bal,
            })

        return {
            "usd_balance": _money(usd_total),
            "tmt_balance": _money(tmt_total),
            "registers": reg_list,
        }

    @staticmethod
    def get_period_cash_summary(
        session: Session,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """Рассчитывает приход, расход и чистый денежный поток отдельно для USD и TMT за выбранный период."""
        stmt = select(CashMovement)
        if date_from is not None:
            stmt = stmt.where(CashMovement.movement_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(CashMovement.movement_date <= date_to)

        movements = session.scalars(stmt).all()

        inflow_types = {
            "sale_payment",
            "customer_debt_payment",
            "purchase_refund",
            "exchange_payment",
            "manual_income",
            "correction_income",
        }
        outflow_types = {
            "purchase_payment",
            "sale_change",
            "sale_refund",
            "expense",
            "manual_expense",
            "correction_expense",
        }

        summary = {
            "USD": {
                "income": Decimal("0.00"),
                "expense": Decimal("0.00"),
                "net": Decimal("0.00"),
            },
            "TMT": {
                "income": Decimal("0.00"),
                "expense": Decimal("0.00"),
                "net": Decimal("0.00"),
            },
        }

        for m in movements:
            cur = m.currency.strip().upper()
            if cur not in summary:
                continue
            amt = _money(_decimal(m.amount))
            if m.movement_type in inflow_types:
                summary[cur]["income"] = _money(summary[cur]["income"] + amt)
            elif m.movement_type in outflow_types:
                summary[cur]["expense"] = _money(summary[cur]["expense"] + amt)

        for cur in ("USD", "TMT"):
            summary[cur]["net"] = _money(summary[cur]["income"] - summary[cur]["expense"])

        return summary

    @staticmethod
    def get_all_outstanding_balances(session: Session) -> dict:
        """Рассчитывает 4 отдельные категории задолженностей отдельно в USD и TMT:
        1. Долги клиентов перед магазином (customer_debts).
        2. Долги магазина перед поставщиками (supplier_payables).
        3. Долги магазина перед клиентами по отмененным чекам (store_debts_to_customers).
        4. Долги поставщиков перед магазином по отмененным закупкам (supplier_debts_to_store).
        """
        result = {
            "customer_debts": {"USD": Decimal("0.00"), "TMT": Decimal("0.00")},
            "supplier_payables": {"USD": Decimal("0.00"), "TMT": Decimal("0.00")},
            "store_debts_to_customers": {"USD": Decimal("0.00"), "TMT": Decimal("0.00")},
            "supplier_debts_to_store": {"USD": Decimal("0.00"), "TMT": Decimal("0.00")},
        }

        sales = session.scalars(select(Sale)).all()
        for sale in sales:
            cur = sale.currency.strip().upper()
            if cur not in ("USD", "TMT"):
                continue
            if sale.status == "cancelled":
                s_debt = SalesService.get_store_debt_to_customer(session, sale)
                if s_debt > 0:
                    result["store_debts_to_customers"][cur] = _money(
                        result["store_debts_to_customers"][cur] + s_debt
                    )
            else:
                c_debt = SalesService.get_customer_debt(session, sale)
                if c_debt > 0:
                    result["customer_debts"][cur] = _money(
                        result["customer_debts"][cur] + c_debt
                    )

        purchases = session.scalars(select(Purchase)).all()
        for purchase in purchases:
            if is_personal_source_purchase(purchase):
                continue
            cur = purchase.currency.strip().upper()
            if cur not in ("USD", "TMT"):
                continue
            if purchase.status == "cancelled":
                sup_debt = _get_supplier_debt_amount(session, purchase)
                if sup_debt > 0:
                    result["supplier_debts_to_store"][cur] = _money(
                        result["supplier_debts_to_store"][cur] + sup_debt
                    )
            else:
                paid = _get_purchase_paid_amount(session, purchase)
                rem = max(
                    Decimal("0.00"),
                    _money(_decimal(purchase.total_amount) - paid),
                )
                if rem > 0:
                    result["supplier_payables"][cur] = _money(
                        result["supplier_payables"][cur] + rem
                    )

        return result

    @staticmethod
    def get_customer_receivables_list(
        session: Session,
        include_paid: bool = False,
    ) -> list[dict]:
        """Возвращает список чеков с задолженностью клиентов и чеков, где магазин должен клиенту."""
        sales = session.scalars(select(Sale).order_by(Sale.sale_date.desc())).all()
        rows = []
        for sale in sales:
            paid = SalesService.get_sale_paid_amount(session, sale)
            total = _money(_decimal(sale.total_amount))

            if sale.status == "cancelled":
                store_debt = SalesService.get_store_debt_to_customer(session, sale)
                if store_debt <= 0 and not include_paid:
                    continue
                rows.append({
                    "sale_id": sale.id,
                    "receipt_number": sale.receipt_number,
                    "sale_date": sale.sale_date,
                    "customer_name": sale.customer_name or "Bölek müşderi",
                    "customer_phone": sale.customer_phone or "",
                    "currency": sale.currency,
                    "exchange_rate": _validate_rate(sale.exchange_rate or Decimal("1.0000")),
                    "original_amount": total,
                    "paid_amount": paid,
                    "remaining_customer_debt": Decimal("0.00"),
                    "store_debt_to_customer": store_debt,
                    "debt_category": "store_owes_customer",
                    "status_label": (
                        "Dükanyň müşderä bergisi"
                        if store_debt > 0
                        else "Ýatyryldy (hasaplaşyk ýapyldy)"
                    ),
                })
            else:
                cust_debt = SalesService.get_customer_debt(session, sale)
                if cust_debt <= 0 and not include_paid:
                    continue
                rows.append({
                    "sale_id": sale.id,
                    "receipt_number": sale.receipt_number,
                    "sale_date": sale.sale_date,
                    "customer_name": sale.customer_name or "Bölek müşderi",
                    "customer_phone": sale.customer_phone or "",
                    "currency": sale.currency,
                    "exchange_rate": _validate_rate(sale.exchange_rate or Decimal("1.0000")),
                    "original_amount": total,
                    "paid_amount": paid,
                    "remaining_customer_debt": cust_debt,
                    "store_debt_to_customer": Decimal("0.00"),
                    "debt_category": "customer_owes_store",
                    "status_label": (
                        "Müşderiniň bergisi"
                        if cust_debt > 0
                        else "Tölendi"
                    ),
                })
        return rows

    @staticmethod
    def get_supplier_payables_list(
        session: Session,
        include_paid: bool = False,
    ) -> list[dict]:
        """Возвращает список закупок с долгом магазина поставщику или долгом поставщика магазину."""
        purchases = session.scalars(
            select(Purchase).order_by(Purchase.purchase_date.desc())
        ).all()
        rows = []
        for purchase in purchases:
            total = _money(_decimal(purchase.total_amount))
            paid = _get_purchase_paid_amount(session, purchase)
            refunded = _get_purchase_refunded_amount(session, purchase)
            is_personal = is_personal_source_purchase(purchase)
            sup_label = (purchase.supplier_name or "").strip() or PERSONAL_SOURCE_LABEL

            if is_personal:
                if not include_paid:
                    continue
                rows.append({
                    "purchase_id": purchase.id,
                    "purchase_date": purchase.purchase_date,
                    "supplier_name": sup_label,
                    "currency": purchase.currency,
                    "exchange_rate": _validate_rate(purchase.exchange_rate),
                    "original_amount": total,
                    "paid_amount": paid,
                    "refunded_amount": refunded,
                    "store_debt_to_supplier": Decimal("0.00"),
                    "supplier_debt_to_store": Decimal("0.00"),
                    "debt_category": "personal_source",
                    "status_label": (
                        "Şahsy çeşme (ýatyryldy)"
                        if purchase.status == "cancelled"
                        else "Şahsy çeşme (bergisiz)"
                    ),
                })
                continue

            if purchase.status == "cancelled":
                supplier_debt = _get_supplier_debt_amount(session, purchase)
                if supplier_debt <= 0 and not include_paid:
                    continue
                rows.append({
                    "purchase_id": purchase.id,
                    "purchase_date": purchase.purchase_date,
                    "supplier_name": sup_label,
                    "currency": purchase.currency,
                    "exchange_rate": _validate_rate(purchase.exchange_rate),
                    "original_amount": total,
                    "paid_amount": paid,
                    "refunded_amount": refunded,
                    "store_debt_to_supplier": Decimal("0.00"),
                    "supplier_debt_to_store": supplier_debt,
                    "debt_category": "supplier_owes_store",
                    "status_label": (
                        "Üpjün edijiniň dükana bergisi"
                        if supplier_debt > 0
                        else "Ýatyryldy (gaýtarma ýapyldy)"
                    ),
                })
            else:
                store_debt = max(Decimal("0.00"), _money(total - paid))
                if store_debt <= 0 and not include_paid:
                    continue
                rows.append({
                    "purchase_id": purchase.id,
                    "purchase_date": purchase.purchase_date,
                    "supplier_name": sup_label,
                    "currency": purchase.currency,
                    "exchange_rate": _validate_rate(purchase.exchange_rate),
                    "original_amount": total,
                    "paid_amount": paid,
                    "refunded_amount": refunded,
                    "store_debt_to_supplier": store_debt,
                    "supplier_debt_to_store": Decimal("0.00"),
                    "debt_category": "store_owes_supplier",
                    "status_label": (
                        "Dükanyň üpjün edijä bergisi"
                        if store_debt > 0
                        else "Tölendi"
                    ),
                })
        return rows

    @staticmethod
    def get_financial_journal(
        session: Session,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        currency: str | None = None,
        movement_type: str | None = None,
        search_query: str | None = None,
    ) -> list[dict]:
        """Возвращает полный финансовый журнал транзакций с фильтрацией и привязкой к документам."""
        stmt = select(CashMovement).order_by(
            CashMovement.movement_date.desc(), CashMovement.id.desc()
        )
        if date_from is not None:
            stmt = stmt.where(CashMovement.movement_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(CashMovement.movement_date <= date_to)
        if currency and currency in ("USD", "TMT"):
            stmt = stmt.where(CashMovement.currency == currency)
        if movement_type:
            stmt = stmt.where(CashMovement.movement_type == movement_type)

        movements = session.scalars(stmt).all()

        # Предзагружаем связанные документы
        sale_ids = {m.sale_id for m in movements if m.sale_id is not None}
        sales_map: dict[int, Sale] = {}
        if sale_ids:
            for s in session.scalars(select(Sale).where(Sale.id.in_(sale_ids))).all():
                sales_map[s.id] = s

        pp_ids = {m.purchase_payment_id for m in movements if m.purchase_payment_id is not None}
        pp_map: dict[int, PurchasePayment] = {}
        if pp_ids:
            for pp in session.scalars(
                select(PurchasePayment).where(PurchasePayment.id.in_(pp_ids))
            ).all():
                pp_map[pp.id] = pp

        pr_ids = {m.purchase_refund_id for m in movements if m.purchase_refund_id is not None}
        pr_map: dict[int, PurchaseRefund] = {}
        if pr_ids:
            for pr in session.scalars(
                select(PurchaseRefund).where(PurchaseRefund.id.in_(pr_ids))
            ).all():
                pr_map[pr.id] = pr

        inflow_types = {
            "sale_payment": ("Satyş tölegi", "Girdeji (+)", "Satyşlar"),
            "customer_debt_payment": ("Müşderiniň bergi tölegi", "Girdeji (+)", "Müşderi bergileri"),
            "purchase_refund": ("Üpjün edijiden yzyna gaýtarma", "Girdeji (+)", "Alyşlar"),
            "exchange_payment": ("Çalyşyk goşmaça tölegi (Trade-in)", "Girdeji (+)", "Enjam çalyşygy"),
            "manual_income": ("Kassa girizmek", "Girdeji (+)", "Kassa"),
            "correction_income": ("Düzediş (girdeji)", "Girdeji (+)", "Düzediş"),
        }
        outflow_types = {
            "purchase_payment": ("Üpjün edijä töleg", "Çykdajy (−)", "Alyşlar"),
            "sale_change": ("Müşderä gaýtargy", "Çykdajy (−)", "Satyşlar"),
            "sale_refund": ("Çek ýatyrmada yzyna gaýtarma", "Çykdajy (−)", "Satyş ýatyrma"),
            "expense": ("Operasion çykdajy", "Çykdajy (−)", "Çykdajylar"),
            "manual_expense": ("Kassadan çykarmak", "Çykdajy (−)", "Kassa"),
            "correction_expense": ("Düzediş (çykdajy)", "Çykdajy (−)", "Düzediş"),
        }

        journal = []
        q = (search_query or "").strip().lower()

        for m in movements:
            if m.movement_type in inflow_types:
                type_label, direction, source = inflow_types[m.movement_type]
                is_inflow = True
            elif m.movement_type in outflow_types:
                type_label, direction, source = outflow_types[m.movement_type]
                is_inflow = False
            else:
                type_label = m.movement_type
                direction = "Hereket"
                source = "Maliýe"
                is_inflow = True

            doc_type = None
            doc_id = None
            doc_label = "—"
            rate = _validate_rate(m.exchange_rate or Decimal("1.0000"))

            if m.sale_id and m.sale_id in sales_map:
                sale = sales_map[m.sale_id]
                doc_type = "sale"
                doc_id = sale.id
                doc_label = f"Çek {sale.receipt_number}"
                if rate == Decimal("1.0000") and sale.exchange_rate:
                    rate = _validate_rate(sale.exchange_rate)
            elif m.purchase_payment_id and m.purchase_payment_id in pp_map:
                pp = pp_map[m.purchase_payment_id]
                doc_type = "purchase"
                doc_id = pp.purchase_id
                doc_label = f"Alyş №{pp.purchase_id}"
                rate = _validate_rate(pp.exchange_rate)
            elif m.purchase_refund_id and m.purchase_refund_id in pr_map:
                pr = pr_map[m.purchase_refund_id]
                doc_type = "purchase"
                doc_id = pr.purchase_id
                doc_label = f"Alyş №{pr.purchase_id}"
                rate = _validate_rate(pr.exchange_rate)

            entry = {
                "id": m.id,
                "date": m.movement_date,
                "movement_type": m.movement_type,
                "type_label": type_label,
                "direction": direction,
                "is_inflow": is_inflow,
                "amount": _money(_decimal(m.amount)),
                "currency": m.currency.strip().upper(),
                "exchange_rate": rate,
                "source": source,
                "doc_type": doc_type,
                "doc_id": doc_id,
                "doc_label": doc_label,
                "description": m.description or "",
            }

            if q:
                haystack = " ".join([
                    str(entry["id"]),
                    entry["type_label"],
                    entry["doc_label"],
                    entry["description"],
                    entry["source"],
                ]).lower()
                if q not in haystack:
                    continue

            journal.append(entry)

        return journal

    @staticmethod
    def record_expense(
        session: Session,
        category: str,
        amount: Decimal | float | str,
        currency: str,
        exchange_rate: Decimal | float | str,
        description: str | None = None,
        expense_date: datetime | None = None,
    ) -> Expense:
        """Регистрирует операционный расход магазина, списывает средства из кассы и пишет в журнал."""
        category = (category or "").strip()
        if not category:
            raise ValueError("Çykdajy kategoriýasyny görkeziň.")
        if len(category) > 100:
            raise ValueError("Çykdajy kategoriýasy 100 simwoldan uzyn bolmaly däl.")

        curr = (currency or "").strip().upper()
        if curr not in ("USD", "TMT"):
            raise ValueError("Rugsat berlen walýutalar: USD, TMT.")

        amt = _money(_decimal(amount))
        if amt <= 0:
            raise ValueError("Çykdajy mukdary noldan uly bolmaly.")

        rate = _validate_rate(exchange_rate)
        desc = (description or "").strip() or f"Çykdajy: {category}"
        if len(desc) > 255:
            raise ValueError("Düşündiriş 255 simwoldan uzyn bolmaly däl.")

        expense_date = expense_date or datetime.now()
        regs = SalesService.ensure_default_registers(session)
        register = regs[curr]

        CashService.adjust_register_balance(
            session=session,
            cash_register_id=register.id,
            amount=amt,
            transaction_type="expense",
            currency=curr,
            exchange_rate=rate,
            description=desc,
        )

        expense = Expense(
            expense_date=expense_date,
            category=category,
            amount=amt,
            currency=curr,
            exchange_rate=rate,
            description=desc,
        )
        session.add(expense)
        session.add(
            CashMovement(
                movement_date=expense_date,
                movement_type="expense",
                currency=curr,
                amount=amt,
                exchange_rate=rate,
                cash_register_id=register.id,
                description=f"[{category}] {desc}",
            )
        )
        session.flush()
        return expense

    @staticmethod
    def record_cash_adjustment(
        session: Session,
        direction: str,
        amount: Decimal | float | str,
        currency: str,
        exchange_rate: Decimal | float | str,
        reason: str,
        reference_movement_id: int | None = None,
    ) -> CashMovement:
        """Создает корректирующую или сторнирующую запись с обязательной причиной (Раздел 5.7).

        Исходные транзакции никогда не удаляются и не редактируются.
        """
        if direction not in ("income", "expense"):
            raise ValueError("Düzediş ugry 'income' ýa-da 'expense' bolmaly.")

        curr = (currency or "").strip().upper()
        if curr not in ("USD", "TMT"):
            raise ValueError("Rugsat berlen walýutalar: USD, TMT.")

        amt = _money(_decimal(amount))
        if amt <= 0:
            raise ValueError("Düzediş mukdary noldan uly bolmaly.")

        rate = _validate_rate(exchange_rate)
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Maliýe düzedişiniň sebäbini görkeziň.")

        prefix = (
            f"Amal #{reference_movement_id} storno/düzediş: "
            if reference_movement_id
            else "Kassa düzedişi: "
        )
        full_desc = (prefix + reason)[:255]

        regs = SalesService.ensure_default_registers(session)
        register = regs[curr]

        tx_type = "income" if direction == "income" else "expense"
        mov_type = "correction_income" if direction == "income" else "correction_expense"

        CashService.adjust_register_balance(
            session=session,
            cash_register_id=register.id,
            amount=amt,
            transaction_type=tx_type,
            currency=curr,
            exchange_rate=rate,
            description=full_desc,
        )

        movement = CashMovement(
            movement_date=datetime.now(),
            movement_type=mov_type,
            currency=curr,
            amount=amt,
            exchange_rate=rate,
            cash_register_id=register.id,
            description=full_desc,
        )
        session.add(movement)
        session.flush()
        return movement

    @staticmethod
    def get_combined_cash_totals(
        session: Session,
        exchange_rate: Decimal | float | str,
    ) -> dict:
        """Рассчитывает общую сумму всей кассы (USD + TMT) в обеих валютах по курсу."""
        rate = _validate_rate(exchange_rate)
        balances = FinanceService.get_register_balances(session)
        usd_bal = balances["usd_balance"]
        tmt_bal = balances["tmt_balance"]
        total_in_tmt = _money(tmt_bal + (usd_bal * rate))
        total_in_usd = _money(usd_bal + (tmt_bal / rate))
        return {
            "usd_balance": usd_bal,
            "tmt_balance": tmt_bal,
            "exchange_rate": rate,
            "total_in_tmt": total_in_tmt,
            "total_in_usd": total_in_usd,
        }

    @staticmethod
    def zero_cash_register(
        session: Session,
        currency: str,
        exchange_rate: Decimal | float | str,
        reason: str = "Kassany nollamak / Pul almak",
    ) -> Decimal:
        """Обнуляет баланс указанной кассы (USD или TMT) с обязательной записью в журнал."""
        curr = (currency or "").strip().upper()
        if curr not in ("USD", "TMT"):
            raise ValueError("Rugsat berlen walýutalar: USD, TMT.")
        rate = _validate_rate(exchange_rate)
        clean_reason = (reason or "").strip() or "Kassany nollamak"

        regs = SalesService.ensure_default_registers(session)
        register = regs[curr]
        bal = _money(_decimal(register.balance))
        if bal == Decimal("0.00"):
            return Decimal("0.00")

        direction = "expense" if bal > Decimal("0.00") else "income"
        amt = abs(bal)
        FinanceService.record_cash_adjustment(
            session=session,
            direction=direction,
            amount=amt,
            currency=curr,
            exchange_rate=rate,
            reason=clean_reason,
        )
        return amt

    @staticmethod
    def settle_or_zero_customer_debt(
        session: Session,
        sale_id: int,
        with_cash: bool = True,
        exchange_rate: Decimal | float | str | None = None,
        reason: str | None = None,
    ) -> Decimal:
        """Полностью закрывает долг клиента по чеку: через кассу (with_cash=True) или списанием (with_cash=False)."""
        from app.models.sale_payment import SalePayment

        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"ID {sale_id} bolan satyş tapylmady.")
        if sale.status == "cancelled":
            raise ValueError("Ýatyrylan çekde müşderi bergisi ýok.")

        debt = SalesService.get_customer_debt(session, sale)
        if debt <= Decimal("0.00"):
            raise ValueError("Bu çek boýunça açyk bergi ýok.")

        rate = _validate_rate(exchange_rate or sale.exchange_rate or Decimal("19.5000"))
        if with_cash:
            desc = (reason or "").strip() or f"Bergini doly ýapmak ({sale.receipt_number})"
            SalesService.add_sale_payment(
                session=session,
                sale_id=sale.id,
                currency=sale.currency,
                amount=debt,
                exchange_rate=rate,
                description=desc,
            )
            return debt

        desc = (reason or "").strip() or f"Bergini nollamak / hasapdan öçürmek ({sale.receipt_number})"
        session.add(
            SalePayment(
                sale_id=sale.id,
                payment_date=datetime.now(),
                currency=sale.currency,
                amount=debt,
                exchange_rate=rate,
                cash_register_id=None,
                payment_type="write_off",
                description=desc[:255],
            )
        )
        session.flush()
        return debt

    @staticmethod
    def settle_or_zero_store_debt_to_customer(
        session: Session,
        sale_id: int,
        with_cash: bool = True,
        exchange_rate: Decimal | float | str | None = None,
        reason: str | None = None,
    ) -> Decimal:
        """Полностью закрывает долг магазина перед клиентом по отменённому чеку (с кассой или обнулением)."""
        from app.models.sale_payment import SalePayment

        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"ID {sale_id} bolan satyş tapylmady.")
        if sale.status != "cancelled":
            raise ValueError("Dükanyň müşderä bergisi diňe ýatyrylan çekde bolýar.")

        debt = SalesService.get_store_debt_to_customer(session, sale)
        if debt <= Decimal("0.00"):
            raise ValueError("Bu çek boýunça dükanyň açyk bergisi ýok.")

        rate = _validate_rate(exchange_rate or sale.exchange_rate or Decimal("19.5000"))
        if with_cash:
            desc = (reason or "").strip() or f"Müşderä bergini doly gaýtarmak ({sale.receipt_number})"
            SalesService.settle_store_debt_to_customer(
                session=session,
                sale_id=sale.id,
                currency=sale.currency,
                amount=debt,
                exchange_rate=rate,
                description=desc,
            )
            return debt

        desc = (reason or "").strip() or f"Dükanyň bergisini nollamak ({sale.receipt_number})"
        session.add(
            SalePayment(
                sale_id=sale.id,
                payment_date=datetime.now(),
                currency=sale.currency,
                amount=debt,
                exchange_rate=rate,
                cash_register_id=None,
                payment_type="customer_debt_settlement",
                description=desc[:255],
            )
        )
        session.flush()
        return debt

    @staticmethod
    def settle_or_zero_supplier_debt(
        session: Session,
        purchase_id: int,
        with_cash: bool = True,
        exchange_rate: Decimal | float | str | None = None,
        reason: str | None = None,
    ) -> Decimal:
        """Закрывает долг магазина перед поставщиком (с оплатой из кассы или списанием без кассы)."""
        from app.services.purchase_service import _register_payment

        purchase = session.get(Purchase, purchase_id)
        if not purchase:
            raise ValueError("Alyş tapylmady.")
        if purchase.status != "active":
            raise ValueError("Ýatyrylan alyşda üpjün edijä bergi ýok.")

        paid = _get_purchase_paid_amount(session, purchase)
        remaining = max(Decimal("0.00"), _money(_decimal(purchase.total_amount) - paid))
        if remaining <= Decimal("0.00"):
            raise ValueError("Bu alyş boýunça açyk bergi ýok.")

        rate = _validate_rate(exchange_rate or purchase.exchange_rate or Decimal("19.5000"))
        if with_cash:
            _register_payment(
                session=session,
                purchase=purchase,
                currency=purchase.currency,
                amount=remaining,
                exchange_rate=rate,
            )
            return remaining

        session.add(
            PurchasePayment(
                purchase_id=purchase.id,
                payment_date=datetime.now(),
                currency=purchase.currency,
                amount=remaining,
                exchange_rate=rate,
            )
        )
        session.flush()
        return remaining

    @staticmethod
    def settle_or_zero_supplier_refund_debt(
        session: Session,
        purchase_id: int,
        with_cash: bool = True,
        exchange_rate: Decimal | float | str | None = None,
        reason: str | None = None,
    ) -> Decimal:
        """Закрывает долг поставщика перед магазином по отменённой закупке (возврат в кассу или обнуление)."""
        from app.models.cash_register import CashTransaction

        purchase = session.get(Purchase, purchase_id)
        if not purchase:
            raise ValueError("Alyş tapylmady.")
        if purchase.status != "cancelled":
            raise ValueError("Üpjün edijiniň bergisi diňe ýatyrylan alyşda bolýar.")

        debt = _get_supplier_debt_amount(session, purchase)
        if debt <= Decimal("0.00"):
            raise ValueError("Üpjün edijiniň açyk bergisi ýok.")

        rate = _validate_rate(exchange_rate or purchase.exchange_rate or Decimal("19.5000"))
        now = datetime.now()
        desc = (reason or "").strip() or (
            f"Alyş №{purchase.id} boýunça üpjün edijiden doly gaýtarma"
            if with_cash
            else f"Alyş №{purchase.id} boýunça üpjün ediji bergisini nollamak"
        )

        refund = PurchaseRefund(
            purchase_id=purchase.id,
            refund_date=now,
            currency=purchase.currency,
            amount=debt,
            exchange_rate=rate,
            description=desc[:255],
        )
        session.add(refund)
        session.flush()

        if with_cash:
            regs = SalesService.ensure_default_registers(session)
            reg = regs.get(purchase.currency.strip().upper())
            reg_id = None
            if reg is not None:
                reg.balance = _money(_decimal(reg.balance) + debt)
                reg_id = reg.id
                session.add(
                    CashTransaction(
                        cash_register_id=reg.id,
                        transaction_type="income",
                        amount=debt,
                        currency=purchase.currency,
                        exchange_rate=rate,
                        description=desc[:255],
                        transaction_date=now,
                    )
                )
            session.add(
                CashMovement(
                    movement_date=now,
                    movement_type="purchase_refund",
                    currency=purchase.currency,
                    amount=debt,
                    exchange_rate=rate,
                    cash_register_id=reg_id,
                    purchase_refund_id=refund.id,
                    description=desc[:255],
                )
            )
            session.flush()
        return debt

    @staticmethod
    def get_simurg_summary(
        session: Session,
        as_of: datetime | None = None,
        include_paid: bool = False,
    ) -> dict:
        """Сводка по рассрочке Simurg (и открытым клиентским долгам) с учётом 5-дневного срока выплаты.

        Возвращает:
        - total_debt: общий непогашенный долг (USD/TMT)
        - ready_amount: сумма, которую уже можно забрать (дата выплаты <= as_of)
        - pending_amount: сумма в ожидании (< 5 дней)
        - total_items_count, ready_items_count, pending_items_count: кол-во устройств/товаров
        - open_sales_count, ready_sales_count
        - rows: детальный список сделок
        """
        from datetime import date as _date
        from datetime import timedelta

        from app.models.product import Product
        from app.models.sale_item import SaleItem

        now = as_of or datetime.now()
        today = now.date()

        sales = session.scalars(
            select(Sale)
            .where(Sale.status != "cancelled")
            .order_by(Sale.sale_date.asc(), Sale.id.asc())
        ).all()

        total_debt = {"USD": Decimal("0.00"), "TMT": Decimal("0.00")}
        ready_amount = {"USD": Decimal("0.00"), "TMT": Decimal("0.00")}
        pending_amount = {"USD": Decimal("0.00"), "TMT": Decimal("0.00")}
        total_items_count = 0
        ready_items_count = 0
        pending_items_count = 0
        open_sales_count = 0
        ready_sales_count = 0
        rows: list[dict] = []

        for sale in sales:
            cur = sale.currency.strip().upper()
            if cur not in ("USD", "TMT"):
                continue

            debt = SalesService.get_customer_debt(session, sale)
            is_simurg = bool(getattr(sale, "is_simurg", False))
            if not is_simurg and debt <= Decimal("0.00"):
                continue
            if debt <= Decimal("0.00") and not include_paid:
                continue

            paid = SalesService.get_sale_paid_amount(session, sale)
            total = _money(_decimal(sale.total_amount))

            item_rows = session.execute(
                select(SaleItem, Product.name)
                .join(Product, SaleItem.product_id == Product.id)
                .where(SaleItem.sale_id == sale.id)
            ).all()
            items_count = sum(int(si.quantity or 0) for si, _ in item_rows)
            item_parts = []
            for si, p_name in item_rows:
                if si.imei:
                    item_parts.append(f"{p_name} ({si.imei})")
                elif si.quantity > 1:
                    item_parts.append(f"{p_name} ×{si.quantity}")
                else:
                    item_parts.append(p_name)
            items_summary = ", ".join(item_parts) or "—"

            payout_dt = getattr(sale, "simurg_payout_date", None)
            if payout_dt is None:
                payout_dt = (
                    (sale.sale_date + timedelta(days=5))
                    if is_simurg and sale.sale_date
                    else sale.sale_date
                )
            payout_day = payout_dt.date() if isinstance(payout_dt, datetime) else _date.today()
            days_left = (payout_day - today).days
            is_ready = days_left <= 0

            if debt > Decimal("0.00"):
                open_sales_count += 1
                total_items_count += items_count
                total_debt[cur] = _money(total_debt[cur] + debt)
                if is_ready:
                    ready_sales_count += 1
                    ready_items_count += items_count
                    ready_amount[cur] = _money(ready_amount[cur] + debt)
                else:
                    pending_items_count += items_count
                    pending_amount[cur] = _money(pending_amount[cur] + debt)

            if debt <= Decimal("0.00"):
                status_label = "Tölendi"
            elif is_ready:
                overdue = abs(days_left)
                status_label = (
                    f"Taýýar (+{overdue} gün)" if overdue > 0 else "Taýýar (şu gün)"
                )
            else:
                status_label = f"Garaşylýar ({days_left} gün galdy)"

            rows.append({
                "sale_id": sale.id,
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "payout_date": payout_dt,
                "days_left": days_left,
                "is_ready": is_ready,
                "is_simurg": is_simurg,
                "items_count": items_count,
                "items_summary": items_summary,
                "customer_name": sale.customer_name or ("Simurg" if is_simurg else "Bölek müşderi"),
                "customer_phone": sale.customer_phone or "",
                "currency": cur,
                "exchange_rate": _validate_rate(sale.exchange_rate or Decimal("1.0000")),
                "original_amount": total,
                "paid_amount": paid,
                "remaining_debt": debt,
                "status_label": status_label,
                "comment": sale.comment or "",
            })

        # Сначала созревшие (самые старые), затем ожидающие, затем оплаченные
        rows.sort(
            key=lambda r: (
                0 if r["remaining_debt"] > 0 and r["is_ready"] else (1 if r["remaining_debt"] > 0 else 2),
                r["payout_date"] or datetime.max,
                r["sale_id"],
            )
        )

        return {
            "total_debt": total_debt,
            "ready_amount": ready_amount,
            "pending_amount": pending_amount,
            "total_items_count": total_items_count,
            "ready_items_count": ready_items_count,
            "pending_items_count": pending_items_count,
            "open_sales_count": open_sales_count,
            "ready_sales_count": ready_sales_count,
            "rows": rows,
        }

    @staticmethod
    def collect_simurg_payout(
        session: Session,
        currency: str,
        amount: Decimal | float | str | None = None,
        ready_only: bool = True,
        exchange_rate: Decimal | float | str | None = None,
        description: str | None = None,
        as_of: datetime | None = None,
    ) -> dict:
        """Принимает выплату от Simurg в кассу и распределяет по открытым чекам FIFO (от самых старых).

        Если amount=None и ready_only=True — забирает всю «созревшую» сумму (где прошло >= 5 дней).
        Если amount задан — распределяет эту сумму по очереди (при ready_only=False может закрывать и более свежие).
        """
        from app.services.settings_service import SettingsService

        curr = (currency or "").strip().upper()
        if curr not in ("USD", "TMT"):
            raise ValueError("Rugsat berlen walýutalar: USD, TMT.")

        rate = _validate_rate(exchange_rate or SettingsService.get_default_exchange_rate())
        summary = FinanceService.get_simurg_summary(session, as_of=as_of, include_paid=False)

        candidates = [
            r for r in summary["rows"]
            if r["currency"] == curr
            and r["remaining_debt"] > Decimal("0.00")
            and (not ready_only or r["is_ready"])
        ]
        if not candidates:
            raise ValueError(
                f"{curr} boýunça almak üçin taýýar Simurg bergisi ýok."
                if ready_only
                else f"{curr} boýunça açyk Simurg bergisi ýok."
            )

        available_total = _money(sum((r["remaining_debt"] for r in candidates), Decimal("0.00")))
        if amount is None:
            to_collect = available_total
        else:
            to_collect = _money(_decimal(amount))
            if to_collect <= Decimal("0.00"):
                raise ValueError("Töleg mukdary noldan uly bolmaly.")
            if to_collect > available_total:
                raise ValueError(
                    f"Girizilen mukdar ({to_collect} {curr}) elýeterli Simurg bergisinden ({available_total} {curr}) köp."
                )

        remaining_to_apply = to_collect
        closed_sales: list[dict] = []
        base_desc = (description or "").strip() or "Simurg tölegi"

        for row in candidates:
            if remaining_to_apply <= Decimal("0.00"):
                break
            apply_amt = min(row["remaining_debt"], remaining_to_apply)
            apply_amt = _money(apply_amt)
            if apply_amt <= Decimal("0.00"):
                continue
            SalesService.add_sale_payment(
                session=session,
                sale_id=row["sale_id"],
                currency=curr,
                amount=apply_amt,
                exchange_rate=rate,
                description=f"{base_desc} ({row['receipt_number']})",
            )
            closed_sales.append({
                "sale_id": row["sale_id"],
                "receipt_number": row["receipt_number"],
                "applied_amount": apply_amt,
            })
            remaining_to_apply = _money(remaining_to_apply - apply_amt)

        collected = _money(to_collect - remaining_to_apply)
        return {
            "currency": curr,
            "collected_amount": collected,
            "sales_count": len(closed_sales),
            "details": closed_sales,
        }

    @staticmethod
    def get_monthly_expenses_summary(
        session: Session,
        year: int | None = None,
        month: int | None = None,
    ) -> dict:
        """Возвращает сумму расходов за указанный (по умолчанию текущий) месяц по USD и TMT."""
        now = datetime.now()
        y = year or now.year
        m = month or now.month
        start = datetime(y, m, 1, 0, 0, 0)
        end = datetime(y + 1, 1, 1, 0, 0, 0) if m == 12 else datetime(y, m + 1, 1, 0, 0, 0)

        expenses = session.scalars(
            select(Expense).where(
                Expense.expense_date >= start,
                Expense.expense_date < end,
            )
        ).all()

        usd = Decimal("0.00")
        tmt = Decimal("0.00")
        for exp in expenses:
            cur = exp.currency.strip().upper()
            amt = _money(_decimal(exp.amount))
            if cur == "USD":
                usd = _money(usd + amt)
            elif cur == "TMT":
                tmt = _money(tmt + amt)

        return {
            "USD": usd,
            "TMT": tmt,
            "count": len(expenses),
            "year": y,
            "month": m,
        }
