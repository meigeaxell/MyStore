"""Бизнес-обработчик WebSocket-протокола MobileStore v1 (отделён от сети и GUI)."""
import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem
from app.repositories.product_repository import (
    count_category_products,
    create_category,
    deactivate_category,
    find_duplicate_product,
    find_stock_item_by_imei,
    get_product_with_devices,
    list_categories,
    list_products_inventory,
    rename_category,
    save_product,
)
from app.services.accessory_matcher import (
    _get_last_sale_price,
    match_accessory_text,
    record_ocr_alias,
)
from app.services.incoming_queue_service import enqueue_incoming_item
from app.services.purchase_service import create_purchase
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService

logger = logging.getLogger("mobilestore.mobile_protocol")

PROTOCOL_VERSION = 1
SERVER_VERSION = "0.1.0"

MUTATING_COMMANDS = {
    "add_to_sale",
    "product_create",
    "product_update",
    "category_create",
    "category_update",
    "category_deactivate",
    "receive_purchase",
    "queue_incoming_item",
}


def validate_imei_luhn(imei: str) -> bool:
    """Проверяет стандартный 15-значный IMEI по алгоритму Луна (Luhn)."""
    clean = (imei or "").strip()
    if len(clean) != 15 or not clean.isdigit():
        return False
    total = 0
    for idx, ch in enumerate(clean):
        digit = int(ch)
        if idx % 2 == 1:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += digit
    return total % 10 == 0


def _levenshtein_distance(a: str, b: str) -> int:
    """Расстояние Левенштейна между двумя строками (для нечёткого сопоставления IMEI / S/N)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _fuzzy_code_similarity(scanned: str, target: str) -> tuple[int, int, int]:
    """Оценивает совпадение считанного кода и значения в БД.

    Возвращает (score_pct, matching_chars, max_len).
    Порог для валидного нечёткого совпадения: >= 80% и <= 3 отличия.
    """
    s = scanned.strip().upper()
    t = target.strip().upper()
    if not s or not t:
        return 0, 0, 0
    max_len = max(len(s), len(t))
    if abs(len(s) - len(t)) > 3:
        return 0, 0, max_len
    dist = _levenshtein_distance(s, t)
    if dist > 3:
        return 0, 0, max_len
    matching = max(0, max_len - dist)
    pct = round((matching * 100) / max_len)
    if pct < 80:
        return 0, matching, max_len
    return pct, matching, max_len


def make_response(
    msg_type: str,
    request_id: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": msg_type,
        "request_id": request_id,
        "ok": True,
        "data": data if data is not None else {},
        "error": None,
    }


def make_error(
    request_id: str,
    code: str,
    message: str,
    msg_type: str = "error",
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": msg_type,
        "request_id": request_id,
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message},
    }


class MobileProtocolProcessor:
    """Обрабатывает команды мобильных клиентов через существующие сервисы MobileStore."""

    def __init__(
        self,
        add_to_sale_callback: Callable[[dict[str, Any]], tuple[bool, str, dict[str, Any] | None]] | None = None,
        is_imei_in_cart_callback: Callable[[str], bool] | None = None,
        max_idempotency_cache: int = 500,
    ) -> None:
        self._add_to_sale_cb = add_to_sale_callback
        self._is_imei_in_cart_cb = is_imei_in_cart_callback
        self._max_cache = max_idempotency_cache
        self._idempotency_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def _get_cached_response(self, device_id: str, request_id: str) -> dict[str, Any] | None:
        key = (device_id, request_id)
        if key in self._idempotency_cache:
            self._idempotency_cache.move_to_end(key)
            return self._idempotency_cache[key]
        return None

    def _cache_response(self, device_id: str, request_id: str, response: dict[str, Any]) -> None:
        key = (device_id, request_id)
        self._idempotency_cache[key] = response
        self._idempotency_cache.move_to_end(key)
        while len(self._idempotency_cache) > self._max_cache:
            self._idempotency_cache.popitem(last=False)

    def handle_message(
        self,
        message: dict[str, Any],
        is_authenticated: bool,
        connected_count: int = 1,
    ) -> tuple[dict[str, Any], str]:
        """Обрабатывает распарсенное JSON-сообщение.

        Возвращает (response_dict, human_log_summary).
        """
        if not isinstance(message, dict):
            return make_error("", "INVALID_JSON", "JSON obýekti garaşylýar."), "Nädogry paket"

        request_id = str(message.get("request_id") or "").strip()
        msg_type = str(message.get("type") or "").strip()
        device_id = str(message.get("device_id") or "").strip()
        payload = message.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return (
                make_error(request_id, "VALIDATION_ERROR", "payload meýdany obýekt bolmaly."),
                f"payload barlag ýalňyşlygy ({msg_type})",
            )

        version = message.get("protocol_version")
        if version != PROTOCOL_VERSION:
            return (
                make_error(
                    request_id,
                    "UNSUPPORTED_VERSION",
                    f"Goldanylmaýan protokol wersiýasy: {version}. Garaşylýan: {PROTOCOL_VERSION}.",
                ),
                f"Nädogry protokol wersiýasy: {version}",
            )

        if not request_id:
            return (
                make_error("", "VALIDATION_ERROR", "Hökmany request_id ýok."),
                f"request_id-siz haýyş ({msg_type})",
            )

        if msg_type == "ping":
            return (
                make_response("pong", request_id, {"server_time": datetime.now().isoformat(timespec="seconds")}),
                "",
            )

        if msg_type == "auth":
            return self._handle_auth(request_id, device_id, payload, connected_count)

        if not is_authenticated:
            return (
                make_error(request_id, "UNAUTHORIZED", "Enjam tassyklanmadyk. auth geçiň."),
                f"Tassyklanmadyk haýyş ret edildi: {msg_type}",
            )

        if msg_type in MUTATING_COMMANDS and device_id:
            cached = self._get_cached_response(device_id, request_id)
            if cached is not None:
                logger.info("Idempotent replay for %s (%s)", msg_type, request_id)
                return cached, f"{msg_type} gaýtalanan haýyş (idempotent jogap)"

        try:
            handlers: dict[str, Callable[[str, str, dict[str, Any]], tuple[dict[str, Any], str]]] = {
                "scan_code": self._handle_scan_code,
                "match_accessory_ocr": self._handle_match_accessory_ocr,
                "confirm_ocr_alias": self._handle_confirm_ocr_alias,
                "add_to_sale": self._handle_add_to_sale,
                "cancel_operation": self._handle_cancel_operation,
                "check_imei": self._handle_check_imei,
                "receive_purchase": self._handle_receive_purchase,
                "queue_incoming_item": self._handle_queue_incoming_item,
                "catalog_list": self._handle_catalog_list,
                "product_details": self._handle_product_details,
                "product_create": self._handle_product_create,
                "product_update": self._handle_product_update,
                "category_list": self._handle_category_list,
                "category_create": self._handle_category_create,
                "category_update": self._handle_category_update,
                "category_deactivate": self._handle_category_deactivate,
            }
            handler = handlers.get(msg_type)
            if handler is None:
                return (
                    make_error(request_id, "UNKNOWN_COMMAND", f"Näbelli buýruk: {msg_type}"),
                    f"Näbelli buýruk: {msg_type}",
                )

            response, log_line = handler(request_id, device_id, payload)
            if msg_type in MUTATING_COMMANDS and device_id and response.get("ok"):
                self._cache_response(device_id, request_id, response)
            return response, log_line
        except (ValueError, TypeError, KeyError) as err:
            return (
                make_error(request_id, "VALIDATION_ERROR", str(err)),
                f"Barlag ýalňyşlygy ({msg_type}): {err}",
            )
        except (IntegrityError, SQLAlchemyError) as err:
            logger.exception("Database error in mobile protocol %s", msg_type)
            return (
                make_error(request_id, "INTERNAL_ERROR", f"Maglumat bazasynyň ýalňyşlygy: {err}"),
                f"Baza ýalňyşlygy ({msg_type})",
            )

    def _handle_auth(
        self,
        request_id: str,
        device_id: str,
        payload: dict[str, Any],
        connected_count: int,
    ) -> tuple[dict[str, Any], str]:
        token = str(payload.get("token") or "").strip()
        expected = SettingsService.get_or_create_mobile_token()
        effective_device_id = str(payload.get("device_id") or device_id).strip()
        device_name = str(payload.get("device_name") or "Android Scanner").strip()

        if not effective_device_id:
            return (
                make_error(request_id, "VALIDATION_ERROR", "Enjamyň device_id belgisini görkeziň.", "auth_error"),
                "auth ýalňyşlygy: boş device_id",
            )
        if not token or token != expected:
            return (
                make_error(request_id, "UNAUTHORIZED", "Birikme PIN kody nädogry.", "auth_error"),
                f"«{device_name}» enjamdan nädogry PIN",
            )

        cfg = SettingsService.get_all()
        return (
            make_response(
                "auth_ok",
                request_id,
                {
                    "store_name": cfg.get("store_name", "MobileStore"),
                    "default_currency": cfg.get("default_currency", "TMT"),
                    "default_exchange_rate": str(SettingsService.get_default_exchange_rate()),
                    "server_version": SERVER_VERSION,
                    "connected_devices_count": connected_count,
                },
            ),
            f"«{device_name}» telefony birikdi",
        )

    def _build_product_card_data(
        self,
        session,
        product: Product,
        stock_item: StockItem | None,
        match_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cat = session.get(Category, product.category_id)
        default_curr = SettingsService.get("default_currency", "TMT")
        default_rate = SettingsService.get_default_exchange_rate()
        unit_cost, cost_curr, _cost_rate = SalesService._resolve_item_cost_basis(
            session=session,
            product_id=product.id,
            stock_item=stock_item,
            fallback_currency=default_curr,
            fallback_rate=default_rate,
        )
        last_sale_price, last_sale_curr = _get_last_sale_price(session, product.id)

        imei_str = stock_item.imei1 if stock_item else None
        in_cart = bool(imei_str and self._is_imei_in_cart_cb and self._is_imei_in_cart_cb(imei_str))

        if stock_item is not None and stock_item.status != "in_stock":
            avail_status = "sold"
            avail_msg = f"IMEI {stock_item.imei1} enjam eýýäm satyldy"
        elif in_cart:
            avail_status = "in_cart"
            avail_msg = f"IMEI {imei_str} enjam eýýäm häzirki satyşa goşuldy"
        elif product.stock_quantity <= 0:
            avail_status = "out_of_stock"
            avail_msg = f"«{product.name}» harydy skladda ýok"
        else:
            avail_status = "available"
            avail_msg = "Satyş üçin elýeterli"

        info = match_info or {}
        return {
            "product_id": product.id,
            "stock_item_id": stock_item.id if stock_item else None,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand or "",
            "model": product.model or "",
            "specification": product.specification or "",
            "category_id": product.category_id,
            "category_name": cat.name if cat else "Kategoriýasyz",
            "imei": imei_str,
            "imei2": stock_item.imei2 if stock_item else None,
            "serial_number": stock_item.serial_number if stock_item else None,
            "condition": stock_item.condition if stock_item else "new",
            "stock_quantity": product.stock_quantity,
            "unit_cost": f"{unit_cost:.2f}",
            "cost_currency": cost_curr,
            "last_sale_price": f"{last_sale_price:.2f}" if last_sale_price is not None else None,
            "last_sale_currency": last_sale_curr,
            "default_currency": default_curr,
            "exchange_rate": f"{default_rate:.4f}",
            "photo_url": None,
            "availability_status": avail_status,
            "availability_message": avail_msg,
            "match_type": info.get("match_type", "exact"),
            "match_score": int(info.get("match_score", 100)),
            "match_detail": str(info.get("match_detail", "")),
            "scanned_code": info.get("scanned_code"),
            "matched_code": info.get("matched_code"),
            "requires_confirmation": bool(info.get("requires_confirmation", False)),
        }

    @staticmethod
    def _collect_scan_candidates(payload: dict[str, Any]) -> list[str]:
        """Собирает все уникальные коды из мульти-скана коробки в порядке приоритета."""
        raw_list: list[str] = []
        for field in ("imei1", "imei2", "serial_number", "code", "barcode"):
            val = payload.get(field)
            if val:
                raw_list.append(str(val).strip())
        extra = payload.get("codes")
        if isinstance(extra, list):
            for entry in extra:
                if entry:
                    raw_list.append(str(entry).strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for item in raw_list:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def _find_fuzzy_stock_matches(
        self,
        session,
        candidates: list[str],
    ) -> list[tuple[int, int, StockItem, dict[str, Any]]]:
        """Нечёткий поиск по большинству совпавших цифр/символов среди устройств в наличии."""
        numeric_cands = [c for c in candidates if c.isdigit() and 13 <= len(c) <= 16]
        serial_cands = [c for c in candidates if not c.isdigit() and 7 <= len(c) <= 24]
        if not numeric_cands and not serial_cands:
            return []

        in_stock_items = session.scalars(
            select(StockItem).where(StockItem.status == "in_stock")
        ).all()

        scored: list[tuple[int, int, StockItem, dict[str, Any]]] = []
        for st in in_stock_items:
            best_pct = 0
            total_bonus = 0
            matched_fields = 0
            best_meta: dict[str, Any] = {}

            # Проверяем IMEI 1 и IMEI 2
            for field_label, target_val in (("IMEI 1", st.imei1), ("IMEI 2", st.imei2)):
                if not target_val:
                    continue
                field_best = 0
                for cand in numeric_cands:
                    pct, matched, total = _fuzzy_code_similarity(cand, target_val)
                    if pct > field_best:
                        field_best = pct
                        if pct > best_pct:
                            best_pct = pct
                            best_meta = {
                                "match_type": "fuzzy",
                                "match_score": pct,
                                "match_detail": f"{total} sandan {matched} gabat geldi ({field_label})",
                                "scanned_code": cand,
                                "matched_code": target_val,
                                "requires_confirmation": True,
                            }
                if field_best >= 80:
                    matched_fields += 1
                    total_bonus += field_best

            if st.serial_number:
                sn_best = 0
                for cand in serial_cands:
                    pct, matched, total = _fuzzy_code_similarity(cand, st.serial_number)
                    if pct > sn_best:
                        sn_best = pct
                        if pct > best_pct:
                            best_pct = pct
                            best_meta = {
                                "match_type": "fuzzy",
                                "match_score": pct,
                                "match_detail": f"{total} simwoldan {matched} gabat geldi (S/N)",
                                "scanned_code": cand,
                                "matched_code": st.serial_number,
                                "requires_confirmation": True,
                            }
                if sn_best >= 80:
                    matched_fields += 1
                    total_bonus += sn_best

            if best_pct >= 80 and best_meta:
                if matched_fields > 1:
                    best_meta["match_detail"] += f" • {matched_fields} meýdan boýunça tassyklandy"
                scored.append((matched_fields, total_bonus, st, best_meta))

        scored.sort(key=lambda row: (row[0], row[1], row[3]["match_score"]), reverse=True)
        return scored

    def _handle_scan_code(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        candidates = self._collect_scan_candidates(payload)
        if not candidates:
            return make_error(request_id, "VALIDATION_ERROR", "Skanirlenen kod boş."), "Boş skan"
        primary_code = candidates[0]

        with SessionLocal() as session:
            sold_fallback: tuple[StockItem, Product, str, str] | None = None
            for cand in candidates:
                matched_items = session.scalars(
                    select(StockItem).where(
                        (StockItem.imei1 == cand)
                        | (StockItem.imei2 == cand)
                        | (StockItem.serial_number == cand)
                    )
                ).all()
                for st in matched_items:
                    prod = session.get(Product, st.product_id)
                    if prod is None or not prod.is_active:
                        continue
                    if st.imei1 == cand:
                        f_label = "IMEI 1"
                    elif st.imei2 == cand:
                        f_label = "IMEI 2"
                    else:
                        f_label = "S/N"

                    if st.status == "in_stock":
                        card = self._build_product_card_data(
                            session,
                            prod,
                            st,
                            match_info={
                                "match_type": "exact",
                                "match_score": 100,
                                "match_detail": f"Takyk gabat gelme ({f_label})",
                                "scanned_code": cand,
                                "matched_code": cand,
                                "requires_confirmation": False,
                            },
                        )
                        return (
                            make_response("product_card", request_id, card),
                            f"Skan {f_label} {cand} → {prod.name} ({card['availability_status']})",
                        )
                    if sold_fallback is None:
                        sold_fallback = (st, prod, f_label, cand)

            if sold_fallback is not None:
                st, prod, f_label, cand = sold_fallback
                card = self._build_product_card_data(
                    session,
                    prod,
                    st,
                    match_info={
                        "match_type": "exact",
                        "match_score": 100,
                        "match_detail": f"Takyk gabat gelme ({f_label})",
                        "scanned_code": cand,
                        "matched_code": cand,
                        "requires_confirmation": False,
                    },
                )
                return (
                    make_response("product_card", request_id, card),
                    f"Skan {f_label} {cand} → {prod.name} ({card['availability_status']})",
                )

            for cand in candidates:
                if 6 <= len(cand) < 15 and cand.isdigit():
                    partial_items = session.scalars(
                        select(StockItem).where(
                            StockItem.status == "in_stock",
                            (StockItem.imei1.ilike(f"%{cand}%")) | (StockItem.imei2.ilike(f"%{cand}%")),
                        ).limit(5)
                    ).all()
                    if len(partial_items) == 1:
                        st = partial_items[0]
                        prod = session.get(Product, st.product_id)
                        if prod and prod.is_active:
                            card = self._build_product_card_data(
                                session,
                                prod,
                                st,
                                match_info={
                                    "match_type": "exact",
                                    "match_score": 100,
                                    "match_detail": "IMEI bölegi boýunça gabat gelme",
                                    "scanned_code": cand,
                                    "matched_code": st.imei1,
                                    "requires_confirmation": False,
                                },
                            )
                            return (
                                make_response("product_card", request_id, card),
                                f"Bölekleýin IMEI skan {cand} → {prod.name}",
                            )

            fuzzy_hits = self._find_fuzzy_stock_matches(session, candidates)
            if fuzzy_hits:
                top_fields, top_bonus, top_st, top_meta = fuzzy_hits[0]
                top_prod = session.get(Product, top_st.product_id)
                is_clear_winner = (
                    len(fuzzy_hits) == 1
                    or (top_fields > fuzzy_hits[1][0])
                    or (top_bonus - fuzzy_hits[1][1] >= 7)
                )
                if top_prod and top_prod.is_active and is_clear_winner:
                    card = self._build_product_card_data(session, top_prod, top_st, match_info=top_meta)
                    return (
                        make_response("product_card", request_id, card),
                        f"Meňzeş skan ({top_meta['match_detail']}) → {top_prod.name}",
                    )
                fuzzy_cards = []
                for _mf, _tb, st_cand, meta_cand in fuzzy_hits[:5]:
                    p_cand = session.get(Product, st_cand.product_id)
                    if p_cand and p_cand.is_active:
                        fuzzy_cards.append(self._build_product_card_data(session, p_cand, st_cand, match_info=meta_cand))
                if fuzzy_cards:
                    return (
                        make_response("scan_multiple", request_id, {"code": primary_code, "items": fuzzy_cards}),
                        f"Meňzeş skan {primary_code}: {len(fuzzy_cards)} meňzeş enjam",
                    )

            for cand in candidates:
                prod_exact = session.scalar(
                    select(Product).where(
                        Product.is_active.is_(True),
                        (Product.barcode.ilike(cand))
                        | (Product.sku.ilike(cand))
                        | (Product.specification.ilike(f"%{cand}%")),
                    )
                )
                if prod_exact is not None:
                    card = self._build_product_card_data(
                        session,
                        prod_exact,
                        None,
                        match_info={
                            "match_type": "exact",
                            "match_score": 100,
                            "match_detail": "SKU / haryt ştrihkody boýunça gabat gelme",
                            "scanned_code": cand,
                            "matched_code": prod_exact.sku,
                            "requires_confirmation": False,
                        },
                    )
                    return (
                        make_response("product_card", request_id, card),
                        f"Kod skan {cand} → {prod_exact.name}",
                    )

            matches = session.scalars(
                select(Product).where(
                    Product.is_active.is_(True),
                    (Product.sku.ilike(f"%{primary_code}%")) | (Product.name.ilike(f"%{primary_code}%")),
                ).order_by(Product.name).limit(10)
            ).all()
            if len(matches) == 1:
                card = self._build_product_card_data(session, matches[0], None)
                return (
                    make_response("product_card", request_id, card),
                    f"Skan {primary_code} → {matches[0].name}",
                )
            if len(matches) > 1:
                items = [
                    self._build_product_card_data(session, p, None)
                    for p in matches
                ]
                return (
                    make_response("scan_multiple", request_id, {"code": primary_code, "items": items}),
                    f"Skan {primary_code}: {len(items)} gabat gelme tapyldy",
                )

        return (
            make_error(request_id, "NOT_FOUND", f"«{primary_code}» kody ýa-da IMEI MobileStore bazasynda tapylmady.", "scan_not_found"),
            f"Skan {primary_code}: tapylmady",
        )

    def _handle_match_accessory_ocr(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        raw_text = str(payload.get("raw_text") or "").strip()
        if not raw_text:
            return (
                make_error(request_id, "VALIDATION_ERROR", "Guty teksti okalmady. Täzeden synanyşyň."),
                "Boş aksessuar OCR haýyşy",
            )
        cat_raw = payload.get("category_id")
        cat_id = int(cat_raw) if cat_raw is not None and str(cat_raw).strip() != "" else None
        limit = int(payload.get("limit") or 6)

        with SessionLocal() as session:
            result = match_accessory_text(
                session=session,
                raw_text=raw_text,
                category_id=cat_id,
                limit=limit,
            )

        found_n = len(result["items"])
        parsed_q = result["parsed"].get("cleaned_query") or raw_text[:40]
        return (
            make_response("accessory_ocr_matches", request_id, result),
            f"Aksessuar OCR «{parsed_q}» → {found_n} meňzeş haryt",
        )

    def _handle_confirm_ocr_alias(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        product_id = payload.get("product_id")
        raw_text = str(payload.get("raw_text") or "").strip()
        if not product_id or not raw_text:
            return (
                make_error(request_id, "VALIDATION_ERROR", "product_id we raw_text görkeziň."),
                "confirm_ocr_alias ýalňyşlygy",
            )
        with SessionLocal() as session, session.begin():
            alias = record_ocr_alias(session, int(product_id), raw_text)
        saved = alias is not None
        return (
            make_response("operation_ok", request_id, {"saved": saved, "message": "Guty ýatda saklandy"}),
            f"OCR guty ýatda saklandy (product_id={product_id}, saved={saved})",
        )

    def _handle_add_to_sale(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        product_id = payload.get("product_id")
        if not product_id:
            return make_error(request_id, "VALIDATION_ERROR", "product_id görkezilmedik."), "add_to_sale ýalňyşlygy"

        raw_price = payload.get("unit_price")
        try:
            unit_price = Decimal(str(raw_price))
            if unit_price <= Decimal("0.00"):
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return (
                make_error(request_id, "VALIDATION_ERROR", "Satyş bahasy noldan uly bolmaly."),
                "add_to_sale baha ýalňyşlygy",
            )

        qty = int(payload.get("quantity", 1))
        if qty <= 0:
            return make_error(request_id, "VALIDATION_ERROR", "Sany noldan uly bolmaly."), "San ýalňyşlygy"

        currency = str(payload.get("currency") or SettingsService.get("default_currency", "TMT")).strip().upper()
        if currency not in ("USD", "TMT"):
            return make_error(request_id, "VALIDATION_ERROR", "Rugsat berlen walýutalar: USD ýa-da TMT."), "Walýuta ýalňyşlygy"

        imei = (str(payload.get("imei")).strip() or None) if payload.get("imei") else None

        with SessionLocal() as session:
            prod = session.get(Product, int(product_id))
            if not prod or not prod.is_active:
                return make_error(request_id, "NOT_FOUND", "Haryt tapylmady ýa-da öçürilen."), "Haryt tapylmady"
            if prod.stock_quantity < qty:
                return (
                    make_error(request_id, "OUT_OF_STOCK", f"Skladda «{prod.name}» harydy ýeterlik däl."),
                    f"Galyndy ýok: {prod.name}",
                )
            if imei:
                st = session.scalar(
                    select(StockItem).where(
                        StockItem.product_id == prod.id,
                        (StockItem.imei1 == imei) | (StockItem.imei2 == imei),
                    )
                )
                if st is None:
                    return make_error(request_id, "NOT_FOUND", f"IMEI {imei} skladda tapylmady."), "IMEI tapylmady"
                if st.status != "in_stock":
                    return make_error(request_id, "ALREADY_SOLD", f"IMEI {imei} enjam eýýäm satyldy."), "Eýýäm satyldy"
                qty = 1

        if self._add_to_sale_cb is None:
            return (
                make_error(request_id, "INTERNAL_ERROR", "Kassa bölümi serwera birikdirilmedik."),
                "Kassa işledijisi ýok",
            )

        ok, message, extra = self._add_to_sale_cb({
            "product_id": int(product_id),
            "imei": imei,
            "quantity": qty,
            "unit_price": unit_price,
            "currency": currency,
        })
        if not ok:
            low = message.lower()
            err_code = "ALREADY_IN_CART" if ("eýýäm" in low or "уже добавлен" in low) else "OUT_OF_STOCK"
            return make_error(request_id, err_code, message), f"Kassa ret etdi: {message}"

        ocr_raw_text = str(payload.get("ocr_raw_text") or "").strip()
        if ocr_raw_text:
            with SessionLocal() as session, session.begin():
                record_ocr_alias(session, int(product_id), ocr_raw_text)

        data = {"message": message, **(extra or {})}
        return make_response("operation_ok", request_id, data), message

    def _handle_cancel_operation(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        reason = str(payload.get("reason") or "cancelled").strip()
        return (
            make_response("operation_ok", request_id, {"message": "Amal ýatyryldy", "reason": reason}),
            f"Telefonda amal ýatyryldy ({reason})",
        )

    def _handle_check_imei(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        imei1 = str(payload.get("imei1") or "").strip()
        imei2 = str(payload.get("imei2") or "").strip() or None
        if not imei1:
            return make_error(request_id, "VALIDATION_ERROR", "Barlamak üçin IMEI 1 giriziň."), "Boş IMEI"

        luhn_ok = validate_imei_luhn(imei1)
        ex1 = find_stock_item_by_imei(imei1)
        ex2 = find_stock_item_by_imei(imei2) if imei2 else None

        if ex1 is not None:
            status_lbl = "Skladda bar" if ex1["status"] == "in_stock" else "Satyldy"
            return (
                make_response(
                    "imei_check_result",
                    request_id,
                    {
                        "imei1": imei1,
                        "luhn_valid": luhn_ok,
                        "exists_in_db": True,
                        "can_receive": False,
                        "existing_product": ex1["product_name"],
                        "existing_status": ex1["status"],
                        "message": f"IMEI {imei1} eýýäm bazada bar ({ex1['product_name']}, {status_lbl}).",
                    },
                ),
                f"IMEI barlagy {imei1}: gaýtalanma",
            )
        if ex2 is not None:
            return (
                make_response(
                    "imei_check_result",
                    request_id,
                    {
                        "imei1": imei1,
                        "luhn_valid": luhn_ok,
                        "exists_in_db": True,
                        "can_receive": False,
                        "existing_product": ex2["product_name"],
                        "existing_status": ex2["status"],
                        "message": f"IMEI 2 ({imei2}) eýýäm bazada bar ({ex2['product_name']}).",
                    },
                ),
                f"IMEI2 barlagy {imei2}: gaýtalanma",
            )

        msg = (
            "IMEI dogry we kabul ediş üçin boş"
            if luhn_ok
            else "IMEI boş, ýöne Luhn (15 san) barlagyna gabat gelmeýär. Girizilen belgini barlaň."
        )
        return (
            make_response(
                "imei_check_result",
                request_id,
                {
                    "imei1": imei1,
                    "luhn_valid": luhn_ok,
                    "exists_in_db": False,
                    "can_receive": True,
                    "message": msg,
                },
            ),
            f"IMEI barlagy {imei1}: boş (Luhn={luhn_ok})",
        )

    def _handle_receive_purchase(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            return make_error(request_id, "VALIDATION_ERROR", "Kabul ediş sanawy boş."), "Boş kabul ediş"

        currency = str(payload.get("currency") or "USD").strip().upper()
        rate = payload.get("exchange_rate") or SettingsService.get_default_exchange_rate()
        supplier_name = str(payload.get("supplier_name") or "").strip() or None
        note = str(payload.get("note") or "Android skaner arkaly kabul ediş").strip()

        purchase_id = create_purchase(
            items=items,
            currency=currency,
            exchange_rate=rate,
            payments=payload.get("payments") or [],
            note=note,
            supplier_name=supplier_name,
        )
        top_ocr = str(payload.get("ocr_raw_text") or "").strip()
        if top_ocr and items:
            first_pid = items[0].get("product_id")
            if first_pid:
                with SessionLocal() as session, session.begin():
                    record_ocr_alias(session, int(first_pid), top_ocr)
        for item in items:
            item_ocr = str(item.get("ocr_raw_text") or "").strip()
            if item_ocr and item.get("product_id"):
                with SessionLocal() as session, session.begin():
                    record_ocr_alias(session, int(item["product_id"]), item_ocr)

        total_units = sum(int(i.get("quantity", 0)) for i in items)
        msg = f"Alyş №{purchase_id} üstünlikli geçirildi ({total_units} sany kabul edildi)"
        return (
            make_response("operation_ok", request_id, {"purchase_id": purchase_id, "message": msg}),
            msg,
        )

    def _handle_queue_incoming_item(
        self,
        request_id: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        dev_name = str(payload.get("device_name") or device_id or "Android Scanner").strip()
        result = enqueue_incoming_item(payload, device_name=dev_name)
        return (
            make_response("incoming_queued", request_id, result),
            result["message"],
        )

    def _handle_catalog_list(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        q = str(payload.get("query") or "").strip().lower()
        cat_id = payload.get("category_id")
        limit = min(300, max(1, int(payload.get("limit") or 100)))

        products, _cats = list_products_inventory()
        result = []
        for p in products:
            if cat_id is not None and p["category_id"] != int(cat_id):
                continue
            if q:
                hay = " ".join([
                    p["sku"],
                    p.get("barcode", ""),
                    p["name"],
                    p["brand"],
                    p["model"],
                    p["specification"],
                    p["category"],
                    p["imei_search_blob"],
                ]).lower()
                if q not in hay:
                    continue
            result.append({
                "id": p["id"],
                "sku": p["sku"],
                "barcode": p.get("barcode", ""),
                "name": p["name"],
                "category_id": p["category_id"],
                "category": p["category"],
                "brand": p["brand"],
                "model": p["model"],
                "specification": p["specification"],
                "stock_quantity": p["quantity"],
                "min_stock_quantity": p["minimum"],
                "new_devices": p["new_devices"],
                "used_devices": p["used_devices"],
            })
            if len(result) >= limit:
                break

        return (
            make_response("catalog_list", request_id, {"products": result, "total": len(result)}),
            f"Katalog haýyşy ({len(result)} setir)",
        )

    def _handle_product_details(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        product_id = payload.get("product_id")
        if not product_id:
            return make_error(request_id, "VALIDATION_ERROR", "product_id görkeziň."), "product_id ýok"

        product, _in_stock_cnt, items = get_product_with_devices(int(product_id))
        if product is None:
            return make_error(request_id, "NOT_FOUND", "Haryt tapylmady."), "Haryt tapylmady"

        default_cost = SettingsService.get_product_default_cost(product.id)
        prod_dict = {
            "id": product.id,
            "sku": product.sku,
            "barcode": product.barcode or "",
            "name": product.name,
            "category_id": product.category_id,
            "brand": product.brand or "",
            "model": product.model or "",
            "specification": product.specification or "",
            "stock_quantity": product.stock_quantity,
            "min_stock_quantity": product.min_stock_quantity,
            "default_cost": f"{default_cost[0]:.2f}" if default_cost else "0.00",
            "default_cost_currency": default_cost[1] if default_cost else "USD",
        }
        devices_list = [
            {
                "id": st.id,
                "imei1": st.imei1,
                "imei2": st.imei2,
                "serial_number": st.serial_number,
                "condition": st.condition,
                "status": st.status,
                "unit_cost": f"{Decimal(str(st.unit_cost)):.2f}" if st.unit_cost is not None else "0.00",
                "cost_currency": st.cost_currency or "USD",
                "notes": st.notes or "",
            }
            for st in items
        ]
        return (
            make_response("product_details", request_id, {"product": prod_dict, "devices": devices_list}),
            f"«{product.name}» haryt karty ({len(devices_list)} IMEI)",
        )

    def _handle_product_create(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        name = str(payload.get("name") or "").strip()
        brand = str(payload.get("brand") or "").strip() or None
        model = str(payload.get("model") or "").strip() or None
        spec = str(payload.get("specification") or "").strip() or None
        allow_dup = bool(payload.get("allow_duplicate", False))

        if not allow_dup:
            dup = find_duplicate_product(name, brand, model, spec)
            if dup is not None:
                return (
                    make_error(
                        request_id,
                        "DUPLICATE_PRODUCT",
                        f"Şu aýratynlykly «{dup.name}» ({dup.sku}) harydy eýýäm bar.",
                    ),
                    f"Gaýtalanýan haryt ret edildi: {name}",
                )

        product = save_product(
            product_id=None,
            name=name,
            category_id=int(payload["category_id"]) if payload.get("category_id") is not None else None,
            brand=brand,
            model=model,
            specification=spec,
            stock_quantity=int(payload.get("stock_quantity") or 0),
            min_stock_quantity=int(payload.get("min_stock_quantity") or SettingsService.get_default_min_stock()),
            barcode=str(payload.get("barcode") or "").strip() or None,
        )
        raw_cost = payload.get("unit_cost")
        if raw_cost is not None and Decimal(str(raw_cost)) > 0:
            SettingsService.set_product_default_cost(
                product.id,
                Decimal(str(raw_cost)),
                str(payload.get("cost_currency") or "USD"),
            )

        ocr_raw_text = str(payload.get("ocr_raw_text") or "").strip()
        if ocr_raw_text:
            with SessionLocal() as session, session.begin():
                record_ocr_alias(session, product.id, ocr_raw_text)

        return (
            make_response(
                "operation_ok",
                request_id,
                {
                    "message": f"«{product.name}» ({product.sku}) harydy döredildi",
                    "product": {
                        "id": product.id,
                        "sku": product.sku,
                        "name": product.name,
                        "category_id": product.category_id,
                        "brand": product.brand or "",
                        "model": product.model or "",
                        "specification": product.specification or "",
                        "stock_quantity": product.stock_quantity,
                        "min_stock_quantity": product.min_stock_quantity,
                    },
                },
            ),
            f"«{product.name}» ({product.sku}) harydy döredildi",
        )

    def _handle_product_update(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        product_id = payload.get("product_id")
        if not product_id:
            return make_error(request_id, "VALIDATION_ERROR", "product_id görkeziň."), "product_id ýok"

        product = save_product(
            product_id=int(product_id),
            name=str(payload.get("name") or ""),
            category_id=int(payload["category_id"]) if payload.get("category_id") is not None else None,
            brand=str(payload.get("brand") or ""),
            model=str(payload.get("model") or ""),
            specification=str(payload.get("specification") or ""),
            stock_quantity=int(payload.get("stock_quantity") or 0),
            min_stock_quantity=int(payload.get("min_stock_quantity") or 0),
            barcode=str(payload.get("barcode") or "").strip() or None,
        )
        raw_cost = payload.get("unit_cost")
        if raw_cost is not None and Decimal(str(raw_cost)) > 0:
            SettingsService.set_product_default_cost(
                product.id,
                Decimal(str(raw_cost)),
                str(payload.get("cost_currency") or "USD"),
            )

        ocr_raw_text = str(payload.get("ocr_raw_text") or "").strip()
        if ocr_raw_text:
            with SessionLocal() as session, session.begin():
                record_ocr_alias(session, product.id, ocr_raw_text)

        return (
            make_response(
                "operation_ok",
                request_id,
                {
                    "message": f"«{product.name}» harydy täzelendi",
                    "product": {
                        "id": product.id,
                        "sku": product.sku,
                        "name": product.name,
                        "category_id": product.category_id,
                        "brand": product.brand or "",
                        "model": product.model or "",
                        "specification": product.specification or "",
                        "stock_quantity": product.stock_quantity,
                        "min_stock_quantity": product.min_stock_quantity,
                    },
                },
            ),
            f"«{product.name}» harydy täzelendi",
        )

    def _handle_category_list(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        active_only = bool(payload.get("active_only", False))
        cats = list_categories(active_only=active_only)
        items = [
            {
                "id": c.id,
                "name": c.name,
                "code": c.code,
                "is_active": c.is_active,
                "product_count": count_category_products(c.id, active_only=True),
            }
            for c in cats
        ]
        return (
            make_response("category_list", request_id, {"categories": items}),
            f"Kategoriýa haýyşy ({len(items)})",
        )

    def _handle_category_create(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        cat = create_category(str(payload.get("name") or ""))
        return (
            make_response(
                "operation_ok",
                request_id,
                {
                    "message": f"«{cat.name}» kategoriýasy döredildi",
                    "category": {
                        "id": cat.id,
                        "name": cat.name,
                        "code": cat.code,
                        "is_active": cat.is_active,
                        "product_count": 0,
                    },
                },
            ),
            f"«{cat.name}» kategoriýasy döredildi",
        )

    def _handle_category_update(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        cat_id = payload.get("category_id")
        if not cat_id:
            return make_error(request_id, "VALIDATION_ERROR", "category_id görkeziň."), "category_id ýok"
        new_name = str(payload.get("name") or "")
        rename_category(int(cat_id), new_name)
        return (
            make_response(
                "operation_ok",
                request_id,
                {"message": f"Kategoriýanyň ady «{new_name.strip()}» boldy", "category_id": int(cat_id)},
            ),
            f"#{cat_id} kategoriýanyň ady üýtgedildi",
        )

    def _handle_category_deactivate(
        self,
        request_id: str,
        _device_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        cat_id = payload.get("category_id")
        if not cat_id:
            return make_error(request_id, "VALIDATION_ERROR", "category_id görkeziň."), "category_id ýok"
        force = bool(payload.get("force", False))
        prod_count = count_category_products(int(cat_id), active_only=True)
        if prod_count > 0 and not force:
            return (
                make_error(
                    request_id,
                    "VALIDATION_ERROR",
                    f"Kategoriýada {prod_count} işjeň haryt bar. Öçürmegi gaýtadan tassyklaň.",
                ),
                f"#{cat_id} kategoriýa ulanylýar ({prod_count} haryt)",
            )
        deactivate_category(int(cat_id))
        return (
            make_response(
                "operation_ok",
                request_id,
                {
                    "message": "Kategoriýa öçürildi",
                    "category_id": int(cat_id),
                    "active_products_count": prod_count,
                },
            ),
            f"#{cat_id} kategoriýa öçürildi",
        )
