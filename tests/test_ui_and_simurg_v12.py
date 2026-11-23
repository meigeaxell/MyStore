import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.services.purchase_service as purchase_mod
import app.services.settings_service as settings_mod
from app.database.base import Base
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.services.finance_service import FinanceService
from app.services.purchase_service import create_purchase
from app.services.report_service import ReportService
from app.services.sales_service import SalesService


@pytest.fixture()
def v12_db(tmp_path, monkeypatch):
    db_file = tmp_path / "v12_test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(purchase_mod, "SessionLocal", sf)
    monkeypatch.setattr(settings_mod, "SessionLocal", sf)
    yield sf
    engine.dispose()


def _seed_stock(sf):
    with sf() as session, session.begin():
        cat = Category(name="Smartfonlar", code="PHONE", is_active=True)
        acc_cat = Category(name="Aksessuarlar", code="ACC", is_active=True)
        session.add_all([cat, acc_cat])
        session.flush()

        phone = Product(
            name="iPhone 15 Pro",
            sku="IP15P",
            category_id=cat.id,
            stock_quantity=2,
            is_active=True,
        )
        case = Product(
            name="MagSafe Case",
            sku="CASE-01",
            barcode="4820001112223",
            category_id=acc_cat.id,
            stock_quantity=0,
            is_active=True,
        )
        session.add_all([phone, case])
        session.flush()

        st1 = StockItem(
            product_id=phone.id,
            imei1="111111111111111",
            condition="new",
            status="in_stock",
            unit_cost=Decimal("900.00"),
            cost_currency="USD",
            cost_exchange_rate=Decimal("20.0000"),
        )
        st2 = StockItem(
            product_id=phone.id,
            imei1="222222222222222",
            condition="new",
            status="in_stock",
            unit_cost=Decimal("950.00"),
            cost_currency="USD",
            cost_exchange_rate=Decimal("20.0000"),
        )
        session.add_all([st1, st2])
        phone_id, case_id = phone.id, case.id

    # Закупаем 5 чехлов по 100 TMT (итого 500 TMT)
    create_purchase(
        items=[{"product_id": case_id, "quantity": 5, "unit_cost": Decimal("100.00")}],
        currency="TMT",
        exchange_rate=Decimal("20.0000"),
        payments=[],
        supplier_name="Test Supplier",
    )
    return phone_id, case_id


def test_stock_valuation_both_currencies(v12_db):
    _seed_stock(v12_db)
    with v12_db() as session:
        val = ReportService.get_stock_valuation(session, exchange_rate=Decimal("20.0000"))
    # 2 телефона: 900 + 950 = 1850 USD; 5 чехлов: 5 * 100 = 500 TMT (= 25 USD)
    assert val["usd_native"] == Decimal("1850.00")
    assert val["tmt_native"] == Decimal("500.00")
    assert val["total_in_usd"] == Decimal("1875.00")
    assert val["total_in_tmt"] == Decimal("37500.00")
    assert val["devices_count"] == 2
    assert val["accessories_count"] == 5
    assert val["total_units"] == 7


def test_simurg_sale_5_day_maturity_and_fifo_collection(v12_db):
    phone_id, _case_id = _seed_stock(v12_db)
    now = datetime(2026, 11, 20, 12, 0, 0)

    with v12_db() as session:
        # Продажа #1 через Simurg (уже прошло 6 дней -> готова к получению!)
        sale1 = SalesService.create_sale(
            session=session,
            items=[{"product_id": phone_id, "quantity": 1, "unit_price": Decimal("22000.00"), "imei": "111111111111111"}],
            payments=[],
            currency="TMT",
            exchange_rate=Decimal("20.0000"),
            customer_name="Simurg — Aman",
            is_simurg=True,
            simurg_payout_date=now - timedelta(days=1),
        )
        # Продажа #2 через Simurg (ещё не созрела — через 3 дня)
        sale2 = SalesService.create_sale(
            session=session,
            items=[{"product_id": phone_id, "quantity": 1, "unit_price": Decimal("24000.00"), "imei": "222222222222222"}],
            payments=[],
            currency="TMT",
            exchange_rate=Decimal("20.0000"),
            customer_name="Simurg — Myrat",
            is_simurg=True,
            simurg_payout_date=now + timedelta(days=3),
        )
        session.flush()

        assert sale1.is_simurg is True
        assert sale2.is_simurg is True

        # В кассе TMT должно быть 0, вся сумма в Simurg (прибыль уже внутри суммы продажи!)
        bal_before = FinanceService.get_register_balances(session)
        assert bal_before["tmt_balance"] == Decimal("0.00")

        summary = FinanceService.get_simurg_summary(session, as_of=now)
        assert summary["total_debt"]["TMT"] == Decimal("46000.00")
        assert summary["ready_amount"]["TMT"] == Decimal("22000.00")
        assert summary["pending_amount"]["TMT"] == Decimal("24000.00")
        assert summary["total_items_count"] == 2
        assert summary["ready_items_count"] == 1
        assert summary["pending_items_count"] == 1

        # Забираем готовые деньги (1 клик)
        res1 = FinanceService.collect_simurg_payout(
            session=session,
            currency="TMT",
            amount=None,
            ready_only=True,
            exchange_rate=Decimal("20.0000"),
            as_of=now,
        )
        assert res1["collected_amount"] == Decimal("22000.00")
        assert res1["sales_count"] == 1

        bal_mid = FinanceService.get_register_balances(session)
        assert bal_mid["tmt_balance"] == Decimal("22000.00")

        # Частичный приём по оставшейся заявке (FIFO, ready_only=False)
        res2 = FinanceService.collect_simurg_payout(
            session=session,
            currency="TMT",
            amount=Decimal("10000.00"),
            ready_only=False,
            exchange_rate=Decimal("20.0000"),
            as_of=now,
        )
        assert res2["collected_amount"] == Decimal("10000.00")

        summary_after = FinanceService.get_simurg_summary(session, as_of=now)
        assert summary_after["total_debt"]["TMT"] == Decimal("14000.00")
        assert summary_after["total_items_count"] == 1
        assert FinanceService.get_register_balances(session)["tmt_balance"] == Decimal("32000.00")


def test_monthly_expenses_summary(v12_db):
    with v12_db() as session:
        regs = SalesService.ensure_default_registers(session)
        regs["TMT"].balance = Decimal("10000.00")
        regs["USD"].balance = Decimal("500.00")
        session.flush()

        FinanceService.record_expense(
            session=session,
            category="Kärende",
            amount=Decimal("1500.00"),
            currency="TMT",
            exchange_rate=Decimal("20.0000"),
        )
        FinanceService.record_expense(
            session=session,
            category="Logistika",
            amount=Decimal("50.00"),
            currency="USD",
            exchange_rate=Decimal("20.0000"),
        )
        res = FinanceService.get_monthly_expenses_summary(session)
    assert res["TMT"] == Decimal("1500.00")
    assert res["USD"] == Decimal("50.00")
    assert res["count"] == 2


def test_ui_dialogs_default_buttons_and_decimal_dot(v12_db, monkeypatch):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QPushButton

    import app.ui.finance_page as finance_ui_mod

    monkeypatch.setattr(finance_ui_mod, "SessionLocal", v12_db)
    QLocale.setDefault(QLocale.c())
    app = QApplication.instance() or QApplication([])

    # Проверяем, что QDoubleSpinBox форматирует дробь через точку '.'
    sp = QDoubleSpinBox()
    sp.setDecimals(2)
    sp.setValue(19.5)
    assert "." in sp.text()
    assert "," not in sp.text()

    from app.ui.category_dialog import CategoryDialog
    from app.ui.finance_page import ExpenseDialog, ShiftAndCashDialog
    from app.ui.product_dialog import ProductDialog
    from app.ui.purchase_page import RefundDialog
    from app.ui.sales_page import HeldCartsDialog

    def _assert_single_primary_default(dlg, expected_text_part: str):
        defaults = [b for b in dlg.findChildren(QPushButton) if b.isDefault()]
        assert len(defaults) == 1, f"{type(dlg).__name__}: expected 1 default button, got {[b.text() for b in defaults]}"
        assert expected_text_part in defaults[0].text(), (
            f"{type(dlg).__name__}: default button '{defaults[0].text()}' does not match '{expected_text_part}'"
        )
        # Проверяем, что кнопки отмены/удаления НЕ имеют autoDefault
        for b in dlg.findChildren(QPushButton):
            if b is not defaults[0]:
                assert not b.autoDefault(), f"{type(dlg).__name__}: '{b.text()}' must not be autoDefault"
        dlg.close()

    _assert_single_primary_default(ProductDialog(), "ýatda sakla")
    _assert_single_primary_default(CategoryDialog(), "Kategoriýa döret")
    _assert_single_primary_default(ExpenseDialog(), "Çykdajyny ýatda sakla")
    _assert_single_primary_default(HeldCartsDialog(), "Çeki kassa gaýtar")
    _assert_single_primary_default(RefundDialog("TMT"), "Gaýtarmany hasaba al")
    _assert_single_primary_default(ShiftAndCashDialog(), "Z-hasabaty PDF")
    assert app is not None
