from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import CashMovement, Category, Product, SalePayment, StockItem
from app.models.cash_register import CashRegister, CashTransaction
from app.services.sales_service import SalesService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestingSession() as session:
        yield session
    engine.dispose()


def test_successful_sale_stock_and_cash_update(db_session):
    """Сценарий 1: Успешная продажа товара с проверкой списания остатка со склада и увеличения баланса кассы."""
    category = Category(name="Телефоны", code="PHONES")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="SAMSUNG-S24",
        name="Samsung Galaxy S24",
        stock_quantity=10,
    )
    db_session.add(product)
    db_session.commit()

    cash_tmt = CashRegister(name="Основная касса TMT", currency="TMT", balance=Decimal("1000.00"))
    db_session.add(cash_tmt)
    db_session.commit()

    items = [
        {
            "product_id": product.id,
            "quantity": 2,
            "unit_price": Decimal("3500.00"),
            "currency": "TMT",
        }
    ]
    payments = [
        {
            "cash_register_id": cash_tmt.id,
            "amount": Decimal("7000.00"),
            "currency": "TMT",
        }
    ]

    sale = SalesService.create_sale(
        session=db_session,
        items=items,
        payments=payments,
        currency="TMT",
        exchange_rate=Decimal("1.0000"),
        comment="Продажа телефона",
    )
    db_session.commit()

    assert sale.status == "completed"
    assert sale.total_amount == Decimal("7000.00")
    assert product.stock_quantity == 8
    assert cash_tmt.balance == Decimal("8000.00")

    # Проверка создания CashTransaction
    tx = db_session.scalar(select(CashTransaction).where(CashTransaction.sale_id == sale.id))
    assert tx is not None
    assert tx.transaction_type == "income"
    assert tx.amount == Decimal("7000.00")
    assert tx.currency == "TMT"


def test_sale_with_mixed_payment_currencies(db_session):
    """Сценарий 2: Продажа со смешанной оплатой в двух валютах (USD + TMT) и проверка записей в CashTransaction."""
    category = Category(name="Смартфоны", code="SMART")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="IPHONE-16",
        name="iPhone 16",
        stock_quantity=5,
    )
    db_session.add(product)
    db_session.commit()

    cash_usd = CashRegister(name="Касса USD", currency="USD", balance=Decimal("500.00"))
    cash_tmt = CashRegister(name="Касса TMT", currency="TMT", balance=Decimal("1000.00"))
    db_session.add_all([cash_usd, cash_tmt])
    db_session.commit()

    # Товар стоит 1000 USD
    items = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("1000.00"),
            "currency": "USD",
        }
    ]
    # Оплата: 400 USD в кассу USD + 2160 TMT в кассу TMT по курсу 3.6 (600 USD)
    payments = [
        {
            "cash_register_id": cash_usd.id,
            "amount": Decimal("400.00"),
            "currency": "USD",
        },
        {
            "cash_register_id": cash_tmt.id,
            "amount": Decimal("2160.00"),
            "currency": "TMT",
            "exchange_rate": Decimal("3.6000"),
        },
    ]

    sale = SalesService.create_sale(
        session=db_session,
        items=items,
        payments=payments,
        currency="USD",
        exchange_rate=Decimal("3.6000"),
    )
    db_session.commit()

    assert sale.total_amount == Decimal("1000.00")
    assert cash_usd.balance == Decimal("900.00")
    assert cash_tmt.balance == Decimal("3160.00")

    transactions = db_session.scalars(
        select(CashTransaction).where(CashTransaction.sale_id == sale.id)
    ).all()
    assert len(transactions) == 2
    assert {tx.currency for tx in transactions} == {"USD", "TMT"}


def test_sale_out_of_stock_and_imei_reuse_fails(db_session):
    """Сценарий 3: Попытка продать товар вне наличия / повторный проданный IMEI (исключение, баланс кассы не меняется)."""
    category = Category(name="Телефоны", code="PH")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="PIXEL-9",
        name="Pixel 9",
        stock_quantity=0,
    )
    db_session.add(product)
    db_session.commit()

    cash = CashRegister(name="Касса", currency="USD", balance=Decimal("5000.00"))
    db_session.add(cash)
    db_session.commit()

    # 1. Попытка продажи товара с нулевым остатком
    items = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("800.00"),
            "currency": "USD",
        }
    ]
    payments = [
        {
            "cash_register_id": cash.id,
            "amount": Decimal("800.00"),
            "currency": "USD",
        }
    ]

    with pytest.raises(ValueError, match="ýeterlik däl"):
        SalesService.create_sale(
            session=db_session,
            items=items,
            payments=payments,
            currency="USD",
            exchange_rate=Decimal("1.0000"),
        )
    db_session.rollback()

    assert cash.balance == Decimal("5000.00")

    # 2. Попытка повторной продажи уже проданного IMEI
    product.stock_quantity = 2
    db_session.commit()

    stock_item = StockItem(
        product_id=product.id,
        imei1="111222333444555",
        condition="new",
        status="sold",  # Уже продан
    )
    db_session.add(stock_item)
    db_session.commit()

    items_imei = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("800.00"),
            "imei": "111222333444555",
            "currency": "USD",
        }
    ]

    with pytest.raises(ValueError, match="eýýäm satyldy ýa-da elýeterli däl"):
        SalesService.create_sale(
            session=db_session,
            items=items_imei,
            payments=payments,
            currency="USD",
            exchange_rate=Decimal("1.0000"),
        )
    db_session.rollback()

    assert cash.balance == Decimal("5000.00")


def test_cancel_sale_returns_stock_refunds_and_prevents_double(db_session):
    """Сценарий 4: Отмена продажи (возврат товара на склад, списание денег из кассы, причина, защита от повторной отмены)."""
    category = Category(name="Планшеты", code="PAD")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="IPAD-PRO",
        name="iPad Pro",
        stock_quantity=3,
    )
    db_session.add(product)
    db_session.commit()

    stock_item = StockItem(
        product_id=product.id,
        imei1="555444333222111",
        condition="new",
        status="in_stock",
    )
    db_session.add(stock_item)

    cash = CashRegister(name="Касса USD", currency="USD", balance=Decimal("1000.00"))
    db_session.add(cash)
    db_session.commit()

    items = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("1200.00"),
            "imei": "555444333222111",
            "currency": "USD",
        }
    ]
    payments = [
        {
            "cash_register_id": cash.id,
            "amount": Decimal("1200.00"),
            "currency": "USD",
        }
    ]

    sale = SalesService.create_sale(
        session=db_session,
        items=items,
        payments=payments,
        currency="USD",
        exchange_rate=Decimal("1.0000"),
    )
    db_session.commit()

    assert product.stock_quantity == 2
    assert stock_item.status == "sold"
    assert cash.balance == Decimal("2200.00")

    # Отмена продажи
    reason = "Клиент отказался от покупки (ошибка в модели)"
    SalesService.cancel_sale(
        session=db_session,
        sale_id=sale.id,
        reason=reason,
        refund_cash_register_id=cash.id,
    )
    db_session.commit()

    assert sale.status == "cancelled"
    assert sale.cancellation_reason == reason
    assert product.stock_quantity == 3
    assert stock_item.status == "in_stock"
    assert cash.balance == Decimal("1000.00")

    # Проверка создания транзакции возврата (refund) в CashTransaction
    refund_tx = db_session.scalar(
        select(CashTransaction).where(
            CashTransaction.sale_id == sale.id,
            CashTransaction.transaction_type == "refund",
        )
    )
    assert refund_tx is not None
    assert refund_tx.amount == Decimal("1200.00")

    # Попытка повторной отмены уже отмененного чека
    with pytest.raises(ValueError, match="eýýäm ýatyryldy"):
        SalesService.cancel_sale(
            session=db_session,
            sale_id=sale.id,
            reason="Вторая попытка отмены",
            refund_cash_register_id=cash.id,
        )


def test_ensure_default_registers_creates_usd_and_tmt(db_session):
    """Проверка автоматического создания касс USD и TMT, если база пуста."""
    regs = SalesService.ensure_default_registers(db_session)
    db_session.commit()

    assert set(regs.keys()) == {"USD", "TMT"}
    assert regs["USD"].balance == Decimal("0.00")
    assert regs["TMT"].balance == Decimal("0.00")


def test_duplicate_imei_in_same_sale_is_rejected(db_session):
    """Защита от повторного добавления одного и того же IMEI (в т.ч. через imei1 и imei2) в один чек."""
    category = Category(name="Телефоны", code="PHONES")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="DUAL-SIM-PHONE",
        name="Dual SIM Phone",
        stock_quantity=5,
    )
    db_session.add(product)
    db_session.commit()

    stock_item = StockItem(
        product_id=product.id,
        imei1="111000111000111",
        imei2="222000222000222",
        condition="new",
        status="in_stock",
    )
    db_session.add(stock_item)

    cash = CashRegister(name="Касса USD", currency="USD", balance=Decimal("1000.00"))
    db_session.add(cash)
    db_session.commit()

    items = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("500.00"),
            "imei": "111000111000111",
            "currency": "USD",
        },
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("500.00"),
            "imei": "222000222000222",
            "currency": "USD",
        },
    ]
    payments = [
        {
            "cash_register_id": cash.id,
            "amount": Decimal("1000.00"),
            "currency": "USD",
        }
    ]

    with pytest.raises(ValueError, match="çekde bir gezekden köp görkezildi"):
        SalesService.create_sale(
            session=db_session,
            items=items,
            payments=payments,
            currency="USD",
        )


def test_sale_records_sale_payments_movements_and_change(db_session):
    """Проверка записи SalePayment, CashMovement и учета сдачи при переплате."""
    category = Category(name="Аксессуары", code="ACC")
    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="CHARGER-20W",
        name="Charger 20W",
        stock_quantity=10,
    )
    db_session.add(product)

    cash_tmt = CashRegister(name="Касса TMT", currency="TMT", balance=Decimal("500.00"))
    db_session.add(cash_tmt)
    db_session.commit()

    items = [
        {
            "product_id": product.id,
            "quantity": 1,
            "unit_price": Decimal("150.00"),
            "currency": "TMT",
        }
    ]
    payments = [
        {
            "cash_register_id": cash_tmt.id,
            "amount": Decimal("200.00"),
            "currency": "TMT",
        }
    ]

    sale = SalesService.create_sale(
        session=db_session,
        items=items,
        payments=payments,
        currency="TMT",
        exchange_rate=Decimal("19.5000"),
    )
    db_session.commit()

    # Баланс должен вырасти ровно на сумму чека (150), т.к. 200 приход и 50 сдача
    assert cash_tmt.balance == Decimal("650.00")

    sale_payments = db_session.scalars(
        select(SalePayment).where(SalePayment.sale_id == sale.id)
    ).all()
    assert len(sale_payments) == 1
    assert sale_payments[0].amount == Decimal("200.00")

    movements = db_session.scalars(
        select(CashMovement).where(CashMovement.sale_id == sale.id)
    ).all()
    assert {m.movement_type for m in movements} == {"sale_payment", "sale_change"}

    # Отмена чека без явного указания кассы должна вернуть ровно чистую сумму (150 TMT)
    SalesService.cancel_sale(
        session=db_session,
        sale_id=sale.id,
        reason="Возврат аксессуара",
    )
    db_session.commit()

    assert cash_tmt.balance == Decimal("500.00")
    assert product.stock_quantity == 10

