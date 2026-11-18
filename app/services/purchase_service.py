
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.models.cash_movement import CashMovement
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund

CURRENCIES = {"USD", "TMT"}
CENT = Decimal("0.01")
RATE_PRECISION = Decimal("0.0001")


def _decimal(value: Any) -> Decimal:
    """Преобразует значение в Decimal и проверяет корректность числа."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Некорректное числовое значение.") from exc

    if not result.is_finite():
        raise ValueError("Число должно быть конечным.")

    return result


def _money(value: Decimal) -> Decimal:
    """Округляет денежную сумму до двух знаков."""
    try:
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(
            "Сумма слишком велика или имеет некорректный формат."
        ) from exc


def _validate_currency(currency: str) -> str:
    """Проверяет и нормализует валюту."""
    if not isinstance(currency, str):
        raise TypeError("Валюта должна быть указана текстом.")

    currency = currency.strip().upper()

    if currency not in CURRENCIES:
        raise ValueError("Допустимые валюты: USD и TMT.")

    return currency


def _validate_rate(value: Any) -> Decimal:
    """Проверяет курс и приводит его к четырём знакам."""
    rate = _decimal(value)

    try:
        rate = rate.quantize(RATE_PRECISION, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Некорректный формат курса.") from exc

    if rate <= 0:
        raise ValueError("Курс должен быть больше нуля.")

    return rate


def _positive_integer(value: Any, field_name: str) -> int:
    """Проверяет положительное целое число."""
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} должно быть положительным целым числом."
        )

    number = _decimal(value)

    if number != number.to_integral_value() or number <= 0:
        raise ValueError(
            f"{field_name} должно быть положительным целым числом."
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

    raise ValueError("Не удалось пересчитать валюту.")


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
        raise ValueError("Нельзя оплачивать аннулированную закупку.")

    currency = _validate_currency(currency)
    amount = _money(_decimal(amount))
    exchange_rate = _validate_rate(exchange_rate)

    if amount <= 0:
        raise ValueError("Сумма платежа должна быть больше нуля.")

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
            f"Сумма платежа превышает остаток долга: "
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

    session.add(
        CashMovement(
            movement_date=payment_date,
            movement_type="purchase_payment",
            currency=currency,
            amount=amount,
            purchase_payment_id=payment.id,
            description=f"Оплата закупки №{purchase.id}",
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
) -> int:
    """Создаёт закупку, увеличивает остатки и регистрирует платежи."""
    currency = _validate_currency(currency)
    rate = _validate_rate(exchange_rate)

    if not items:
        raise ValueError("В закупке должен быть хотя бы один товар.")

    payments = payments or []
    purchase_date = purchase_date or datetime.now()

    with SessionLocal() as session, session.begin():
        purchase = Purchase(
            purchase_date=purchase_date,
            currency=currency,
            exchange_rate=rate,
            total_amount=Decimal("0.00"),
            note=note,
            status="active",
        )

        session.add(purchase)
        session.flush()

        total = Decimal("0.00")

        for item in items:
            product_id = _positive_integer(
                item["product_id"],
                "ID товара",
            )
            quantity = _positive_integer(
                item["quantity"],
                "Количество",
            )
            unit_cost = _money(_decimal(item["unit_cost"]))

            if unit_cost < 0:
                raise ValueError(
                    "Закупочная цена не может быть отрицательной."
                )

            product = session.scalar(
                select(Product).where(
                    Product.id == product_id,
                    Product.is_active.is_(True),
                )
            )

            if product is None:
                raise ValueError(
                    f"Активный товар с ID {product_id} не найден."
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
    purchase_id = _positive_integer(purchase_id, "ID закупки")

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Закупка не найдена.")

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
    purchase_id = _positive_integer(purchase_id, "ID закупки")

    with SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Закупка не найдена.")

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
    purchase_id = _positive_integer(purchase_id, "ID закупки")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Укажи причину аннулирования.")

    reason = reason.strip()

    if len(reason) > 255:
        raise ValueError("Причина не должна превышать 255 символов.")

    cancelled_at = cancelled_at or datetime.now()

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Закупка не найдена.")

        if purchase.status != "active":
            raise ValueError("Закупка уже аннулирована.")

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
                    f"Товар с ID {product_id} не найден."
                )

            if product.stock_quantity < quantity:
                raise ValueError(
                    f"Нельзя аннулировать закупку: товара "
                    f"«{product.name}» на складе {product.stock_quantity}, "
                    f"а вернуть нужно {quantity}. "
                    "Вероятно, часть товара уже выбыла."
                )

            products[product_id] = product

        for product_id, quantity in quantities.items():
            products[product_id].stock_quantity -= quantity

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
    purchase_id = _positive_integer(purchase_id, "ID закупки")
    currency = _validate_currency(currency)
    refund_amount = _money(_decimal(amount))
    rate = _validate_rate(exchange_rate)

    if refund_amount <= 0:
        raise ValueError("Сумма возврата должна быть больше нуля.")

    if description is not None:
        description = description.strip() or None
        if description is not None and len(description) > 255:
            raise ValueError(
                "Описание не должно превышать 255 символов."
            )

    refund_date = refund_date or datetime.now()

    with SessionLocal() as session, session.begin():
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Закупка не найдена.")

        if purchase.status != "cancelled":
            raise ValueError(
                "Возврат денег можно зарегистрировать "
                "только по аннулированной закупке."
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
                f"Возврат превышает задолженность поставщика. "
                f"Остаток: {debt_before} {purchase.currency}."
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

        session.add(
            CashMovement(
                movement_date=refund_date,
                movement_type="purchase_refund",
                currency=currency,
                amount=refund_amount,
                purchase_refund_id=refund.id,
                description=(
                    description
                    or f"Возврат от поставщика по закупке №{purchase.id}"
                ),
            )
        )

        refund_id = refund.id

    return refund_id


def get_supplier_debt(purchase_id: int) -> Decimal:
    """Возвращает задолженность поставщика по аннулированной закупке."""
    purchase_id = _positive_integer(purchase_id, "ID закупки")

    with SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)

        if purchase is None:
            raise ValueError("Закупка не найдена.")

        if purchase.status != "cancelled":
            return Decimal("0.00")

        return _get_supplier_debt_amount(session, purchase)
