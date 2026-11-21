
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
from app.services import purchase_service


@pytest.fixture
def purchase_db(tmp_path, monkeypatch):
    """Создаёт изолированную временную БД для тестов закупок."""
    database_file = tmp_path / "test_purchase.db"
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
            code="TEST_PURCHASE",
            is_active=True,
        )
        session.add(category)
        session.flush()

        item = Product(
            category_id=category.id,
            sku="TEST-PURCHASE-001",
            name="Тестовый телефон",
            stock_quantity=0,
            min_stock_quantity=0,
            is_active=True,
        )
        session.add(item)
        session.commit()

        return item.id


def test_create_purchase_without_payment(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 2,
                "unit_cost": "150.00",
            }
        ],
        currency="USD",
        exchange_rate="19.5000",
    )

    assert purchase_service.get_purchase_balance(purchase_id) == Decimal("300.00")

    with purchase_service.SessionLocal() as session:
        item = session.get(Product, product)
        assert item.stock_quantity == 2

        purchase = session.get(Purchase, purchase_id)
        assert purchase.total_amount == Decimal("300.00")


def test_create_purchase_with_mixed_payments(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "1000.00",
            }
        ],
        currency="USD",
        exchange_rate="19.5000",
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

    assert purchase_service.get_purchase_balance(purchase_id) == Decimal("250.00")

    with purchase_service.SessionLocal() as session:
        payments = session.scalars(
            select(PurchasePayment).where(
                PurchasePayment.purchase_id == purchase_id
            )
        ).all()

        assert len(payments) == 2

        movements = session.scalars(
            select(CashMovement).where(
                CashMovement.purchase_payment_id.in_(
                    [payment.id for payment in payments]
                )
            )
        ).all()

        assert len(movements) == 2


def test_add_payment_to_existing_purchase(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "1000.00",
            }
        ],
        currency="USD",
        exchange_rate="19.5000",
    )

    purchase_service.add_purchase_payment(
        purchase_id=purchase_id,
        currency="TMT",
        amount="9750.00",
        exchange_rate="19.5000",
    )

    assert purchase_service.get_purchase_balance(purchase_id) == Decimal("500.00")


def test_overpayment_is_rejected(product):
    with pytest.raises(ValueError, match="galan bergiden köp"):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": "100.00",
                }
            ],
            currency="USD",
            exchange_rate="19.5000",
            payments=[
                {
                    "currency": "TMT",
                    "amount": "2000.00",
                    "exchange_rate": "19.5000",
                }
            ],
        )

    with purchase_service.SessionLocal() as session:
        assert session.scalar(
            select(func.count()).select_from(Purchase)
        ) == 0

        item = session.get(Product, product)
        assert item.stock_quantity == 0


def test_invalid_product_rolls_back_purchase(product):
    with pytest.raises(ValueError, match="tapylmady"):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": "100.00",
                },
                {
                    "product_id": 999999,
                    "quantity": 1,
                    "unit_cost": "200.00",
                },
            ],
            currency="USD",
            exchange_rate="19.5000",
        )

    with purchase_service.SessionLocal() as session:
        assert session.scalar(
            select(func.count()).select_from(Purchase)
        ) == 0

        item = session.get(Product, product)
        assert item.stock_quantity == 0


def test_negative_quantity_is_rejected(product):
    with pytest.raises(ValueError, match="Sany"):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": -1,
                    "unit_cost": "100.00",
                }
            ],
            currency="USD",
            exchange_rate="19.5000",
        )


def test_currency_is_normalized(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "100.00",
            }
        ],
        currency=" usd ",
        exchange_rate="19.5000",
    )

    with purchase_service.SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)
        assert purchase.currency == "USD"


def test_payment_currency_is_normalized(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "100.00",
            }
        ],
        currency="USD",
        exchange_rate="19.5000",
        payments=[
            {
                "currency": " tmt ",
                "amount": "975.00",
                "exchange_rate": "19.5000",
            }
        ],
    )

    with purchase_service.SessionLocal() as session:
        payment = session.scalar(
            select(PurchasePayment).where(
                PurchasePayment.purchase_id == purchase_id
            )
        )
        assert payment.currency == "TMT"


def test_exchange_rate_is_rounded_to_four_places(product):
    purchase_id = purchase_service.create_purchase(
        items=[
            {
                "product_id": product,
                "quantity": 1,
                "unit_cost": "100.00",
            }
        ],
        currency="USD",
        exchange_rate="19.50005",
    )

    with purchase_service.SessionLocal() as session:
        purchase = session.get(Purchase, purchase_id)
        assert purchase.exchange_rate == Decimal("19.5001")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_exchange_rate_is_rejected(product, value):
    with pytest.raises(ValueError):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": "100.00",
                }
            ],
            currency="USD",
            exchange_rate=value,
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_price_is_rejected(product, value):
    with pytest.raises(ValueError):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": value,
                }
            ],
            currency="USD",
            exchange_rate="19.5000",
        )


@pytest.mark.parametrize("value", [1.5, "1.5", True, 0, -1])
def test_invalid_quantity_is_rejected(product, value):
    with pytest.raises((ValueError, TypeError)):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": value,
                    "unit_cost": "100.00",
                }
            ],
            currency="USD",
            exchange_rate="19.5000",
        )


def test_invalid_currency_is_rejected(product):
    with pytest.raises(ValueError, match="Rugsat edilýän walýutalar"):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": "100.00",
                }
            ],
            currency="EUR",
            exchange_rate="19.5000",
        )


def test_zero_exchange_rate_is_rejected(product):
    with pytest.raises(ValueError, match="noldan uly"):
        purchase_service.create_purchase(
            items=[
                {
                    "product_id": product,
                    "quantity": 1,
                    "unit_cost": "100.00",
                }
            ],
            currency="USD",
            exchange_rate="0",
        )
