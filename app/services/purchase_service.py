
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.models.cash_movement import CashMovement
from app.models.cash_register import CashRegister, CashTransaction
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund
from app.models.stock_item import StockItem

CURRENCIES = {"USD", "TMT"}
CENT = Decimal("0.01")
RATE_PRECISION = Decimal("0.0001")


def _decimal(value: Any) -> Decimal:
    """Преобразует значение в Decimal и проверяет корректность числа."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("San bahasy nädogry.") from exc

    if not result.is_finite():
        raise ValueError("San gutarnykly bolmaly.")

    return result


def _money(value: Decimal) -> Decimal:
    """Округляет денежную сумму до двух знаков."""
    try:
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(
            "Mukdar gaty uly ýa-da formaty nädogry."
        ) from exc


def _validate_currency(currency: str) -> str:
    """Проверяет и нормализует валюту."""
    if not isinstance(currency, str):
        raise TypeError("Walýuta tekst görnüşinde görkezilmeli.")

    currency = currency.strip().upper()

    if currency not in CURRENCIES:
        raise ValueError("Rugsat edilýän walýutalar: USD we TMT.")

    return currency


def _validate_rate(value: Any) -> Decimal:
    """Проверяет курс и приводит его к четырём знакам."""
    rate = _decimal(value)

    try:
        rate = rate.quantize(RATE_PRECISION, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Kurs formaty nädogry.") from exc

    if rate <= 0:
        raise ValueError("Kurs noldan uly bolmaly.")

    return rate


def _positive_integer(value: Any, field_name: str) -> int:
    """Проверяет положительное целое число."""
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} položitel bitin san bolmaly."
        )

    number = _decimal(value)

    if number != number.to_integral_value() or number <= 0:
        raise ValueError(
            f"{field_name} položitel bitin san bolmaly."
        )

    return int(number)


def _convert_to_document_currency(
    amount: Decimal,
    payment_currency: str,
    document_currency: str,
    exchange_rate: Decimal,
) -> Decimal:
    """Пересчитывает сумму в валюту документа.

    Курс всегда выражен в TMT за 1 USD.
    """
    if payment_currency == document_currency:
        return _money(amount)

    if payment_currency == "TMT" and document_currency == "USD":
        return _money(amount / exchange_rate)

    if payment_currency == "USD" and document_currency == "TMT":
        return _money(amount * exchange_rate)

    raise ValueError("Walýutany hasaplap bolmady.")


def _get_paid_amount(session: Session, purchase: Purchase) -> Decimal:
    """Возвращает сумму платежей в валюте закупки."""
    payments = session.scalars(
        select(PurchasePayment).where(
            PurchasePayment.purchase_id == purchase.id
        )
    ).all()

    paid = Decimal("0.00")

    for payment in payments:
        paid += _convert_to_document_currency(
            Decimal(str(payment.amount)),
            payment.currency,
            purchase.currency,
            Decimal(str(payment.exchange_rate)),
        )

    return _money(paid)


def _get_refunded_amount(session: Session, purchase: Purchase) -> Decimal:
    """Возвращает сумму возвратов в валюте закупки."""
    refunds = session.scalars(
        select(PurchaseRefund).where(
            PurchaseRefund.purchase_id == purchase.id
        )
    ).all()

    refunded = Decimal("0.00")

    for refund in refunds:
        refunded += _convert_to_document_currency(
            Decimal(str(refund.amount)),
            refund.currency,
            purchase.currency,
            Decimal(str(refund.exchange_rate)),
        )

    return _money(refunded)


def _get_supplier_debt_amount(
    session: Session,
    purchase: Purchase,
) -> Decimal:
    """Рассчитывает остаток денег, которые поставщик должен вернуть."""
    paid = _get_paid_amount(session, purchase)
    refunded = _get_refunded_amount(session, purchase)

    return max(Decimal("0.00"), _money(paid - refunded))


def _register_payment(
    session: Session,
    purchase: Purchase,
    currency: str,
    amount: Decimal,
    exchange_rate: Decimal,
    payment_date: datetime | None = None,
) -> PurchasePayment:
    """Регистрирует платёж и соответствующее движение кассы."""
    if purchase.status != "active":
        raise ValueError("Ýatyrylan alyş üçin töleg edip bolmaýar.")

    currency = _validate_currency(currency)
    amount = _money(_decimal(amount))
    exchange_rate = _validate_rate(exchange_rate)

    if amount <= 0:
        raise ValueError("Töleg mukdary noldan uly bolmaly.")

    payment_date = payment_date or datetime.now()
    paid_before = _get_paid_amount(session, purchase)

    payment_in_document_currency = _convert_to_document_currency(
        amount,
        currency,
        purchase.currency,
        exchange_rate,
    )

    remaining = _money(
        Decimal(str(purchase.total_amount)) - paid_before
    )

    if payment_in_document_currency > remaining:
        raise ValueError(
            f"Töleg mukdary galan bergiden köp: "
            f"{remaining} {purchase.currency}."
        )

    payment = PurchasePayment(
        purchase_id=purchase.id,
        payment_date=payment_date,
        currency=currency,
        amount=amount,
        exchange_rate=exchange_rate,
    )

    session.add(payment)
    session.flush()

    register = session.scalar(
        select(CashRegister).where(CashRegister.currency == currency)
    )
    reg_id = None
    if register is not None:
        reg_balance = _money(_decimal(register.balance))
        if reg_balance < amount:
            raise ValueError(
                f"{currency} kassasynda pul ýeterlik däl "
                f"(elýeterli: {reg_balance} {currency}, gerek: {amount} {currency})."
            )
        register.balance = _money(reg_balance - amount)
        reg_id = register.id
        session.add(
            CashTransaction(
                cash_register_id=register.id,
                transaction_type="expense",
                amount=amount,
                currency=currency,
                exchange_rate=exchange_rate,
                description=f"Alyş №{purchase.id} tölegi",
                transaction_date=payment_date,
            )
        )

    session.add(
        CashMovement(
            movement_date=payment_date,
            movement_type="purchase_payment",
            currency=currency,
            amount=amount,
            exchange_rate=exchange_rate,
            cash_register_id=reg_id,
            purchase_payment_id=payment.id,
            description=f"Alyş №{purchase.id} tölegi",
        )
    )

    return payment


def create_purchase(
    items: list[dict],
    currency: str,
    exchange_rate: Decimal | float | str,
    payments: list[dict] | None = None,
    note: str | None = None,
    purchase_date: datetime | None = None,
    supplier_name: str | None = None,
) -> int:
    """Создаёт закупку, увеличивает остатки и регистрирует платежи."""
    currency = _validate_currency(currency)
    rate = _validate_rate(exchange_rate)

    if not items:
        raise ValueError("Alyşda iň azyndan bir haryt bolmaly.")

    payments = payments or []
    purchase_date = purchase_date or datetime.now()
    if supplier_name is not None:
        supplier_name = str(supplier_name).strip() or None

    with SessionLocal() as session, session.begin():
        purchase = Purchase(
            purchase_date=purchase_date,
            supplier_name=supplier_name,
            currency=currency,
            exchange_rate=rate,
            total_amount=Decimal("0.00"),
            note=note,
            status="active",
        )

        session.add(purchase)
        session.flush()

        total = Decimal("0.00")
        seen_imeis: set[str] = set()

        for item in items:
            product_id = _positive_integer(
                item["product_id"],
                "Haryt ID",
            )
            quantity = _positive_integer(
                item["quantity"],
                "Sany",
            )
            unit_cost = _money(_decimal(item["unit_cost"]))

            if unit_cost < 0:
                raise ValueError(
                    "Alyş bahasy otrisatel bolup bilmez."
                )

            product = session.scalar(
                select(Product).where(
                    Product.id == product_id,
                    Product.is_active.is_(True),
                )
            )

            if product is None:
                raise ValueError(
                    f"ID {product_id} bolan işjeň haryt tapylmady."
                )

            line_total = _money(unit_cost * quantity)

            session.add(
                PurchaseItem(
                    purchase_id=purchase.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    total_cost=line_total,
                )
            )

            imei_records = item.get("imeis") or []
            if len(imei_records) > quantity:
                raise ValueError(
                    f"IMEI sany ({len(imei_records)}) "
                    f"'{product.name}' harydynyň sanyndan ({quantity}) köp."
                )
            for imei_data in imei_records:
                if isinstance(imei_data, str):
                    imei1 = imei_data.strip()
                    imei2 = None
                    serial_number = None
                    condition = "new"
                else:
                    imei1 = str(imei_data.get("imei1", "")).strip()
                    imei2_raw = imei_data.get("imei2")
                    imei2 = str(imei2_raw).strip() or None if imei2_raw else None
                    sn_raw = imei_data.get("serial_number")
                    serial_number = str(sn_raw).strip() or None if sn_raw else None
                    condition = str(imei_data.get("condition", "new")).strip() or "new"

                if not imei1:
                    raise ValueError("IMEI 1 boş bolup bilmez.")
                if imei1 in seen_imeis or (imei2 and imei2 in seen_imeis) or imei1 == imei2:
                    raise ValueError(f"Alyş resminamasynda gaýtalanýan IMEI: {imei1}")
                seen_imeis.add(imei1)
                if imei2:
                    seen_imeis.add(imei2)

                existing_stock = session.scalar(
                    select(StockItem).where(
                        (StockItem.imei1 == imei1)
                        | (StockItem.imei2 == imei1)
                        | (
                            (StockItem.imei1 == imei2)
                            | (StockItem.imei2 == imei2)
                            if imei2
                            else False
                        )
                    )
                )
                if existing_stock is not None:
                    raise ValueError(f"IMEI {imei1} bolan enjam eýýäm bazada hasaba alnan.")

                session.add(
                    StockItem(
                        product_id=product.id,
                        purchase_id=purchase.id,
                        imei1=imei1,
                        imei2=imei2,
                        serial_number=serial_number,
                        condition=condition,
                        status="in_stock",
                        unit_cost=unit_cost,
                        cost_currency=currency,
                        cost_exchange_rate=rate,
                        created_at=purchase_date,
                    )
                )

            product.stock_quantity += quantity
            total += line_total

        purchase.total_amount = _money(total)

        for payment_data in payments:
            _register_payment(
                session=session,
                purchase=purchase,
                currency=payment_data["currency"],
                amount=_decimal(payment_data["amount"]),
                exchange_rate=_decimal(payment_data["exchange_rate"]),
                payment_date=payment_data.get("payment_date"),
            )

        purchase_id = purchase.id

    return purchase_id


def add_purchase_payment(
    purchase_id: int,
    currency: str,
    amount: Decimal | float | str,
    exchange_rate: Decimal | float | str,
    payment_date: datetime | None = None,
) -> int:
    """Добавляет очередной платёж по существующей закупке."""
    purchase_id = _positive_integer(purchase_id, "Alyş ID")

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Alyş tapylmady.")

        payment = _register_payment(
            session=session,
            purchase=purchase,
            currency=currency,
            amount=_decimal(amount),
            exchange_rate=_decimal(exchange_rate),
            payment_date=payment_date,
        )

        payment_id = payment.id

    return payment_id


def get_purchase_balance(purchase_id: int) -> Decimal:
    """Возвращает долг магазина по активной закупке."""
    purchase_id = _positive_integer(purchase_id, "Alyş ID")

    with SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Alyş tapylmady.")

        if purchase.status == "cancelled":
            return Decimal("0.00")

        paid = _get_paid_amount(session, purchase)

        return max(
            Decimal("0.00"),
            _money(Decimal(str(purchase.total_amount)) - paid),
        )


def cancel_purchase(
    purchase_id: int,
    reason: str,
    cancelled_at: datetime | None = None,
) -> None:
    """Аннулирует закупку и возвращает её товары со склада."""
    purchase_id = _positive_integer(purchase_id, "Alyş ID")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Ýatyrma sebäbini görkeziň.")

    reason = reason.strip()

    if len(reason) > 255:
        raise ValueError("Sebäp 255 nyşandan köp bolmaly däl.")

    cancelled_at = cancelled_at or datetime.now()

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Alyş tapylmady.")

        if purchase.status != "active":
            raise ValueError("Alyş eýýäm ýatyryldy.")

        purchase_items = session.scalars(
            select(PurchaseItem).where(
                PurchaseItem.purchase_id == purchase_id
            )
        ).all()

        # Суммируем одинаковые товары: одна позиция товара
        # может встречаться в закупке несколько раз.
        quantities: dict[int, int] = defaultdict(int)

        for item in purchase_items:
            quantities[item.product_id] += item.quantity

        products: dict[int, Product] = {}

        # Сначала проверяем все остатки. Только после успешной
        # проверки изменяем склад.
        for product_id, quantity in quantities.items():
            product = session.get(Product, product_id)

            if product is None:
                raise ValueError(
                    f"ID {product_id} bolan haryt tapylmady."
                )

            if product.stock_quantity < quantity:
                raise ValueError(
                    f"Alyşy ýatyryp bolmaýar: «{product.name}» harydyndan "
                    f"skladda {product.stock_quantity} bar, "
                    f"yzyna gaýtarmaly {quantity}. "
                    "Harydyň bir bölegi eýýäm çykarylan bolmagy mümkin."
                )

            products[product_id] = product

        for product_id, quantity in quantities.items():
            products[product_id].stock_quantity -= quantity

        # Проверяем и удаляем связанные с закупкой IMEI-записи (или запрещаем отмену, если IMEI уже продан)
        linked_stock_items = session.scalars(
            select(StockItem).where(StockItem.purchase_id == purchase_id)
        ).all()
        for s_item in linked_stock_items:
            if s_item.status != "in_stock":
                raise ValueError(
                    f"Alyşy ýatyryp bolmaýar: IMEI {s_item.imei1} bolan enjam "
                    "eýýäm satyldy ýa-da elýeterli däl."
                )
            session.delete(s_item)

        purchase.status = "cancelled"
        purchase.cancelled_at = cancelled_at
        purchase.cancellation_reason = reason


def add_purchase_refund(
    purchase_id: int,
    currency: str,
    amount: Decimal | float | str,
    exchange_rate: Decimal | float | str,
    refund_date: datetime | None = None,
    description: str | None = None,
) -> int:
    """Регистрирует возврат денег от поставщика и приход в кассу."""
    purchase_id = _positive_integer(purchase_id, "Alyş ID")
    currency = _validate_currency(currency)
    refund_amount = _money(_decimal(amount))
    rate = _validate_rate(exchange_rate)

    if refund_amount <= 0:
        raise ValueError("Yzyna gaýtarma mukdary noldan uly bolmaly.")

    if description is not None:
        description = description.strip() or None
        if description is not None and len(description) > 255:
            raise ValueError(
                "Bellik 255 nyşandan köp bolmaly däl."
            )

    refund_date = refund_date or datetime.now()

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Alyş tapylmady.")

        if purchase.status != "cancelled":
            raise ValueError(
                "Pul yzyna gaýtarmagy diňe ýatyrylan alyş boýunça belläp bolýar."
            )

        debt_before = _get_supplier_debt_amount(session, purchase)

        refund_in_document_currency = _convert_to_document_currency(
            refund_amount,
            currency,
            purchase.currency,
            rate,
        )

        if refund_in_document_currency > debt_before:
            raise ValueError(
                f"Yzyna gaýtarma üpjün edijiniň bergisinden köp. "
                f"Galyndy: {debt_before} {purchase.currency}."
            )

        refund = PurchaseRefund(
            purchase_id=purchase.id,
            refund_date=refund_date,
            currency=currency,
            amount=refund_amount,
            exchange_rate=rate,
            description=description,
        )

        session.add(refund)
        session.flush()

        register = session.scalar(
            select(CashRegister).where(CashRegister.currency == currency)
        )
        reg_id = None
        if register is not None:
            reg_balance = _money(_decimal(register.balance))
            register.balance = _money(reg_balance + refund_amount)
            reg_id = register.id
            session.add(
                CashTransaction(
                    cash_register_id=register.id,
                    transaction_type="income",
                    amount=refund_amount,
                    currency=currency,
                    exchange_rate=rate,
                    description=(
                        description
                        or f"Alyş №{purchase.id} boýunça üpjün edijiden yzyna gaýtarma"
                    ),
                    transaction_date=refund_date,
                )
            )

        session.add(
            CashMovement(
                movement_date=refund_date,
                movement_type="purchase_refund",
                currency=currency,
                amount=refund_amount,
                exchange_rate=rate,
                cash_register_id=reg_id,
                purchase_refund_id=refund.id,
                description=(
                    description
                    or f"Alyş №{purchase.id} boýunça üpjün edijiden yzyna gaýtarma"
                ),
            )
        )

        refund_id = refund.id

    return refund_id


def get_supplier_debt(purchase_id: int) -> Decimal:
    """Возвращает задолженность поставщика по аннулированной закупке."""
    purchase_id = _positive_integer(purchase_id, "Alyş ID")

    with SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Alyş tapylmady.")

        if purchase.status != "cancelled":
            return Decimal("0.00")

        return _get_supplier_debt_amount(session, purchase)
