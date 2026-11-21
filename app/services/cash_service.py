from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.cash_register import CashRegister, CashTransaction

CENT = Decimal("0.01")
RATE_PRECISION = Decimal("0.0001")


def _decimal(value) -> Decimal:
    try:
        res = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Nädogry san bahasy.") from exc
    if not res.is_finite():
        raise ValueError("San çäkli bolmaly.")
    return res


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _validate_rate(value) -> Decimal:
    rate = _decimal(value)
    if rate <= 0:
        raise ValueError("Çalyşyk kursy noldan uly bolmaly.")
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
            raise ValueError(f"ID {cash_register_id} kassa tapylmady.")

        amount = _money(_decimal(amount))
        if amount <= 0:
            raise ValueError("Amal mukdary noldan uly bolmaly.")

        exchange_rate = _validate_rate(exchange_rate)

        if transaction_type not in ("income", "expense", "refund"):
            raise ValueError("Nädogry kassa amalynyň görnüşi.")

        if currency == register.currency:
            delta = amount
        elif currency == "TMT" and register.currency == "USD":
            delta = _money(amount / exchange_rate)
        elif currency == "USD" and register.currency == "TMT":
            delta = _money(amount * exchange_rate)
        else:
            raise ValueError("Kassa we töleg walýutalary gabat gelmeýär.")

        if transaction_type == "income":
            register.balance = _money(Decimal(str(register.balance)) + delta)
        elif transaction_type in ("expense", "refund"):
            new_balance = Decimal(str(register.balance)) - delta
            if new_balance < 0:
                raise ValueError("Kassada ýeterlik pul ýok.")
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
