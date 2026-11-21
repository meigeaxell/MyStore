"""Тесты WebSocket-протокола и локального сервера MobileStore (Этап 7)."""
import json

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database.base import Base
from app.models.product import Product
from app.models.stock_item import StockItem
from app.repositories import product_repository
from app.services import mobile_protocol, purchase_service, settings_service
from app.services.mobile_protocol import MobileProtocolProcessor, validate_imei_luhn
from app.services.mobile_ws_server import MobileWebSocketServer
from app.services.settings_service import SettingsService


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Изолированная временная БД SQLite для всех сервисов мобильного протокола."""
    db_file = tmp_path / "test_mobile_protocol.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(mobile_protocol, "SessionLocal", TestingSession)
    monkeypatch.setattr(purchase_service, "SessionLocal", TestingSession)
    monkeypatch.setattr(product_repository, "SessionLocal", TestingSession)
    monkeypatch.setattr(settings_service, "SessionLocal", TestingSession)

    yield TestingSession
    test_engine.dispose()


def _req(msg_type: str, request_id: str, payload: dict, device_id: str = "phone-1") -> dict:
    return {
        "protocol_version": 1,
        "type": msg_type,
        "request_id": request_id,
        "device_id": device_id,
        "payload": payload,
    }


def test_validate_imei_luhn():
    assert validate_imei_luhn("356938035643809") is True
    assert validate_imei_luhn("490154203237518") is True
    assert validate_imei_luhn("356938035643800") is False  # неверная контрольная цифра
    assert validate_imei_luhn("12345") is False
    assert validate_imei_luhn("35693803564380a") is False


def test_auth_version_and_unauthorized_guard(isolated_db):
    proc = MobileProtocolProcessor()
    pin = SettingsService.get_or_create_mobile_token()

    # Неверная версия протокола
    resp, _ = proc.handle_message(
        {"protocol_version": 99, "type": "ping", "request_id": "v1", "device_id": "d1", "payload": {}},
        is_authenticated=False,
    )
    assert not resp["ok"] and resp["error"]["code"] == "UNSUPPORTED_VERSION"

    # Неавторизованный запрос отклонён
    resp, _ = proc.handle_message(_req("catalog_list", "c1", {}), is_authenticated=False)
    assert not resp["ok"] and resp["error"]["code"] == "UNAUTHORIZED"

    # Неверный PIN
    resp, _ = proc.handle_message(
        _req("auth", "a1", {"token": "wrong", "device_id": "phone-1", "device_name": "Test Phone"}),
        is_authenticated=False,
    )
    assert not resp["ok"] and resp["error"]["code"] == "UNAUTHORIZED"

    # Успешная авторизация
    resp, _ = proc.handle_message(
        _req("auth", "a2", {"token": pin, "device_id": "phone-1", "device_name": "Test Phone"}),
        is_authenticated=False,
        connected_count=2,
    )
    assert resp["ok"] and resp["type"] == "auth_ok"
    assert resp["data"]["connected_devices_count"] == 2


def test_receiving_duplicate_imei_and_idempotency(isolated_db):
    proc = MobileProtocolProcessor()

    # Создаём категорию и товар
    cat_resp, _ = proc.handle_message(_req("category_create", "cat-1", {"name": "Смартфоны"}), True)
    assert cat_resp["ok"]
    cat_id = cat_resp["data"]["category"]["id"]

    prod_resp, _ = proc.handle_message(
        _req(
            "product_create",
            "prod-1",
            {
                "name": "iPhone 15 Pro",
                "category_id": cat_id,
                "brand": "Apple",
                "model": "15 Pro",
                "specification": "256GB / Black",
            },
        ),
        True,
    )
    assert prod_resp["ok"]
    prod_id = prod_resp["data"]["product"]["id"]

    # Попытка создать дубликат товара без allow_duplicate отклоняется
    dup_prod, _ = proc.handle_message(
        _req(
            "product_create",
            "prod-2",
            {
                "name": "iPhone 15 Pro",
                "category_id": cat_id,
                "brand": "Apple",
                "model": "15 Pro",
                "specification": "256GB / Black",
            },
        ),
        True,
    )
    assert not dup_prod["ok"] and dup_prod["error"]["code"] == "DUPLICATE_PRODUCT"

    imei1 = "356938035643809"
    imei2 = "490154203237518"

    # Проверка свободного IMEI
    chk1, _ = proc.handle_message(_req("check_imei", "chk-1", {"imei1": imei1}), True)
    assert chk1["ok"] and chk1["data"]["luhn_valid"] is True and chk1["data"]["can_receive"] is True

    # Приёмка 2 устройств
    rec_payload = {
        "supplier_name": "Official Dist",
        "currency": "USD",
        "exchange_rate": "19.5000",
        "items": [
            {
                "product_id": prod_id,
                "quantity": 2,
                "unit_cost": "900.00",
                "imeis": [
                    {"imei1": imei1, "condition": "new"},
                    {"imei1": imei2, "condition": "new"},
                ],
            }
        ],
    }
    rec1, _ = proc.handle_message(_req("receive_purchase", "rec-uuid-1", rec_payload, "phone-1"), True)
    assert rec1["ok"] and rec1["data"]["purchase_id"] > 0

    # Идемпотентный повтор при обрыве связи (тот же device_id + request_id) НЕ создаёт дубль закупки!
    rec_replay, _ = proc.handle_message(_req("receive_purchase", "rec-uuid-1", rec_payload, "phone-1"), True)
    assert rec_replay["ok"] and rec_replay["data"]["purchase_id"] == rec1["data"]["purchase_id"]

    with isolated_db() as session:
        prod = session.get(Product, prod_id)
        assert prod.stock_quantity == 2
        stock_items = session.scalars(select(StockItem).where(StockItem.product_id == prod_id)).all()
        assert len(stock_items) == 2

    # Повторная приёмка того же IMEI с новым request_id отклоняется!
    chk_dup, _ = proc.handle_message(_req("check_imei", "chk-2", {"imei1": imei1}), True)
    assert chk_dup["ok"] and chk_dup["data"]["exists_in_db"] is True and chk_dup["data"]["can_receive"] is False

    rec_dup_imei, _ = proc.handle_message(
        _req("receive_purchase", "rec-uuid-2", rec_payload, "phone-2"),
        True,
    )
    assert not rec_dup_imei["ok"] and rec_dup_imei["error"]["code"] == "VALIDATION_ERROR"


def test_concurrent_devices_sale_cart_and_sold_protection(isolated_db):
    cart: list[dict] = []

    def is_in_cart(imei: str) -> bool:
        return any(it.get("imei") == imei for it in cart)

    def add_to_sale(item: dict):
        if item.get("imei") and is_in_cart(item["imei"]):
            return False, f"Устройство с IMEI {item['imei']} уже добавлено в текущую продажу.", None
        cart.append(item)
        return True, f"Товар добавлен ({item['unit_price']} {item['currency']})", {"cart_items_count": len(cart)}

    proc = MobileProtocolProcessor(
        add_to_sale_callback=add_to_sale,
        is_imei_in_cart_callback=is_in_cart,
    )

    cat_resp, _ = proc.handle_message(_req("category_create", "c1", {"name": "Телефоны"}), True)
    cat_id = cat_resp["data"]["category"]["id"]
    prod_resp, _ = proc.handle_message(
        _req("product_create", "p1", {"name": "Galaxy S24", "category_id": cat_id, "brand": "Samsung"}),
        True,
    )
    prod_id = prod_resp["data"]["product"]["id"]

    imei = "356938035643809"
    proc.handle_message(
        _req(
            "receive_purchase",
            "r1",
            {
                "currency": "USD",
                "exchange_rate": "19.5",
                "items": [{"product_id": prod_id, "quantity": 1, "unit_cost": "700", "imeis": [{"imei1": imei}]}],
            },
        ),
        True,
    )

    # Телефон 1 сканирует IMEI -> available
    scan1, _ = proc.handle_message(_req("scan_code", "s1", {"code": imei, "source": "barcode"}, "phone-1"), True)
    assert scan1["ok"] and scan1["data"]["availability_status"] == "available"

    # Телефон 1 добавляет товар в продажу
    add1, _ = proc.handle_message(
        _req(
            "add_to_sale",
            "sale-req-1",
            {"product_id": prod_id, "imei": imei, "quantity": 1, "unit_price": "820.00", "currency": "USD"},
            "phone-1",
        ),
        True,
    )
    assert add1["ok"] and len(cart) == 1

    # Идемпотентный повтор sale-req-1 с Телефона 1 не дублирует корзину
    add1_replay, _ = proc.handle_message(
        _req(
            "add_to_sale",
            "sale-req-1",
            {"product_id": prod_id, "imei": imei, "quantity": 1, "unit_price": "820.00", "currency": "USD"},
            "phone-1",
        ),
        True,
    )
    assert add1_replay["ok"] and len(cart) == 1

    # Телефон 2 сканирует тот же IMEI -> видит статус in_cart!
    scan2, _ = proc.handle_message(_req("scan_code", "s2", {"code": imei, "source": "ocr"}, "phone-2"), True)
    assert scan2["ok"] and scan2["data"]["availability_status"] == "in_cart"

    # Телефон 2 пытается добавить тот же IMEI -> отказ ALREADY_IN_CART
    add2, _ = proc.handle_message(
        _req(
            "add_to_sale",
            "sale-req-2",
            {"product_id": prod_id, "imei": imei, "quantity": 1, "unit_price": "810.00", "currency": "USD"},
            "phone-2",
        ),
        True,
    )
    assert not add2["ok"] and add2["error"]["code"] == "ALREADY_IN_CART"

    # Если устройство уже продано в БД -> scan_code возвращает status=sold, add_to_sale возвращает ALREADY_SOLD
    cart.clear()
    with isolated_db() as session:
        st = session.scalar(select(StockItem).where(StockItem.imei1 == imei))
        st.status = "sold"
        session.commit()

    scan_sold, _ = proc.handle_message(_req("scan_code", "s3", {"code": imei}, "phone-2"), True)
    assert scan_sold["ok"] and scan_sold["data"]["availability_status"] == "sold"

    add_sold, _ = proc.handle_message(
        _req(
            "add_to_sale",
            "sale-req-3",
            {"product_id": prod_id, "imei": imei, "quantity": 1, "unit_price": "810.00", "currency": "USD"},
            "phone-2",
        ),
        True,
    )
    assert not add_sold["ok"] and add_sold["error"]["code"] == "ALREADY_SOLD"


def test_category_deactivate_guard_and_catalog_search(isolated_db):
    proc = MobileProtocolProcessor()
    cat_resp, _ = proc.handle_message(_req("category_create", "c1", {"name": "Аксессуары"}), True)
    cat_id = cat_resp["data"]["category"]["id"]

    proc.handle_message(
        _req("product_create", "p1", {"name": "Чехол MagSafe", "category_id": cat_id, "unit_cost": "10.00"}),
        True,
    )

    # Без force деактивация категории с товарами предупреждает
    d1, _ = proc.handle_message(_req("category_deactivate", "d1", {"category_id": cat_id}), True)
    assert not d1["ok"] and d1["error"]["code"] == "VALIDATION_ERROR"

    # С force=True категория мягко деактивируется
    d2, _ = proc.handle_message(_req("category_deactivate", "d2", {"category_id": cat_id, "force": True}), True)
    assert d2["ok"] and d2["data"]["active_products_count"] == 1

    # Поиск в каталоге находит созданный товар
    cat_list, _ = proc.handle_message(_req("catalog_list", "cl1", {"query": "MagSafe"}), True)
    assert cat_list["ok"] and cat_list["data"]["total"] == 1
    assert cat_list["data"]["products"][0]["stock_quantity"] == 0


def test_websocket_server_multi_device_and_reconnect(isolated_db, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app_inst = QApplication.instance() or QApplication([])
    assert app_inst is not None

    server = MobileWebSocketServer()
    ok, _msg = server.start(port=0)  # свободный эфемерный порт
    assert ok and server.is_running()
    port = server.port
    token = SettingsService.get_or_create_mobile_token()

    def _wait(pred, timeout_ms: int = 3000) -> None:
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(15)
        elapsed = [0]

        def tick():
            elapsed[0] += 15
            if pred() or elapsed[0] >= timeout_ms:
                timer.stop()
                loop.quit()

        timer.timeout.connect(tick)
        timer.start()
        loop.exec()
        assert pred(), "WebSocket timeout"

    def _connect_and_auth(dev_id: str, dev_name: str):
        sock = QWebSocket()
        connected = [False]
        msgs: list[dict] = []
        sock.connected.connect(lambda: connected.__setitem__(0, True))
        sock.textMessageReceived.connect(lambda t: msgs.append(json.loads(t)))
        sock.open(QUrl(f"ws://127.0.0.1:{port}"))
        _wait(lambda: connected[0])
        sock.sendTextMessage(
            json.dumps(
                _req(
                    "auth",
                    f"auth-{dev_id}",
                    {"token": token, "device_id": dev_id, "device_name": dev_name, "app_version": "1.0.0"},
                    dev_id,
                )
            )
        )
        _wait(lambda: len(msgs) >= 1)
        assert msgs[-1]["ok"]
        return sock, msgs

    s1, _ = _connect_and_auth("dev-A", "Phone A")
    s2, _ = _connect_and_auth("dev-B", "Phone B")
    assert len([d for d in server.get_connected_devices() if d["authenticated"]]) == 2

    # Переподключение dev-A после обрыва сети должно закрыть старый сокет без дублирования устройства
    s1_reconnected, _ = _connect_and_auth("dev-A", "Phone A")
    _wait(lambda: len([d for d in server.get_connected_devices() if d["authenticated"]]) == 2)
    auth_ids = sorted(d["device_id"] for d in server.get_connected_devices() if d["authenticated"])
    assert auth_ids == ["dev-A", "dev-B"]

    s1.close()
    s1_reconnected.close()
    s2.close()
    server.stop()
    assert not server.is_running()


def test_multicode_box_scan_and_fuzzy_majority_match(isolated_db):
    """Мульти-скан коробки (IMEI1 + IMEI2 + S/N) и нечёткое совпадение по большинству цифр."""
    proc = MobileProtocolProcessor()

    cat_resp, _ = proc.handle_message(_req("category_create", "c1", {"name": "Смартфоны"}), True)
    cat_id = cat_resp["data"]["category"]["id"]
    prod_resp, _ = proc.handle_message(
        _req("product_create", "p1", {"name": "iPhone 16 Pro", "category_id": cat_id, "brand": "Apple"}),
        True,
    )
    prod_id = prod_resp["data"]["product"]["id"]

    imei1 = "356938035643809"
    imei2 = "490154203237518"
    serial = "F2LZN987ABCD"

    rec, _ = proc.handle_message(
        _req(
            "receive_purchase",
            "rec-multi-1",
            {
                "currency": "USD",
                "exchange_rate": "19.5",
                "items": [
                    {
                        "product_id": prod_id,
                        "quantity": 1,
                        "unit_cost": "1050.00",
                        "imeis": [{"imei1": imei1, "imei2": imei2, "serial_number": serial, "condition": "new"}],
                    }
                ],
            },
        ),
        True,
    )
    assert rec["ok"]

    # 1. Мульти-скан: IMEI 1 повреждён, но S/N в том же пакете совпал точно -> exact match!
    r_exact_sn, _ = proc.handle_message(
        _req(
            "scan_code",
            "s-sn",
            {"code": "356938035600000", "codes": ["356938035600000", serial], "source": "multi"},
        ),
        True,
    )
    assert r_exact_sn["ok"]
    assert r_exact_sn["data"]["match_type"] == "exact"
    assert r_exact_sn["data"]["requires_confirmation"] is False
    assert r_exact_sn["data"]["imei"] == imei1
    assert r_exact_sn["data"]["imei2"] == imei2
    assert r_exact_sn["data"]["serial_number"] == serial

    # 2. Нечёткий скан: 2 цифры IMEI 1 считались с ошибкой (13 из 15 совпали) -> fuzzy + requires_confirmation!
    garbled_imei = "356938035649909"  # 2 цифры изменены (38 -> 99)
    r_fuzzy, _ = proc.handle_message(
        _req("scan_code", "s-fuzzy", {"code": garbled_imei, "codes": [garbled_imei], "source": "ocr"}),
        True,
    )
    assert r_fuzzy["ok"] and r_fuzzy["type"] == "product_card"
    assert r_fuzzy["data"]["match_type"] == "fuzzy"
    assert r_fuzzy["data"]["requires_confirmation"] is True
    assert r_fuzzy["data"]["match_score"] >= 80
    assert r_fuzzy["data"]["imei"] == imei1
    assert r_fuzzy["data"]["scanned_code"] == garbled_imei
    assert r_fuzzy["data"]["matched_code"] == imei1

    # 3. Слишком много ошибок (5 из 15 цифр неверны) -> scan_not_found, не путаем с чужим товаром!
    bad_imei = "356938035699999"
    r_miss, _ = proc.handle_message(
        _req("scan_code", "s-miss", {"code": bad_imei, "codes": [bad_imei], "source": "ocr"}),
        True,
    )
    assert not r_miss["ok"] and r_miss["type"] == "scan_not_found"

