from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.product import Product
from app.models.stock_item import StockItem
from app.models.cash_register import CashRegister
from app.services.cash_service import CashService, _decimal, _money, _validate_rate


class SalesService:
    @staticmethod
    def create_sale(
        session: Session,
        items: list[dict],
        payments: list[dict],
        currency: str = "TMT",
        exchange_rate: Decimal = Decimal("1.0000"),
        receipt_number: str | None = None,
        note: str | None = None,
        comment: str | None = None,
    ) -> Sale:
        """Создает продажу (чек) с позициями, проверяет склад и IMEI, списывает остатки и принимает оплату."""
        currency = currency.strip().upper()
        if currency not in ("USD", "TMT"):
            raise ValueError("Допустимые валюты чека: USD, TMT.")

        exchange_rate = _validate_rate(exchange_rate)

        if not items:
            raise ValueError("Чек не может быть пустым.")

        if not payments:
            raise ValueError("Необходимо указать хотя бы один способ оплаты.")

        if not receipt_number:
            receipt_number = f"REC-{datetime.now().strftime('%Y%m%d%H%M%S-%f')}"

        sale = Sale(
            receipt_number=receipt_number,
            sale_date=datetime.now(),
            currency=currency,
            total_amount=Decimal("0.00"),
            status="completed",
            note=note,
            comment=comment,
        )
        session.add(sale)
        session.flush()

        total_sale_amount_doc_curr = Decimal("0.00")

        for item_data in items:
            product_id = item_data.get("product_id")
            quantity = int(item_data.get("quantity", 1))
            unit_price = _money(_decimal(item_data.get("unit_price")))
            discount = _money(_decimal(item_data.get("discount", 0)))
            imei = item_data.get("imei")
            item_currency = item_data.get("currency", currency).strip().upper()

            if quantity <= 0:
                raise ValueError("Количество товара должно быть больше нуля.")
            if unit_price < 0:
                raise ValueError("Цена продажи не может быть отрицательной.")

            product = session.get(Product, product_id)
            if not product:
                raise ValueError(f"Товар с ID {product_id} не найден.")

            stock_item_id = None

            if imei:
                imei = str(imei).strip()
                stock_item = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == product_id,
                        (StockItem.imei1 == imei) | (StockItem.imei2 == imei),
                    )
                )
                if not stock_item:
                    raise ValueError(f"Товар с IMEI {imei} не найден на складе.")
                if stock_item.status != "in_stock":
                    raise ValueError(f"Товар с IMEI {imei} уже продан или недоступен.")
                
                stock_item.status = "sold"
                stock_item_id = stock_item.id
                quantity = 1

            if product.stock_quantity < quantity:
                raise ValueError(f"Недостаточно товара '{product.name}' на складе (остаток: {product.stock_quantity}, требуется: {quantity}).")

            product.stock_quantity -= quantity

            line_amount_item_curr = _money((unit_price * quantity) - discount)
            if line_amount_item_curr < 0:
                raise ValueError("Сумма позиции с учетом скидки не может быть отрицательной.")

            if item_currency == currency:
                line_amount_doc_curr = line_amount_item_curr
            elif item_currency == "TMT" and currency == "USD":
                line_amount_doc_curr = _money(line_amount_item_curr / exchange_rate)
            elif item_currency == "USD" and currency == "TMT":
                line_amount_doc_curr = _money(line_amount_item_curr * exchange_rate)
            else:
                raise ValueError("Несоответствие валют позиций и чека.")

            total_sale_amount_doc_curr += line_amount_doc_curr

            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                stock_item_id=stock_item_id,
                imei=imei,
                quantity=quantity,
                unit_price=unit_price,
                discount=discount,
                currency=item_currency,
            )
            session.add(sale_item)

        sale.total_amount = _money(total_sale_amount_doc_curr)

        total_paid_in_sale_curr = Decimal("0.00")

        for payment in payments:
            cash_register_id = payment.get("cash_register_id")
            pay_amount = _money(_decimal(payment.get("amount")))
            pay_currency = payment.get("currency", currency).strip().upper()
            pay_rate = _validate_rate(payment.get("exchange_rate", exchange_rate))

            if pay_amount <= 0:
                raise ValueError("Сумма оплаты должна быть больше нуля.")

            CashService.adjust_register_balance(
                session=session,
                cash_register_id=cash_register_id,
                amount=pay_amount,
                transaction_type="income",
                currency=pay_currency,
                exchange_rate=pay_rate,
                description=f"Оплата продажи {sale.receipt_number}",
                sale_id=sale.id,
            )

            if pay_currency == currency:
                conv_paid = pay_amount
            elif pay_currency == "TMT" and currency == "USD":
                conv_paid = _money(pay_amount / pay_rate)
            elif pay_currency == "USD" and currency == "TMT":
                conv_paid = _money(pay_amount * pay_rate)
            else:
                raise ValueError("Несоответствие валют оплаты и чека.")

            total_paid_in_sale_curr += conv_paid

        total_paid_in_sale_curr = _money(total_paid_in_sale_curr)
        if total_paid_in_sale_curr < sale.total_amount:
            raise ValueError(f"Внесенная сумма ({total_paid_in_sale_curr} {currency}) меньше суммы чека ({sale.total_amount} {currency}).")

        session.flush()
        return sale

    @staticmethod
    def cancel_sale(
        session: Session,
        sale_id: int,
        reason: str,
        refund_cash_register_id: int,
    ) -> Sale:
        """Аудит-совместимая отмена продажи, возврат товара на склад и возврат денег из кассы."""
        sale = session.get(Sale, sale_id)
        if not sale:
            raise ValueError(f"Продажа с ID {sale_id} не найдена.")

        if sale.status == "cancelled":
            raise ValueError("Продажа уже отменена.")

        reason = str(reason).strip()
        if not reason:
            raise ValueError("Укажите причину отмены продажи.")

        sale.status = "cancelled"
        sale.cancellation_reason = reason

        sale_items = session.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id)
        ).all()

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

        CashService.adjust_register_balance(
            session=session,
            cash_register_id=refund_cash_register_id,
            amount=Decimal(str(sale.total_amount)),
            transaction_type="refund",
            currency=sale.currency,
            exchange_rate=Decimal("1.0000"),
            description=f"Возврат по чеку {sale.receipt_number}: {reason}",
            sale_id=sale.id,
        )

        session.flush()
        return sale
