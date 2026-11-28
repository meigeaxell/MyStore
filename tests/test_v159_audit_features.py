"""Тесты для отложенной прибыли Simurg, средневзвешенной себестоимости и разделения долгов."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.repositories import product_repository
from app.services import purchase_service, settings_service
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "v159_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(product_repository, "SessionLocal", session_factory)
    monkeypatch.setattr(purchase_service, "SessionLocal", session_factory)
    monkeypatch.setattr(settings_service, "SessionLocal", session_factory)

    return session_factory


def test_simurg_profit_deferred_until_payout(isolated_db):
    cat = product_repository.create_category("Telefon")
    prod = product_repository.save_product(
        product_id=None,
        name="Simurg Phone Test",
        category_id=cat.id,
        brand="Redmi",
    )
    purchase_service.create_purchase(
        items=[{
            "product_id": prod.id,
            "quantity": 1,
            "unit_cost": "100.00",
            "imeis": ["860000000000001"],
        }],
        currency="USD",
        exchange_rate="18.2000",
        supplier_name="",
    )

    sale_dt = datetime(2026, 11, 20, 12, 0, 0)
    payout_dt = datetime(2026, 11, 26, 15, 0, 0)

    with isolated_db() as session:
        sale = SalesService.create_sale(
            session=session,
            items=[{
                "product_id": prod.id,
                "quantity": 1,
                "unit_price": "2200.00",
                "imei": "860000000000001",
            }],
            currency="TMT",
            exchange_rate="18.2000",
            payments=[],
            allow_credit=True,
            is_simurg=True,
            customer_name="Simurg",
        )
        sale.sale_date = sale_dt
        session.commit()
        sale_id = sale.id

    # До выплаты Simurg прибыль = 0.00, долг Simurg = 2200.00, обычные долги клиентов = 0.00
    with isolated_db() as session:
        pr_before = ReportService.get_profit_report(
            session, sale_dt - timedelta(days=1), sale_dt + timedelta(days=1)
        )
        sr_before = ReportService.get_sales_report(
            session, sale_dt - timedelta(days=1), sale_dt + timedelta(days=1)
        )
        debts_before = FinanceService.get_all_outstanding_balances(session)

        assert pr_before["by_currency"]["TMT"]["gross_profit"] == Decimal("0.00")
        assert sr_before["by_currency"]["TMT"]["gross_profit"] == Decimal("0.00")
        assert sr_before["by_currency"]["TMT"]["revenue"] == Decimal("2200.00")
        assert debts_before["simurg_debts"]["TMT"] == Decimal("2200.00")
        assert debts_before["customer_debts"]["TMT"] == Decimal("0.00")

        # Получаем выплату от Simurg 26.11
        FinanceService.collect_simurg_payout(
            session=session,
            currency="TMT",
            amount="2200.00",
            ready_only=False,
            exchange_rate="18.2000",
            as_of=payout_dt,
        )
        from sqlalchemy import select

        from app.models.sale_payment import SalePayment

        for sp in session.scalars(select(SalePayment).where(SalePayment.sale_id == sale_id)).all():
            sp.payment_date = payout_dt
        session.commit()

    # После выплаты прибыль (2200 - 100*18.2 = 380.00 TMT) появляется именно в периоде выплаты (26.11)
    with isolated_db() as session:
        pr_sale_day = ReportService.get_profit_report(
            session, sale_dt - timedelta(hours=1), sale_dt + timedelta(hours=1)
        )
        pr_payout_day = ReportService.get_profit_report(
            session, payout_dt - timedelta(hours=1), payout_dt + timedelta(hours=1)
        )
        sr_all = ReportService.get_sales_report(session)
        debts_after = FinanceService.get_all_outstanding_balances(session)

        assert pr_sale_day["by_currency"]["TMT"]["gross_profit"] == Decimal("0.00")
        assert pr_payout_day["by_currency"]["TMT"]["gross_profit"] == Decimal("380.00")
        assert sr_all["by_currency"]["TMT"]["gross_profit"] == Decimal("380.00")
        assert debts_after["simurg_debts"]["TMT"] == Decimal("0.00")


def test_weighted_average_cost_and_manual_override(isolated_db):
    cat = product_repository.create_category("Aksessuar")
    prod = product_repository.save_product(
        product_id=None,
        name="AirPods Weighted",
        category_id=cat.id,
        brand="Apple",
    )

    # Партия 1: 10 шт по $6.00 -> средняя $6.00
    purchase_service.create_purchase(
        items=[{"product_id": prod.id, "quantity": 10, "unit_cost": "6.00"}],
        currency="USD",
        exchange_rate="18.2000",
        supplier_name="",
    )
    assert SettingsService.get_product_default_cost(prod.id) == (Decimal("6.00"), "USD")

    # Партия 2: 10 шт по $4.00 -> средневзвешенная (10*6 + 10*4)/20 = $5.00
    purchase_service.create_purchase(
        items=[{"product_id": prod.id, "quantity": 10, "unit_cost": "4.00"}],
        currency="USD",
        exchange_rate="18.2000",
        supplier_name="",
    )
    assert SettingsService.get_product_default_cost(prod.id) == (Decimal("5.00"), "USD")

    # Ручная правка себестоимости на складе ($5.50) должна иметь приоритет в _resolve_item_cost_basis
    SettingsService.set_product_default_cost(prod.id, Decimal("5.50"), "USD")
    with isolated_db() as session:
        cost, curr, _rate = SalesService._resolve_item_cost_basis(
            session=session,
            product_id=prod.id,
            stock_item=None,
            fallback_currency="USD",
            fallback_rate=Decimal("18.2000"),
        )
        assert cost == Decimal("5.50")
        assert curr == "USD"
