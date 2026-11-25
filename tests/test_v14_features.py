"""Тесты ключевых возможностей v1.4.0:
- постоянные системные категории Telefon Täze и Telefon B/U + защита от удаления/переименования;
- самостоятельный учёт телефонов по IMEI (без количественных остатков, скрытие со склада после продажи);
- закупка без поставщика = личный источник (Şahsy çeşme) без долга;
- буферная очередь приёмки (Известные / Неизвестные / Телефоны IMEI) и WebSocket queue_incoming_item.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.repositories import product_repository
from app.services import (
    incoming_queue_service,
    mobile_protocol,
    purchase_service,
    settings_service,
)
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.services.sales_service import SalesService


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(product_repository, "SessionLocal", session_factory)
    monkeypatch.setattr(purchase_service, "SessionLocal", session_factory)
    monkeypatch.setattr(incoming_queue_service, "SessionLocal", session_factory)
    monkeypatch.setattr(mobile_protocol, "SessionLocal", session_factory)
    monkeypatch.setattr(settings_service, "SessionLocal", session_factory)

    return session_factory


def test_system_phone_categories_created_and_protected(isolated_db):
    cat_ids = product_repository.ensure_system_phone_categories()
    assert "new" in cat_ids and "used" in cat_ids

    with isolated_db() as session:
        c_new = session.get(Category, cat_ids["new"])
        c_used = session.get(Category, cat_ids["used"])
        assert c_new is not None and c_new.name == "Telefon Täze" and c_new.code == "PHONE_NEW"
        assert c_used is not None and c_used.name == "Telefon B/U" and c_used.code == "PHONE_USED"

    with pytest.raises(ValueError, match="Hemişelik"):
        product_repository.rename_category(cat_ids["new"], "Other Name")

    with pytest.raises(ValueError, match="Hemişelik"):
        product_repository.deactivate_category(cat_ids["used"])


def test_standalone_phone_lifecycle_and_hides_after_sale(isolated_db):
    prod, st = product_repository.register_standalone_phone(
        model_name="iPhone 15 Pro Max",
        memory="256GB",
        color="Natural Titanium",
        imei1="354892100000111",
        imei2="354892100000112",
        serial_number="SN15PM001",
        condition="used",
        battery_health="91%",
        cosmetic_condition="Arassa, çyzyk ýok",
        unit_cost=Decimal("820.00"),
        cost_currency="USD",
        cost_exchange_rate=Decimal("19.5000"),
    )

    assert prod.is_phone_unit is True
    assert prod.stock_quantity == 1
    assert st.memory == "256GB"
    assert st.color == "Natural Titanium"
    assert st.battery_health == "91%"
    assert st.cosmetic_condition == "Arassa, çyzyk ýok"

    # В активном списке склада телефон виден в категории Telefon B/U
    active_list, _ = product_repository.list_products_inventory(include_archived=False)
    assert len(active_list) == 1
    assert active_list[0]["category"] == "Telefon B/U"
    assert active_list[0]["is_phone_unit"] is True
    assert active_list[0]["phone_sold"] is False

    # Обновляем состояние на Täze -> категория автоматически меняется на Telefon Täze
    updated = product_repository.update_standalone_phone(
        stock_item_id=st.id,
        model_name="iPhone 15 Pro Max",
        imei1="354892100000111",
        memory="256GB",
        color="Black Titanium",
        condition="new",
        unit_cost=Decimal("950.00"),
        cost_currency="USD",
    )
    assert updated.condition == "new"
    assert updated.battery_health is None  # для нового телефона очищается

    active_list2, _ = product_repository.list_products_inventory(include_archived=False)
    assert active_list2[0]["category"] == "Telefon Täze"

    # Продаём телефон -> исчезает из активного склада, но история чека сохранена!
    with isolated_db() as session, session.begin():
        sale = SalesService.create_sale(
            session=session,
            items=[
                {
                    "product_id": prod.id,
                    "imei": "354892100000111",
                    "quantity": 1,
                    "unit_price": Decimal("1050.00"),
                    "currency": "USD",
                }
            ],
            payments=[
                {
                    "currency": "USD",
                    "amount": Decimal("1050.00"),
                    "exchange_rate": Decimal("19.5000"),
                }
            ],
            currency="USD",
            exchange_rate=Decimal("19.5000"),
        )
        sale_id = sale.id

    active_after_sale, _ = product_repository.list_products_inventory(include_archived=False)
    assert active_after_sale == []

    # Проверка истории: запись StockItem осталась со статусом sold
    with isolated_db() as session:
        st_sold = session.get(StockItem, st.id)
        assert st_sold is not None
        assert st_sold.status == "sold"
        assert sale_id > 0


def test_empty_supplier_purchase_has_no_debt_and_is_personal_source(isolated_db):
    cat = product_repository.create_category("Çehol")
    prod = product_repository.save_product(
        product_id=None,
        name="16 Pro Max",
        category_id=cat.id,
        brand="Blueo",
    )

    # Закупка с пустым поставщиком (без оплаты) -> личный источник, долг 0.00
    personal_pid = purchase_service.create_purchase(
        items=[{"product_id": prod.id, "quantity": 5, "unit_cost": "10.00"}],
        currency="USD",
        exchange_rate="19.5000",
        supplier_name="",
    )
    assert purchase_service.get_purchase_balance(personal_pid) == Decimal("0.00")

    # Закупка с реальным поставщиком (без оплаты) -> долг 50.00
    sup_pid = purchase_service.create_purchase(
        items=[{"product_id": prod.id, "quantity": 5, "unit_cost": "10.00"}],
        currency="USD",
        exchange_rate="19.5000",
        supplier_name="Bazar Optom",
    )
    assert purchase_service.get_purchase_balance(sup_pid) == Decimal("50.00")

    with isolated_db() as session:
        debts = FinanceService.get_all_outstanding_balances(session)
        assert debts["supplier_payables"]["USD"] == Decimal("50.00")

        open_payables = FinanceService.get_supplier_payables_list(session, include_paid=False)
        assert len(open_payables) == 1
        assert open_payables[0]["supplier_name"] == "Bazar Optom"

        all_payables = FinanceService.get_supplier_payables_list(session, include_paid=True)
        personal_row = next(r for r in all_payables if r["purchase_id"] == personal_pid)
        assert personal_row["supplier_name"] == "Şahsy çeşme"
        assert personal_row["store_debt_to_supplier"] == Decimal("0.00")

        sup_report = ReportService.get_supplier_report(session)
        rep_personal = next(r for r in sup_report if r["supplier_name"] == "Şahsy çeşme")
        assert rep_personal["debt_usd"] == Decimal("0.00")


def test_incoming_queue_known_unknown_and_phone_flow(isolated_db):
    cat = product_repository.create_category("Çehol")
    known_prod = product_repository.save_product(
        product_id=None,
        name="14 Pro Max",
        category_id=cat.id,
        brand="Blueo",
        barcode="6931474700011",
    )

    processor = mobile_protocol.MobileProtocolProcessor()

    # 1. Известный штрихкод сканируется 2 раза -> склеивается в 1 строку (qty=2)
    for idx in (1, 2):
        resp, _ = processor.handle_message(
            {
                "protocol_version": 1,
                "type": "queue_incoming_item",
                "request_id": f"req-known-{idx}",
                "device_id": "phone-1",
                "payload": {"mode": "quantity", "barcode": "6931474700011", "quantity": 1},
            },
            is_authenticated=True,
        )
        assert resp["ok"] is True
        assert resp["type"] == "incoming_queued"
        assert resp["data"]["item_kind"] == "known"

    # 2. Неизвестный штрихкод сканируется 2 раза -> склеивается в 'unknown' (qty=2)
    for idx in (1, 2):
        resp, _ = processor.handle_message(
            {
                "protocol_version": 1,
                "type": "queue_incoming_item",
                "request_id": f"req-unk-{idx}",
                "device_id": "phone-1",
                "payload": {"mode": "quantity", "barcode": "6931474799999", "quantity": 1},
            },
            is_authenticated=True,
        )
        assert resp["ok"] is True
        assert resp["data"]["item_kind"] == "unknown"

    # 3. Телефон по IMEI -> попадает в 'phone_imei', дубликат IMEI отклоняется
    resp_p, _ = processor.handle_message(
        {
            "protocol_version": 1,
            "type": "queue_incoming_item",
            "request_id": "req-phone-1",
            "device_id": "phone-1",
            "payload": {
                "mode": "imei",
                "imei1": "354892100000777",
                "condition": "new",
                "model_hint": "16 Pro 256 Black",
            },
        },
        is_authenticated=True,
    )
    assert resp_p["ok"] is True
    assert resp_p["data"]["item_kind"] == "phone_imei"

    resp_dup, _ = processor.handle_message(
        {
            "protocol_version": 1,
            "type": "queue_incoming_item",
            "request_id": "req-phone-dup",
            "device_id": "phone-1",
            "payload": {"mode": "imei", "imei1": "354892100000777"},
        },
        is_authenticated=True,
    )
    assert resp_dup["ok"] is False

    counts = incoming_queue_service.count_queue_items()
    assert counts == {"known": 1, "unknown": 1, "phone_imei": 1, "total": 3}

    # Проводим все 3 вкладки на ПК
    known_rows = incoming_queue_service.list_queue_items("known")
    assert known_rows[0]["quantity"] == 2
    incoming_queue_service.commit_known_items(
        queue_ids=[known_rows[0]["id"]],
        supplier_name="",
        currency="USD",
        exchange_rate=Decimal("19.5000"),
        overrides={known_rows[0]["id"]: {"quantity": 3, "unit_cost": Decimal("4.50")}},
    )

    unk_rows = incoming_queue_service.list_queue_items("unknown")
    assert unk_rows[0]["quantity"] == 2
    new_pid, _ = incoming_queue_service.commit_unknown_item(
        queue_id=unk_rows[0]["id"],
        name="16 Pro",
        category_id=cat.id,
        brand="Hoco",
        quantity=2,
        unit_cost=Decimal("3.00"),
        currency="USD",
        exchange_rate=Decimal("19.5000"),
    )

    phone_rows = incoming_queue_service.list_queue_items("phone_imei")
    phone_pid, phone_st_id = incoming_queue_service.commit_phone_item(
        queue_id=phone_rows[0]["id"],
        model_name="iPhone 16 Pro",
        memory="256GB",
        color="Black Titanium",
        imei1="354892100000777",
        condition="new",
        unit_cost=Decimal("1050.00"),
        currency="USD",
        exchange_rate=Decimal("19.5000"),
    )

    assert incoming_queue_service.count_queue_items()["total"] == 0

    with isolated_db() as session:
        assert session.get(Product, known_prod.id).stock_quantity == 3
        assert session.get(Product, new_pid).stock_quantity == 2
        p_phone = session.get(Product, phone_pid)
        st_phone = session.get(StockItem, phone_st_id)
        assert p_phone.is_phone_unit is True
        assert st_phone.imei1 == "354892100000777"
        assert st_phone.memory == "256GB"
        assert session.scalar(select(Category.name).where(Category.id == p_phone.category_id)) == "Telefon Täze"


def test_cancel_sale_refunds_exact_mixed_cash_and_handles_simurg_and_insufficient_cash(isolated_db):
    cat = product_repository.create_category("Çehol")
    prod = product_repository.save_product(
        product_id=None,
        name="16 Pro",
        category_id=cat.id,
        stock_quantity=10,
    )

    with isolated_db() as session, session.begin():
        regs = SalesService.ensure_default_registers(session)
        regs["USD"].balance = Decimal("100.00")
        regs["TMT"].balance = Decimal("1000.00")

        # 1. Смешанная продажа: чек на 2000 TMT -> оплачено 50 USD (975 TMT) + 1100 TMT -> сдача 75 TMT
        # Чистый приход: +50 USD в USD кассу, +1025 TMT в TMT кассу
        sale = SalesService.create_sale(
            session=session,
            items=[{"product_id": prod.id, "quantity": 2, "unit_price": Decimal("1000.00"), "currency": "TMT"}],
            payments=[
                {"currency": "USD", "amount": Decimal("50.00"), "exchange_rate": Decimal("19.5000")},
                {"currency": "TMT", "amount": Decimal("1100.00"), "exchange_rate": Decimal("19.5000")},
            ],
            currency="TMT",
            exchange_rate=Decimal("19.5000"),
        )
        assert regs["USD"].balance == Decimal("150.00")
        assert regs["TMT"].balance == Decimal("2025.00")

        # Отмена без указания кассы -> возвращает ровно 50 USD и 1025 TMT в те же кассы + товар на склад!
        SalesService.cancel_sale(session, sale.id, "Müşderi gaýtardy")
        assert regs["USD"].balance == Decimal("100.00")
        assert regs["TMT"].balance == Decimal("1000.00")
        assert session.get(Product, prod.id).stock_quantity == 10
        assert SalesService.get_store_debt_to_customer(session, sale) == Decimal("0.00")

        # 2. Simurg / продажа в долг (0 оплачено) -> при отмене касса НЕ трогается!
        sim_sale = SalesService.create_sale(
            session=session,
            items=[{"product_id": prod.id, "quantity": 1, "unit_price": Decimal("500.00"), "currency": "TMT"}],
            payments=[],
            currency="TMT",
            exchange_rate=Decimal("19.5000"),
            customer_name="Simurg Client",
            is_simurg=True,
        )
        SalesService.cancel_sale(session, sim_sale.id, "Simurg ýatyryldy")
        assert regs["TMT"].balance == Decimal("1000.00")
        assert session.get(Product, prod.id).stock_quantity == 10

        # 3. Недостаточно денег в кассе при отмене -> предупреждение ValueError!
        sale3 = SalesService.create_sale(
            session=session,
            items=[{"product_id": prod.id, "quantity": 1, "unit_price": Decimal("400.00"), "currency": "TMT"}],
            payments=[{"currency": "TMT", "amount": Decimal("400.00"), "exchange_rate": Decimal("19.5000")}],
            currency="TMT",
            exchange_rate=Decimal("19.5000"),
        )
        regs["TMT"].balance = Decimal("100.00")  # выручку забрали из кассы
        with pytest.raises(ValueError, match="ýeterlik pul ýok"):
            SalesService.cancel_sale(session, sale3.id, "Gaýtarma")

