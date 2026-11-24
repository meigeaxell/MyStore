
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.cash_movement import CashMovement
from app.models.category import Category
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_payment import PurchasePayment
from app.models.purchase_refund import PurchaseRefund
from app.services import purchase_service


@pytest.fixture
def purchase_db(tmp_path, monkeypatch):
    database_file = tmp_path / "test_cancellation.db"
    test_engine = create_engine(f"sqlite:///{database_file}")

    Base.metadata.create_all(test_engine)

    TestingSession = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    monkeypatch.setattr(purchase_service, "SessionLocal", TestingSession)

    yield TestingSession

    test_engine.dispose()


@pytest.fixture
def product(purchase_db):
    with purchase_db() as session:
        category = Category(
            name="Тестовая категория",
            code="TEST_CANCEL",
            is_active=True,
        )
        session.add(category)
        session.flush()

        item = Product(
            category_id=category.id,
            sku="TEST-CANCEL-001",
            name="Тестовый телефон",
            stock_quantity=0,
            min_stock_quantity=0,
            is_active=True,
        )
        session.add(item)
        session.commit()

        return item.id


def create_test_purchase(product_id, quantity=1, payments=None, supplier_name="Test Supplier"):
    return purchase_service.create_purchase(
        items=[
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_cost": "1000.00",
            }
        ],
        currency="USD",
        exchange_rate="19.5000",
        payments=payments,
        supplier_name=supplier_name,
    )


def test_cancel_purchase_returns_stock_and_clears_store_debt(product):
    purchase_id = create_test_purchase(product, quantity=2)

    purchase_service.cancel_purchase(
        purchase_id,
        "Ошибка при оформлении закупки",
    )

    assert purchase_service.get_purchase_balance(purchase_id) == Decimal(
        "0.00"
    )
    assert purchase_service.get_supplier_debt(purchase_id) == Decimal(
        "0.00"
    )

    with purchase_service.SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)
        item = session.get(Product, product)

        assert purchase.status == "cancelled"
        assert purchase.cancelled_at is not None
        assert purchase.cancellation_reason == (
            "Ошибка при оформлении закупки"
        )
        assert item.stock_quantity == 0


def test_cancel_purchase_creates_supplier_debt_from_payments(product):
    purchase_id = create_test_purchase(
        product,
        payments=[
            {
                "currency": "USD",
                "amount": "500.00",
                "exchange_rate": "19.5000",
            },
            {
                "currency": "TMT",
                "amount": "4875.00",
                "exchange_rate": "19.5000",
            },
        ],
    )

    purchase_service.cancel_purchase(
        purchase_id,
        "Поставщик не смог выполнить заказ",
    )

    assert purchase_service.get_purchase_balance(purchase_id) == Decimal(
        "0.00"
    )
    assert purchase_service.get_supplier_debt(purchase_id) == Decimal(
        "750.00"
    )

    with purchase_service.SessionLocal() as session:
        assert session.scalar(
            select(func.count()).select_from(PurchasePayment)
        ) == 2

        assert session.scalar(
            select(func.count()).select_from(CashMovement)
        ) == 2


def test_supplier_refund_reduces_debt_and_increases_cash(product):
    purchase_id = create_test_purchase(
        product,
        payments=[
            {
                "currency": "USD",
                "amount": "500.00",
                "exchange_rate": "19.5000",
            },
            {
                "currency": "TMT",
                "amount": "4875.00",
                "exchange_rate": "19.5000",
            },
        ],
    )

    purchase_service.cancel_purchase(
        purchase_id,
        "Возврат закупки",
    )

    refund_id = purchase_service.add_purchase_refund(
        purchase_id=purchase_id,
        currency="TMT",
        amount="10000.00",
        exchange_rate="20.0000",
        description="Частичный возврат от поставщика",
    )

    assert purchase_service.get_supplier_debt(purchase_id) == Decimal(
        "250.00"
    )

    with purchase_service.SessionLocal() as session:
        refund = session.get(PurchaseRefund, refund_id)

        movement = session.scalar(
            select(CashMovement).where(
                CashMovement.purchase_refund_id == refund_id
            )
        )

        assert refund.currency == "TMT"
        assert refund.amount == Decimal("10000.00")
        assert refund.exchange_rate == Decimal("20.0000")

        assert movement is not None
        assert movement.movement_type == "purchase_refund"
        assert movement.currency == "TMT"
        assert movement.amount == Decimal("10000.00")


def test_supplier_cannot_refund_more_than_debt(product):
    purchase_id = create_test_purchase(
        product,
        payments=[
            {
                "currency": "USD",
                "amount": "500.00",
                "exchange_rate": "19.5000",
            },
        ],
    )

    purchase_service.cancel_purchase(
        purchase_id,
        "Проверка переплаты",
    )

    with pytest.raises(ValueError, match="bergisinden köp"):
        purchase_service.add_purchase_refund(
            purchase_id=purchase_id,
            currency="TMT",
            amount="12000.00",
            exchange_rate="20.0000",
        )

    assert purchase_service.get_supplier_debt(purchase_id) == Decimal(
        "500.00"
    )

    with purchase_service.SessionLocal() as session:
        assert session.scalar(
            select(func.count()).select_from(PurchaseRefund)
        ) == 0


def test_cannot_cancel_purchase_if_stock_is_insufficient(product):
    purchase_id = create_test_purchase(product, quantity=2)

    with purchase_service.SessionLocal() as session:
        item = session.get(Product, product)
        item.stock_quantity = 1
        session.commit()

    with pytest.raises(ValueError, match="eýýäm çykarylan"):
        purchase_service.cancel_purchase(
            purchase_id,
            "Попытка аннулирования",
        )

    with purchase_service.SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)
        item = session.get(Product, product)

        assert purchase.status == "active"
        assert item.stock_quantity == 1


def test_cannot_add_payment_to_cancelled_purchase(product):
    purchase_id = create_test_purchase(product)

    purchase_service.cancel_purchase(
        purchase_id,
        "Закупка отменена",
    )

    with pytest.raises(ValueError, match="Ýatyrylan alyş"):
        purchase_service.add_purchase_payment(
            purchase_id=purchase_id,
            currency="USD",
            amount="100.00",
            exchange_rate="19.5000",
        )


def test_refund_is_allowed_only_after_cancellation(product):
    purchase_id = create_test_purchase(
        product,
        payments=[
            {
                "currency": "USD",
                "amount": "100.00",
                "exchange_rate": "19.5000",
            },
        ],
    )

    with pytest.raises(ValueError, match="diňe ýatyrylan alyş"):
        purchase_service.add_purchase_refund(
            purchase_id=purchase_id,
            currency="USD",
            amount="50.00",
            exchange_rate="19.5000",
        )


def test_multiple_lines_for_same_product_are_returned_together(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "100.00",
            },
            {
                "product_id": product,
                "quantity": 2,
                "unit_cost": "100.00",
            },
        ],
        currency="USD",
        exchange_rate="19.5000",
    )

    purchase_service.cancel_purchase(
        purchase_id,
        "Проверка одинаковых позиций",
    )

    with purchase_service.SessionLocal() as session:
        item = session.get(Product, product)
        assert item.stock_quantity == 0
