from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_register import CashRegister, CashTransaction

CENT = Decimal("0.01")
RATE_PRECISION = Decimal("0.0001")


def _decimal(value) -> Decimal:
    try:
        res = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Некорректное числовое значение.") from exc
    if not res.is_finite():
        raise ValueError("Число должно быть конечным.")
    return res


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _validate_rate(value) -> Decimal:
    rate = _decimal(value)
    if rate <= 0:
        raise ValueError("Курс обмена должен быть больше нуля.")
    return rate.quantize(RATE_PRECISION, rounding=ROUND_HALF_UP)


class CashService:
    @staticmethod
    def adjust_register_balance(
        session: Session,
        cash_register_id: int,
        amount: Decimal,
        transaction_type: str,
        currency: str,
        exchange_rate: Decimal,
        description: str | None = None,
        sale_id: int | None = None,
    ) -> CashTransaction:
        """Изменяет баланс кассы и создает запись движения денег (CashTransaction)."""
        register = session.get(CashRegister, cash_register_id)
        if not register:
            raise ValueError(f"Касса с ID {cash_register_id} не найдена.")

        amount = _money(_decimal(amount))
        if amount <= 0:
            raise ValueError("Сумма транзакции должна быть больше нуля.")

        exchange_rate = _validate_rate(exchange_rate)

        if transaction_type not in ("income", "expense", "refund"):
            raise ValueError("Некорректный тип кассовой транзакции.")

        if currency == register.currency:
            delta = amount
        elif currency == "TMT" and register.currency == "USD":
            delta = _money(amount / exchange_rate)
        elif currency == "USD" and register.currency == "TMT":
            delta = _money(amount * exchange_rate)
        else:
            raise ValueError("Несоответствие валют кассы и платежа.")

        if transaction_type == "income":
            register.balance = _money(Decimal(str(register.balance)) + delta)
        elif transaction_type in ("expense", "refund"):
            new_balance = Decimal(str(register.balance)) - delta
            if new_balance < 0:
                raise ValueError("Недостаточно средств в кассе.")
            register.balance = _money(new_balance)

        tx = CashTransaction(
            cash_register_id=register.id,
            transaction_type=transaction_type,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            description=description,
            transaction_date=datetime.now(),
            sale_id=sale_id,
        )
        session.add(tx)
        session.flush()
        return tx
