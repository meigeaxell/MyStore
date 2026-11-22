"""Тесты OCR-распознавания аксессуаров по коробке и самообучаемых алиасов."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.repositories.product_repository as product_repo
import app.services.mobile_protocol as mp
import app.services.settings_service as settings_mod
from app.database.base import Base
from app.models.cash_register import CashRegister
from app.models.category import Category
from app.models.product import Product
from app.models.product_ocr_alias import ProductOcrAlias
from app.services import purchase_service
from app.services.accessory_matcher import (
    match_accessory_text,
    normalize_ocr_text,
    parse_box_ocr,
    record_ocr_alias,
)
from app.services.sales_service import SalesService


@pytest.fixture()
def ocr_db(tmp_path, monkeypatch):
    db_file = tmp_path / "ocr_test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(mp, "SessionLocal", session_factory)
    monkeypatch.setattr(product_repo, "SessionLocal", session_factory)
    monkeypatch.setattr(purchase_service, "SessionLocal", session_factory)
    monkeypatch.setattr(settings_mod, "SessionLocal", session_factory)

    with session_factory() as session, session.begin():
        cat_glass = Category(name="Udarnyk / Aýna", code="GLASS", is_active=True)
        cat_case = Category(name="Çehollar", code="CASE", is_active=True)
        cat_charge = Category(name="Adapter we kabel", code="CHG", is_active=True)
        session.add_all([cat_glass, cat_case, cat_charge])
        session.flush()

        p_blueo_16pm = Product(
            category_id=cat_glass.id,
            sku="GL-BLUEO-16PM",
            name="Blueo Anti-Static 9D iPhone 16 Pro Max",
            brand="Blueo",
            model="iPhone 16 Pro Max",
            specification="9D, Anti-Static, Full Glue",
            stock_quantity=8,
        )
        p_remax_16pm = Product(
            category_id=cat_glass.id,
            sku="GL-REMAX-16PM",
            name="Remax 9D iPhone 16 Pro Max",
            brand="Remax",
            model="iPhone 16 Pro Max",
            specification="9D, HD",
            stock_quantity=15,
        )
        p_blueo_16pro = Product(
            category_id=cat_glass.id,
            sku="GL-BLUEO-16P",
            name="Blueo Anti-Static 9D iPhone 16 Pro",
            brand="Blueo",
            model="iPhone 16 Pro",
            specification="9D, Anti-Static",
            stock_quantity=6,
        )
        p_case_16pm = Product(
            category_id=cat_case.id,
            sku="CS-MS-16PM",
            name="MagSafe Silicone Case iPhone 16 Pro Max",
            brand="Baseus",
            model="iPhone 16 Pro Max",
            specification="MagSafe, Silicone",
            stock_quantity=10,
        )
        p_case_s22 = Product(
            category_id=cat_case.id,
            sku="CS-SAM-S22",
            name="Silicone Cover Samsung S22",
            brand="Nillkin",
            model="Samsung S22",
            specification="Silicone, Matte",
            stock_quantity=5,
        )
        p_glass_rn13 = Product(
            category_id=cat_glass.id,
            sku="GL-RN13",
            name="Tempered Glass 9D Redmi Note 13",
            brand="Remax",
            model="Redmi Note 13",
            specification="9D, Full Glue",
            stock_quantity=12,
        )
        p_adapter_20w = Product(
            category_id=cat_charge.id,
            sku="AD-HOCO-20W",
            name="Hoco PD 20W Type-C Adapter",
            brand="Hoco",
            model="",
            specification="20W, PD, Type-C",
            stock_quantity=7,
        )
        session.add_all([
            p_blueo_16pm,
            p_remax_16pm,
            p_blueo_16pro,
            p_case_16pm,
            p_case_s22,
            p_glass_rn13,
            p_adapter_20w,
        ])
        session.flush()

        # Запишем прошлые продажи, чтобы проверить подсказку последней цены продажи
        reg = CashRegister(name="Kassa TMT", currency="TMT", balance=Decimal("1000.00"))
        session.add(reg)
        session.flush()

        SalesService.create_sale(
            session=session,
            items=[
                {"product_id": p_blueo_16pm.id, "quantity": 1, "unit_price": Decimal("120.00"), "currency": "TMT"},
                {"product_id": p_remax_16pm.id, "quantity": 1, "unit_price": Decimal("40.00"), "currency": "TMT"},
            ],
            payments=[{"cash_register_id": reg.id, "amount": Decimal("160.00"), "currency": "TMT"}],
            currency="TMT",
            exchange_rate=Decimal("19.5000"),
        )

        ids = {
            "cat_glass": cat_glass.id,
            "cat_case": cat_case.id,
            "cat_charge": cat_charge.id,
            "blueo_16pm": p_blueo_16pm.id,
            "remax_16pm": p_remax_16pm.id,
            "blueo_16pro": p_blueo_16pro.id,
            "case_16pm": p_case_16pm.id,
            "case_s22": p_case_s22.id,
            "glass_rn13": p_glass_rn13.id,
            "adapter_20w": p_adapter_20w.id,
        }

    yield session_factory, ids
    engine.dispose()


def test_parse_dirty_box_abbreviations_and_noise():
    p1 = parse_box_ocr("MADE IN CHINA  CE RoHS\nBLUEO 9D ESD\nFor IP 16 MAX Full Glue")
    assert p1.brand == "Blueo"
    assert p1.device_model == "iPhone 16 Pro Max"
    assert p1.accessory_type == "glass"
    assert "9D" in p1.features
    assert "Anti-Static" in p1.features
    assert "made" not in p1.normalized_text

    p2 = parse_box_ocr("SAM S22 MAGSAFE SILICONE")
    assert p2.device_model == "Samsung S22"
    assert p2.accessory_type == "case"

    p3 = parse_box_ocr("RN13 9D TEMPERED")
    assert p3.device_model == "Redmi Note 13"
    assert p3.accessory_type == "glass"

    p4 = parse_box_ocr("lPhone 16PM Blveo 21D")
    assert p4.device_model == "iPhone 16 Pro Max"
    assert p4.brand == "Blueo"
    assert p4.accessory_type == "glass"


def test_distinguishes_brand_price_type_and_model_variant(ocr_db):
    session_factory, ids = ocr_db
    with session_factory() as session:
        # 1. Blueo 16 Pro Max glass -> Blueo (120 TMT) must beat Remax (40 TMT), 16 Pro, and MagSafe Case
        res = match_accessory_text(session, "BLUEO ESD 9D IP 16 MAX FULL GLUE")
        assert res["items"], "Expected matching items"
        top = res["items"][0]
        assert top["product_id"] == ids["blueo_16pm"]
        assert top["last_sale_price"] == "120.00"
        assert top["last_sale_currency"] == "TMT"

        # Remax glass is same type/model, should rank above wrong model or wrong type (case)
        ranked_ids = [it["product_id"] for it in res["items"]]
        assert ids["remax_16pm"] in ranked_ids
        assert ranked_ids.index(ids["blueo_16pm"]) < ranked_ids.index(ids["remax_16pm"])
        if ids["case_16pm"] in ranked_ids:
            assert ranked_ids.index(ids["remax_16pm"]) < ranked_ids.index(ids["case_16pm"])

        # 2. Without brand (logo unreadable): both Blueo (120 TMT) & Remax (40 TMT) glasses appear at top
        res_no_brand = match_accessory_text(session, "9D GLASS 16PM")
        top2_ids = {it["product_id"] for it in res_no_brand["items"][:2]}
        assert top2_ids == {ids["blueo_16pm"], ids["remax_16pm"]}

        # 3. MagSafe Silicone 16PM -> Case beats glasses
        res_case = match_accessory_text(session, "BASEUS MAGSAFE SILICONE 16PM")
        assert res_case["items"][0]["product_id"] == ids["case_16pm"]

        # 4. Samsung S22 & Redmi Note 13 & Hoco 20W
        res_s22 = match_accessory_text(session, "NILLKIN MATTE SILICONE SAM S22")
        assert res_s22["items"][0]["product_id"] == ids["case_s22"]

        res_rn13 = match_accessory_text(session, "RN13 FULL GLUE 9D")
        assert res_rn13["items"][0]["product_id"] == ids["glass_rn13"]

        res_hoco = match_accessory_text(session, "HOCO PD 20W TYPE-C WALL CHARGER")
        assert res_hoco["items"][0]["product_id"] == ids["adapter_20w"]


def test_draft_suggestion_and_alias_learning(ocr_db):
    session_factory, ids = ocr_db
    with session_factory() as session, session.begin():
        # Шум не сохраняется как алиас
        assert record_ocr_alias(session, ids["blueo_16pm"], "CE RoHS Made in China") is None
        assert normalize_ocr_text("CE RoHS Made in China") == ""

        # Уникальная надпись коробки (без слова glass/16pm!) запоминается и потом находит товар №1
        al1 = record_ocr_alias(session, ids["blueo_16pm"], "ULTRA DIAMOND ARMOR X9900")
        assert al1 is not None
        assert al1.hits == 1
        al2 = record_ocr_alias(session, ids["blueo_16pm"], "ULTRA DIAMOND ARMOR X9900")
        assert al2.hits == 2

    with session_factory() as session:
        res = match_accessory_text(session, "ULTRA DIAMOND ARMOR X9900")
        assert res["items"][0]["product_id"] == ids["blueo_16pm"]
        assert "Ýatda saklanan guty" in res["items"][0]["match_detail"]

        # Автозаполнение черновика нового товара при приёмке
        res_new = match_accessory_text(session, "ANKER 65W GAN TYPE-C CHARGER")
        draft = res_new["draft_suggestion"]
        assert draft["brand"] == "Anker"
        assert draft["category_id"] == ids["cat_charge"]
        assert "Anker" in draft["name"]
        assert "65W" in draft["specification"]


def test_protocol_ocr_match_and_auto_alias_on_product_create_and_sale(ocr_db):
    session_factory, ids = ocr_db
    added_to_cart: list[dict] = []

    def fake_add(data: dict):
        added_to_cart.append(data)
        return True, "Goşuldy", {"cart_count": len(added_to_cart)}

    proc = mp.MobileProtocolProcessor(add_to_sale_callback=fake_add)

    # 1. match_accessory_ocr через WebSocket-протокол
    resp, _ = proc.handle_message(
        {
            "protocol_version": 1,
            "type": "match_accessory_ocr",
            "request_id": "ocr-1",
            "device_id": "dev-1",
            "payload": {"raw_text": "BLUEO 9D IP 16 MAX"},
        },
        is_authenticated=True,
    )
    assert resp["ok"] is True
    assert resp["type"] == "accessory_ocr_matches"
    assert resp["data"]["items"][0]["product_id"] == ids["blueo_16pm"]
    assert resp["data"]["items"][0]["last_sale_price"] == "120.00"

    # 2. product_create с ocr_raw_text сразу сохраняет алиас
    resp_create, _ = proc.handle_message(
        {
            "protocol_version": 1,
            "type": "product_create",
            "request_id": "ocr-2",
            "device_id": "dev-1",
            "payload": {
                "name": "Green Lion Privacy 16 Pro Max",
                "category_id": ids["cat_glass"],
                "brand": "Green Lion",
                "model": "iPhone 16 Pro Max",
                "specification": "Privacy, 9D",
                "ocr_raw_text": "GREEN LION ANTI-PEEP BOX Z77",
            },
        },
        is_authenticated=True,
    )
    assert resp_create["ok"] is True
    created_id = resp_create["data"]["product"]["id"]

    with session_factory() as session:
        alias = session.scalar(
            select(ProductOcrAlias).where(ProductOcrAlias.product_id == created_id)
        )
        assert alias is not None
        assert "z77" in alias.normalized_text

    # 3. add_to_sale с ocr_raw_text тоже автоматически обучает алиас
    resp_sale, _ = proc.handle_message(
        {
            "protocol_version": 1,
            "type": "add_to_sale",
            "request_id": "ocr-3",
            "device_id": "dev-1",
            "payload": {
                "product_id": ids["remax_16pm"],
                "unit_price": "45.00",
                "currency": "TMT",
                "quantity": 1,
                "ocr_raw_text": "REMAX CRYSTAL BOX R88",
            },
        },
        is_authenticated=True,
    )
    assert resp_sale["ok"] is True
    with session_factory() as session:
        alias_sale = session.scalar(
            select(ProductOcrAlias).where(ProductOcrAlias.product_id == ids["remax_16pm"])
        )
        assert alias_sale is not None
        assert "r88" in alias_sale.normalized_text
