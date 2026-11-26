"""Тесты новых возможностей: штрихкоды, редактирование StockItem, архивация, касса и долги, ZIP-обновление."""
import zipfile
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.repositories.product_repository as product_repo
import app.services.settings_service as settings_mod
from app.database.base import Base
from app.models.cash_register import CashRegister
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.services import purchase_service
from app.services.finance_service import FinanceService
from app.services.sales_service import SalesService
from app.services.update_service import UpdateService


@pytest.fixture()
def feat_db(tmp_path, monkeypatch):
    db_file = tmp_path / "feat_test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(product_repo, "SessionLocal", session_factory)
    monkeypatch.setattr(purchase_service, "SessionLocal", session_factory)
    monkeypatch.setattr(settings_mod, "SessionLocal", session_factory)

    with session_factory() as session, session.begin():
        cat = Category(name="Smartfonlar", code="PHONE", is_active=True)
        cat_acc = Category(name="Aksessuarlar", code="ACC", is_active=True)
        session.add_all([cat, cat_acc])
        session.flush()
        ids = {"cat_phone": cat.id, "cat_acc": cat_acc.id}

    yield session_factory, ids
    engine.dispose()


def test_product_barcode_save_lookup_and_duplicate_guard(feat_db):
    _sf, ids = feat_db
    p1 = product_repo.save_product(
        product_id=None,
        name="Hoco 20W Adapter",
        category_id=ids["cat_acc"],
        brand="Hoco",
        model="C80",
        specification="Gara",
        barcode="6931474751234",
        stock_quantity=5,
        default_cost="10.00",
        default_cost_currency="USD",
    )
    assert p1.barcode == "6931474751234"

    found = product_repo.find_product_by_barcode("6931474751234")
    assert found is not None
    assert found.id == p1.id

    # Общий штрихкод разрешён для другого товара / цвета
    p2 = product_repo.save_product(
        product_id=None,
        name="Hoco 20W Adapter Ak",
        category_id=ids["cat_acc"],
        brand="Hoco",
        model="C80",
        specification="Ak",
        barcode="6931474751234",
        stock_quantity=3,
        default_cost="10.00",
        default_cost_currency="USD",
    )
    assert p2.id != p1.id
    all_found = product_repo.find_products_by_barcode("6931474751234")
    assert {p.id for p in all_found} == {p1.id, p2.id}

    # Совпадающие название, модель, категория, характеристики и себестоимость -> суммирование остатка
    merged = product_repo.save_product(
        product_id=None,
        name="Hoco 20W Adapter",
        category_id=ids["cat_acc"],
        brand="Hoco",
        model="C80",
        specification="Gara",
        barcode="6931474751234",
        stock_quantity=4,
        default_cost="10.00",
        default_cost_currency="USD",
    )
    assert merged.id == p1.id
    assert merged.stock_quantity == 9
    assert getattr(merged, "_merged_duplicate", False) is True

    # Другая себестоимость -> отдельный товар (не склеивается)
    diff_cost = product_repo.save_product(
        product_id=None,
        name="Hoco 20W Adapter",
        category_id=ids["cat_acc"],
        brand="Hoco",
        model="C80",
        specification="Gara",
        barcode="6931474751234",
        stock_quantity=2,
        default_cost="12.00",
        default_cost_currency="USD",
    )
    assert diff_cost.id != p1.id
    assert diff_cost.stock_quantity == 2


def test_edit_and_delete_stock_item_with_stock_sync(feat_db):
    session_factory, ids = feat_db
    p1 = product_repo.save_product(None, "iPhone 15 128GB", ids["cat_phone"])
    p2 = product_repo.save_product(None, "iPhone 15 256GB", ids["cat_phone"])

    st = product_repo.register_stock_item(
        product_id=p1.id,
        imei1="356938035643809",
        condition="new",
        unit_cost=Decimal("700.00"),
        cost_currency="USD",
    )
    with session_factory() as session:
        assert session.get(Product, p1.id).stock_quantity == 1

    # Полное редактирование + перенос на другую модель p2
    updated = product_repo.update_stock_item(
        stock_item_id=st.id,
        product_id=p2.id,
        imei1="356938035643809",
        imei2="356938035643817",
        serial_number="SN-XYZ-99",
        condition="used",
        status="in_stock",
        unit_cost=Decimal("650.00"),
        cost_currency="USD",
        cost_exchange_rate=Decimal("19.5000"),
        acquisition_source="direct_buyout",
        notes="Batareýa 92%",
    )
    assert updated.product_id == p2.id
    assert updated.condition == "used"
    assert updated.imei2 == "356938035643817"
    assert updated.serial_number == "SN-XYZ-99"
    assert updated.notes == "Batareýa 92%"

    with session_factory() as session:
        assert session.get(Product, p1.id).stock_quantity == 0
        assert session.get(Product, p2.id).stock_quantity == 1

    # Удаление StockItem уменьшает остаток p2 до 0
    product_repo.delete_stock_item(st.id)
    with session_factory() as session:
        assert session.get(StockItem, st.id) is None
        assert session.get(Product, p2.id).stock_quantity == 0


def test_archive_product_with_stock_and_restore(feat_db):
    _sf, ids = feat_db
    p = product_repo.save_product(None, "iPhone 14", ids["cat_phone"], stock_quantity=3)
    product_repo.register_stock_item(p.id, imei1="356938035643809")

    # Архивация разрешена даже при наличии остатков и IMEI
    product_repo.deactivate_product(p.id, force=True)

    active_list, _ = product_repo.list_products_inventory(include_archived=False)
    assert all(item["id"] != p.id for item in active_list)

    all_list, _ = product_repo.list_products_inventory(include_archived=True)
    archived = next(item for item in all_list if item["id"] == p.id)
    assert archived["is_active"] is False
    assert archived["quantity"] >= 1

    # Восстановление из архива
    product_repo.restore_product(p.id)
    active_after, _ = product_repo.list_products_inventory(include_archived=False)
    assert any(item["id"] == p.id for item in active_after)


def test_cash_totals_zeroing_and_debt_settlements(feat_db):
    session_factory, ids = feat_db
    p = product_repo.save_product(None, "Case 16PM", ids["cat_acc"], stock_quantity=10)

    with session_factory() as session, session.begin():
        reg_usd = CashRegister(name="Kassa USD", currency="USD", balance=Decimal("100.00"))
        reg_tmt = CashRegister(name="Kassa TMT", currency="TMT", balance=Decimal("1950.00"))
        session.add_all([reg_usd, reg_tmt])
        session.flush()

        # Общий просчёт всей кассы (100 USD + 1950 TMT по курсу 19.5 = 3900 TMT / 200 USD)
        totals = FinanceService.get_combined_cash_totals(session, Decimal("19.5000"))
        assert totals["total_in_tmt"] == Decimal("3900.00")
        assert totals["total_in_usd"] == Decimal("200.00")

        # Продажа в долг клиенту (300 TMT, оплачено 100 TMT, долг 200 TMT)
        sale = SalesService.create_sale(
            session=session,
            items=[{"product_id": p.id, "quantity": 1, "unit_price": Decimal("300.00"), "currency": "TMT"}],
            payments=[{"cash_register_id": reg_tmt.id, "amount": Decimal("100.00"), "currency": "TMT"}],
            currency="TMT",
            exchange_rate=Decimal("19.5000"),
            customer_name="Merdan",
            allow_credit=True,
        )
        assert SalesService.get_customer_debt(session, sale) == Decimal("200.00")
        bal_before_zero_debt = reg_tmt.balance

        # Обнуление долга без кассы (with_cash=False) -> долг 0, баланс кассы не меняется
        cleared = FinanceService.settle_or_zero_customer_debt(
            session, sale.id, with_cash=False, reason="Ylalaşyk boýunça öçürildi"
        )
        assert cleared == Decimal("200.00")
        assert SalesService.get_customer_debt(session, sale) == Decimal("0.00")
        assert reg_tmt.balance == bal_before_zero_debt

        # Обнуление кассы USD -> баланс 0.00
        zeroed_usd = FinanceService.zero_cash_register(session, "USD", Decimal("19.5000"), "Eýesi aldy")
        assert zeroed_usd == Decimal("100.00")
        assert reg_usd.balance == Decimal("0.00")

    # Закупка в долг поставщику + обнуление долга поставщику
    pur_id = purchase_service.create_purchase(
        items=[{"product_id": p.id, "quantity": 2, "unit_cost": "50.00"}],
        currency="USD",
        exchange_rate="19.5000",
        supplier_name="Supplier A",
    )
    assert purchase_service.get_purchase_balance(pur_id) == Decimal("100.00")
    with session_factory() as session, session.begin():
        FinanceService.settle_or_zero_supplier_debt(session, pur_id, with_cash=False)
    assert purchase_service.get_purchase_balance(pur_id) == Decimal("0.00")


def test_update_zip_inspection(tmp_path):
    good_zip = tmp_path / "MobileStore-Windows-x64-v1.1.0.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("MobileStore/MobileStore.exe", b"MZ")
        zf.writestr("MobileStore/_internal/readme.txt", b"ok")

    ok, _msg, prefix = UpdateService.inspect_update_zip(good_zip)
    assert ok is True
    assert prefix == "MobileStore/"

    bad_zip = tmp_path / "not_app.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("random.txt", b"hello")
    ok_bad, _msg_bad, _ = UpdateService.inspect_update_zip(bad_zip)
    assert ok_bad is False
