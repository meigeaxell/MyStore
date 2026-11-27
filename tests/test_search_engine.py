"""Тесты единого движка поиска (FTS5 + синонимы + раскладка + digit-safe RapidFuzz + бенчмарк)."""
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.category import Category
from app.models.product import Product
from app.services import search_engine as se


@pytest.fixture
def search_db(tmp_path, monkeypatch):
    db_file = tmp_path / "search_test.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(se, "SessionLocal", sf)
    se.invalidate_synonym_cache()
    se._FTS_READY_ENGINES.clear()

    with sf() as session, session.begin():
        c_phone = Category(name="Telefon Täze", code="PHONE_NEW", is_active=True)
        c_acc = Category(name="Aksessuarlar", code="ACC", is_active=True)
        session.add_all([c_phone, c_acc])
        session.flush()

        products = [
            Product(category_id=c_acc.id, sku="PRD_1", name="Çehol Silicone Gara", brand="Apple", model="iPhone 16 Pro Max", stock_quantity=10, is_active=True),
            Product(category_id=c_acc.id, sku="PRD_2", name="Protective Glass 9D", brand="Apple", model="iPhone 16 Pro Max", stock_quantity=5, is_active=True),
            Product(category_id=c_phone.id, sku="PRD_3", name="Samsung Galaxy A55 128GB", brand="Samsung", model="A55", stock_quantity=3, is_active=True),
            Product(category_id=c_phone.id, sku="PRD_4", name="Samsung Galaxy A54 128GB", brand="Samsung", model="A54", stock_quantity=4, is_active=True),
            Product(category_id=c_acc.id, sku="PRD_5", name="Наушники AirPods Pro 2", brand="Apple", model="AirPods Pro 2", stock_quantity=0, is_active=True),
        ]
        session.add_all(products)
        session.flush()
        se.rebuild_fts_index(session)

    yield sf
    se._FTS_READY_ENGINES.clear()
    engine.dispose()


def test_synonyms_layout_and_turkmen_normalization(search_db):
    with search_db() as session:
        # 1. Сокращение + синоним (16pm udarnyk -> Protective Glass 9D iPhone 16 Pro Max)
        r1 = se.search_products(session, "16pm udarnyk")
        assert r1.hits and r1.hits[0].product.sku == "PRD_2"

        # 2. Кириллица / синоним цвета (чехол черный -> Çehol Silicone Gara)
        r2 = se.search_products(session, "чехол черный")
        assert r2.hits and r2.hits[0].product.sku == "PRD_1"

        # 3. Русская раскладка клавиатуры (ыфьыгтп ф55 -> samsung a55)
        r3 = se.search_products(session, "ыфьыгтп ф55")
        assert r3.hits and r3.hits[0].product.sku == "PRD_3"


def test_digit_safe_fuzzy_search(search_db):
    with search_db() as session:
        # Опечатка в бренде + точная цифра модели: samsng a55 -> строго A55, НЕ A54!
        res = se.search_products(session, "samsng a55", enable_fuzzy=True)
        skus = [h.product.sku for h in res.hits]
        assert "PRD_3" in skus
        assert "PRD_4" not in skus


def test_out_of_stock_count_reported(search_db):
    with search_db() as session:
        res = se.search_products(session, "nausnik airpods", in_stock_only=True)
        assert not res.hits
        assert res.out_of_stock_count == 1


def test_user_synonym_crud(search_db):
    row = se.upsert_synonym("k80", "redmi k80 pro")
    assert row.term == "k80"
    all_syns = se.list_synonyms()
    assert any(s.term == "k80" for s in all_syns)
    se.delete_synonym(row.id)
    assert all(s.term != "k80" for s in se.list_synonyms())


def test_fts5_speed_on_5000_products(tmp_path, monkeypatch):
    db_file = tmp_path / "bench_5000.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(se, "SessionLocal", sf)
    se.invalidate_synonym_cache()
    se._FTS_READY_ENGINES.clear()

    with sf() as session, session.begin():
        cat = Category(name="Aksessuarlar", code="ACC", is_active=True)
        session.add(cat)
        session.flush()
        bulk = [
            Product(
                category_id=cat.id,
                sku=f"SKU_{i:05d}",
                name=f"Çehol Model {i}",
                brand="BrandX" if i % 2 else "Samsung",
                model=f"M{i}",
                stock_quantity=5,
                is_active=True,
            )
            for i in range(5000)
        ]
        session.add_all(bulk)
        session.flush()
        se.rebuild_fts_index(session)

    with sf() as session:
        t0 = time.perf_counter()
        res = se.search_products(session, "samsung cehol m4998", limit=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert res.hits and res.hits[0].product.sku == "SKU_04998"
        assert elapsed_ms < 120.0, f"FTS5 query too slow: {elapsed_ms:.1f}ms"

    se._FTS_READY_ENGINES.clear()
    engine.dispose()
