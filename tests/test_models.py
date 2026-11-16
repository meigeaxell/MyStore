
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Category, Product, StockItem


@pytest.fixture
def db_session(tmp_path):
    """Создаёт временную базу данных для тестов."""
    database_file = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{database_file}")

    Base.metadata.create_all(test_engine)

    TestingSession = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    with TestingSession() as session:
        yield session

    test_engine.dispose()


def test_category_and_product_creation(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="IPHONE-17-256-BLACK",
        name="iPhone 17",
        brand="Apple",
        model="iPhone 17",
        specification="256 GB, Black",
    )

    db_session.add(product)
    db_session.commit()

    saved_product = db_session.query(Product).first()

    assert saved_product is not None
    assert saved_product.name == "iPhone 17"
    assert saved_product.sku == "IPHONE-17-256-BLACK"
    assert saved_product.category_id == category.id


def test_product_sku_must_be_unique(db_session):
    category = Category(
        name="Аксессуары",
        code="ACCESSORY",
    )

    db_session.add(category)
    db_session.commit()

    product1 = Product(
        category_id=category.id,
        sku="CASE-S25-BLACK",
        name="Чехол Samsung S25 Black",
    )

    product2 = Product(
        category_id=category.id,
        sku="CASE-S25-BLACK",
        name="Другой чехол",
    )

    db_session.add(product1)
    db_session.commit()

    db_session.add(product2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_stock_item_imei_must_be_unique(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="IPHONE-17",
        name="iPhone 17",
    )

    db_session.add(product)
    db_session.commit()

    phone1 = StockItem(
        product_id=product.id,
        imei1="123456789012345",
        condition="new",
    )

    phone2 = StockItem(
        product_id=product.id,
        imei1="123456789012345",
        condition="new",
    )

    db_session.add(phone1)
    db_session.commit()

    db_session.add(phone2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()

def test_stock_item_imei2_must_be_unique(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="SAMSUNG-S25",
        name="Samsung S25",
    )

    db_session.add(product)
    db_session.commit()

    phone1 = StockItem(
        product_id=product.id,
        imei1="111111111111111",
        imei2="222222222222222",
        condition="new",
    )

    phone2 = StockItem(
        product_id=product.id,
        imei1="333333333333333",
        imei2="222222222222222",
        condition="new",
    )

    db_session.add(phone1)
    db_session.commit()

    db_session.add(phone2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_multiple_stock_items_can_have_empty_imei2(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="XIAOMI-17",
        name="Xiaomi 17",
    )

    db_session.add(product)
    db_session.commit()

    phone1 = StockItem(
        product_id=product.id,
        imei1="444444444444444",
        imei2=None,
        condition="new",
    )

    phone2 = StockItem(
        product_id=product.id,
        imei1="555555555555555",
        imei2=None,
        condition="new",
    )

    db_session.add_all([phone1, phone2])
    db_session.commit()

    assert db_session.query(StockItem).count() == 2


def test_stock_item_requires_imei1(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="PIXEL-10",
        name="Google Pixel 10",
    )

    db_session.add(product)
    db_session.commit()

    phone = StockItem(
        product_id=product.id,
        imei1=None,
        condition="new",
    )

    db_session.add(phone)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()

def test_stock_item_default_status(db_session):
    category = Category(
        name="Новые телефоны",
        code="NEW_PHONE",
    )

    db_session.add(category)
    db_session.commit()

    product = Product(
        category_id=category.id,
        sku="IPHONE-17-PRO",
        name="iPhone 17 Pro",
    )

    db_session.add(product)
    db_session.commit()

    phone = StockItem(
        product_id=product.id,
        imei1="666666666666666",
        condition="new",
    )

    db_session.add(phone)
    db_session.commit()

    assert phone.status == "in_stock"