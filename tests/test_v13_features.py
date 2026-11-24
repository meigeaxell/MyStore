import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.repositories.product_repository as prod_repo
import app.services.settings_service as settings_mod
from app.database.base import Base
from app.models.brand_glossary import BrandGlossary
from app.models.category import Category
from app.services.accessory_matcher import match_accessory_text
from app.services.settings_service import SettingsService


@pytest.fixture()
def v13_db(tmp_path, monkeypatch):
    db_file = tmp_path / "v13_test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(prod_repo, "SessionLocal", sf)
    monkeypatch.setattr(settings_mod, "SessionLocal", sf)

    with sf() as session, session.begin():
        c_case = Category(name="Çehol", code="CAT_001", is_active=True)
        c_glass = Category(name="Udarnyk", code="CAT_002", is_active=True)
        session.add_all([c_case, c_glass])
        session.flush()
        cats = {"case": c_case.id, "glass": c_glass.id}

    yield sf, cats
    engine.dispose()


def test_brand_glossary_sync_and_reference_ocr_funnel(v13_db):
    sf, cats = v13_db

    # Пользовательская схема: name = "14 Pro Max", category = Çehol/Udarnyk, brand = бренд аксессуара,
    # model = "iPhone", specification = Referens (уникальные слова/коды коробки)
    p_blueo = prod_repo.save_product(
        product_id=None,
        name="14 Pro Max",
        category_id=cats["glass"],
        brand="Blueo",
        model="iPhone",
        specification="DustFree, MrMonkey, 9D",
        stock_quantity=10,
    )
    p_hoco = prod_repo.save_product(
        product_id=None,
        name="14 Pro Max",
        category_id=cats["case"],
        brand="Hoco",
        model="iPhone",
        specification="X88, CrystalMag, SoftEdge",
        stock_quantity=8,
    )
    SettingsService.set_product_default_cost(p_hoco.id, Decimal("4.50"), "USD")

    with sf() as session:
        glossaries = session.scalars(select(BrandGlossary)).all()
        assert len(glossaries) == 2
        by_pid = {g.product_id: g for g in glossaries}
        assert by_pid[p_blueo.id].brand_key == "blueo"
        assert "DustFree" in by_pid[p_blueo.id].reference_text
        assert by_pid[p_hoco.id].brand_key == "hoco"

        # 1) Скан коробки БЕЗ логотипа Hoco, но с уникальным референсом "X88 CrystalMag" и "14 Pro Max"
        res_ref = match_accessory_text(session, "14 Pro Max X88 CrystalMag")
        assert res_ref["items"], "Expected match via unique reference word"
        assert res_ref["items"][0]["product_id"] == p_hoco.id
        assert res_ref["parsed"]["brand"].lower() == "hoco"

        # 2) Скан коробки с брендом Blueo + DustFree + 14 Pro Max -> мгновенно сужает на Blueo
        res_brand = match_accessory_text(session, "Blueo 14 Pro Max DustFree")
        assert res_brand["items"]
        assert res_brand["items"][0]["product_id"] == p_blueo.id

    # Проверяем, что list_products_inventory сразу отдаёт себестоимость и референс
    products, _cat_map = prod_repo.list_products_inventory(include_archived=False)
    hoco_row = next(p for p in products if p["id"] == p_hoco.id)
    assert hoco_row["cost_display"] == "4.50 USD"
    assert "X88" in hoco_row["reference"]

    brands, models = prod_repo.list_distinct_brands_and_models()
    assert "Blueo" in brands and "Hoco" in brands
    assert "iPhone" in models


def test_settings_stock_group_and_remember_fields(v13_db):
    assert SettingsService.get_stock_group_mode() == "name"
    SettingsService.set_stock_group_mode("brand")
    assert SettingsService.get_stock_group_mode() == "brand"
    SettingsService.set_stock_group_mode("none")
    assert SettingsService.get_stock_group_mode() == "none"

    fields = SettingsService.get_product_remember_fields()
    assert fields["brand"] is True
    assert fields["name"] is False
    SettingsService.set_product_remember_fields({"name": True, "brand": False})
    updated = SettingsService.get_product_remember_fields()
    assert updated["name"] is True
    assert updated["brand"] is False

    SettingsService.save_last_product_draft({"brand": "Remax", "model": "Xiaomi"})
    assert SettingsService.get_last_product_draft()["brand"] == "Remax"


def test_combo_popup_is_opaque():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QComboBox

    from app.ui.widgets import style_combo

    _app = QApplication.instance() or QApplication([])
    combo = style_combo(QComboBox())
    container = combo.view().window()
    assert not container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert container.autoFillBackground()
