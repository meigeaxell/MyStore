"""Сервис буферной очереди приёмки (Incoming Queue) между мобильным сканером и ПК."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.incoming_queue_item import IncomingQueueItem
from app.models.product import Product
from app.repositories.product_repository import (
    find_stock_item_by_imei,
    register_standalone_phone,
    save_product,
)
from app.services.accessory_matcher import record_ocr_alias
from app.services.purchase_service import create_purchase
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService


def _parse_optional_cost(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".")
    if not s:
        return None
    try:
        val = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError("Alyş bahasy nädogry.") from exc
    if val < 0:
        raise ValueError("Alyş bahasy otrisatel bolup bilmez.")
    return val.quantize(Decimal("0.01"))


def count_queue_items() -> dict[str, int]:
    """Возвращает количество ожидающих позиций в очереди по вкладкам."""
    counts = {"known": 0, "unknown": 0, "phone_imei": 0, "total": 0}
    with SessionLocal() as session:
        rows = session.execute(
            select(IncomingQueueItem.item_kind, func.count(IncomingQueueItem.id))
            .group_by(IncomingQueueItem.item_kind)
        ).all()
        for kind, cnt in rows:
            n = int(cnt or 0)
            if kind in counts:
                counts[kind] = n
            counts["total"] += n
    return counts


def enqueue_incoming_item(payload: dict[str, Any], device_name: str = "") -> dict[str, Any]:
    """Добавляет отсканированную позицию с телефона в буферную очередь ПК.

    Автоматически распределяет по 3 вкладкам:
    - phone_imei: если передан IMEI (или mode == 'imei')
    - known: если найден товар в каталоге (по product_id или штрихкоду) — склеивает quantity += qty
    - unknown: новый штрихкод / нераспознанный OCR — склеивает по одинаковому штрихкоду
    """
    mode = str(payload.get("mode") or "").strip().lower()
    imei1 = str(payload.get("imei1") or "").strip() or None
    imei2 = str(payload.get("imei2") or "").strip() or None
    serial_number = str(payload.get("serial_number") or "").strip() or None
    barcode = str(payload.get("barcode") or payload.get("code") or "").strip() or None
    condition = "used" if str(payload.get("condition") or "new").strip().lower() in ("used", "b/u", "б/у") else "new"
    model_hint = str(payload.get("model_hint") or payload.get("note") or "").strip() or None
    ocr_raw_text = str(payload.get("ocr_raw_text") or "").strip() or None
    supplier_name = str(payload.get("supplier_name") or "").strip() or None
    currency = str(payload.get("currency") or SettingsService.get("default_currency", "USD")).strip().upper()
    if currency not in ("USD", "TMT"):
        currency = "USD"
    unit_cost = _parse_optional_cost(payload.get("unit_cost"))
    clean_device = (device_name or str(payload.get("device_name") or "")).strip() or None

    raw_qty = payload.get("quantity", 1)
    try:
        qty = int(raw_qty)
    except (TypeError, ValueError) as exc:
        raise ValueError("Sany položitel bitin san bolmaly.") from exc
    if qty <= 0:
        raise ValueError("Sany noldan uly bolmaly.")

    # 1. Режим телефона (IMEI)
    if mode == "imei" or imei1:
        if not imei1:
            raise ValueError("IMEI 1 giriziň.")
        if imei2 and imei1 == imei2:
            raise ValueError("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")

        ex_db = find_stock_item_by_imei(imei1)
        if ex_db is not None:
            raise ValueError(f"IMEI {imei1} eýýäm skladda/bazada hasaba alnan ({ex_db['product_name']}).")
        if imei2:
            ex_db2 = find_stock_item_by_imei(imei2)
            if ex_db2 is not None:
                raise ValueError(f"IMEI 2 ({imei2}) eýýäm bazada hasaba alnan ({ex_db2['product_name']}).")

        with SessionLocal() as session, session.begin():
            dup_q = session.scalar(
                select(IncomingQueueItem).where(
                    (IncomingQueueItem.imei1 == imei1)
                    | (IncomingQueueItem.imei2 == imei1)
                    | (
                        (IncomingQueueItem.imei1 == imei2) | (IncomingQueueItem.imei2 == imei2)
                        if imei2
                        else False
                    )
                )
            )
            if dup_q is not None:
                raise ValueError(f"IMEI {imei1} eýýäm PK kabul ediş nobatynda bar.")

            row = IncomingQueueItem(
                item_kind="phone_imei",
                product_id=None,
                barcode=barcode,
                imei1=imei1,
                imei2=imei2,
                serial_number=serial_number,
                condition=condition,
                model_hint=model_hint,
                ocr_raw_text=ocr_raw_text,
                quantity=1,
                unit_cost=unit_cost,
                currency=currency,
                supplier_name=supplier_name,
                device_name=clean_device,
                created_at=datetime.now(),
            )
            session.add(row)
            session.flush()
            q_id = row.id

        counts = count_queue_items()
        cond_lbl = "B/U" if condition == "used" else "Täze"
        msg = f"Telefon ({cond_lbl}, IMEI {imei1}) PK nobatyna goşuldy"
        return {
            "queue_id": q_id,
            "item_kind": "phone_imei",
            "merged": False,
            "quantity": 1,
            "product_name": model_hint or f"IMEI {imei1}",
            "message": msg,
            "counts": counts,
        }

    # 2. Режим количественных товаров (Известный / Неизвестный)
    raw_pid = payload.get("product_id")
    product_id = int(raw_pid) if raw_pid is not None and str(raw_pid).strip() != "" else None

    if product_id is None and not barcode and not ocr_raw_text and not model_hint:
        raise ValueError("Haryt, ştrihkod ýa-da guty teksti görkezilmedi.")

    with SessionLocal() as session, session.begin():
        resolved_product: Product | None = None
        if product_id is not None:
            resolved_product = session.scalar(
                select(Product).where(
                    Product.id == product_id,
                    Product.is_active.is_(True),
                )
            )
        if resolved_product is None and barcode:
            bc_matches = session.scalars(
                select(Product).where(
                    Product.is_active.is_(True),
                    Product.is_phone_unit.is_(False),
                    (Product.barcode == barcode) | (Product.sku == barcode),
                )
            ).all()
            if len(bc_matches) == 1:
                resolved_product = bc_matches[0]

        if resolved_product is not None:
            # Ищем уже ожидающую строку того же известного товара -> склеиваем количество
            existing = session.scalar(
                select(IncomingQueueItem)
                .where(
                    IncomingQueueItem.item_kind == "known",
                    IncomingQueueItem.product_id == resolved_product.id,
                )
                .order_by(IncomingQueueItem.id.desc())
            )
            if existing is not None:
                existing.quantity += qty
                if unit_cost is not None and unit_cost > 0:
                    existing.unit_cost = unit_cost
                    existing.currency = currency
                if supplier_name:
                    existing.supplier_name = supplier_name
                if ocr_raw_text and not existing.ocr_raw_text:
                    existing.ocr_raw_text = ocr_raw_text
                if model_hint:
                    existing.model_hint = model_hint
                session.flush()
                q_id = existing.id
                final_qty = existing.quantity
                merged = True
            else:
                row = IncomingQueueItem(
                    item_kind="known",
                    product_id=resolved_product.id,
                    barcode=barcode or resolved_product.barcode,
                    condition="new",
                    model_hint=model_hint,
                    ocr_raw_text=ocr_raw_text,
                    quantity=qty,
                    unit_cost=unit_cost,
                    currency=currency,
                    supplier_name=supplier_name,
                    device_name=clean_device,
                    created_at=datetime.now(),
                )
                session.add(row)
                session.flush()
                q_id = row.id
                final_qty = qty
                merged = False
            prod_name = resolved_product.name
            item_kind = "known"
            msg = f"«{prod_name}» belli harytlar nobatyna goşuldy (jemi: {final_qty} sany)"
        else:
            # Неизвестный товар -> склеиваем, если совпал штрихкод и примечание (model_hint)
            existing = None
            if barcode:
                candidates = session.scalars(
                    select(IncomingQueueItem)
                    .where(
                        IncomingQueueItem.item_kind == "unknown",
                        IncomingQueueItem.barcode == barcode,
                    )
                    .order_by(IncomingQueueItem.id.desc())
                ).all()
                norm_hint = (model_hint or "").strip().lower()
                for cand in candidates:
                    if (cand.model_hint or "").strip().lower() == norm_hint:
                        existing = cand
                        break
            if existing is not None:
                existing.quantity += qty
                if unit_cost is not None and unit_cost > 0:
                    existing.unit_cost = unit_cost
                    existing.currency = currency
                if supplier_name:
                    existing.supplier_name = supplier_name
                if ocr_raw_text and not existing.ocr_raw_text:
                    existing.ocr_raw_text = ocr_raw_text
                if model_hint:
                    existing.model_hint = model_hint
                session.flush()
                q_id = existing.id
                final_qty = existing.quantity
                merged = True
            else:
                row = IncomingQueueItem(
                    item_kind="unknown",
                    product_id=None,
                    barcode=barcode,
                    condition="new",
                    model_hint=model_hint,
                    ocr_raw_text=ocr_raw_text,
                    quantity=qty,
                    unit_cost=unit_cost,
                    currency=currency,
                    supplier_name=supplier_name,
                    device_name=clean_device,
                    created_at=datetime.now(),
                )
                session.add(row)
                session.flush()
                q_id = row.id
                final_qty = qty
                merged = False
            prod_name = barcode or model_hint or (ocr_raw_text[:40] if ocr_raw_text else "Näbelli haryt")
            item_kind = "unknown"
            msg = f"«{prod_name}» näbelli harytlar nobatyna goşuldy (jemi: {final_qty} sany)"

    counts = count_queue_items()
    return {
        "queue_id": q_id,
        "item_kind": item_kind,
        "merged": merged,
        "quantity": final_qty,
        "product_name": prod_name,
        "message": msg,
        "counts": counts,
    }


def list_queue_items(item_kind: str | None = None) -> list[dict[str, Any]]:
    """Возвращает позиции буферной очереди с обогащёнными данными товара (для 'known')."""
    default_curr = SettingsService.get("default_currency", "USD")
    default_rate = SettingsService.get_default_exchange_rate()

    with SessionLocal() as session:
        stmt = select(IncomingQueueItem).order_by(IncomingQueueItem.created_at.desc(), IncomingQueueItem.id.desc())
        if item_kind:
            stmt = stmt.where(IncomingQueueItem.item_kind == item_kind)
        rows = session.scalars(stmt).all()

        prod_ids = [r.product_id for r in rows if r.product_id is not None]
        prod_map: dict[int, tuple[Product, str]] = {}
        if prod_ids:
            p_rows = session.execute(
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(Product.id.in_(prod_ids))
            ).all()
            for prod, cat_name in p_rows:
                prod_map[prod.id] = (prod, cat_name or "—")

        result: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "id": r.id,
                "item_kind": r.item_kind,
                "product_id": r.product_id,
                "barcode": r.barcode or "",
                "imei1": r.imei1 or "",
                "imei2": r.imei2 or "",
                "serial_number": r.serial_number or "",
                "condition": r.condition or "new",
                "model_hint": r.model_hint or "",
                "ocr_raw_text": r.ocr_raw_text or "",
                "quantity": int(r.quantity or 1),
                "unit_cost": Decimal(str(r.unit_cost)) if r.unit_cost is not None else Decimal("0.00"),
                "currency": (r.currency or default_curr).upper(),
                "supplier_name": r.supplier_name or "",
                "device_name": r.device_name or "",
                "created_at": r.created_at,
                "product_name": "",
                "category": "",
                "brand": "",
                "model": "",
                "current_stock": 0,
            }
            if r.product_id and r.product_id in prod_map:
                prod, cat_name = prod_map[r.product_id]
                entry["product_name"] = prod.name
                entry["category"] = cat_name
                entry["brand"] = prod.brand or ""
                entry["model"] = prod.model or ""
                entry["current_stock"] = int(prod.stock_quantity or 0)
                if entry["unit_cost"] <= 0:
                    u_cost, c_curr, _r = SalesService._resolve_item_cost_basis(
                        session=session,
                        product_id=prod.id,
                        stock_item=None,
                        fallback_currency=entry["currency"],
                        fallback_rate=default_rate,
                    )
                    if u_cost > 0:
                        entry["unit_cost"] = u_cost
                        entry["currency"] = c_curr
            result.append(entry)
        return result


def update_queue_item(
    queue_id: int,
    quantity: int | None = None,
    unit_cost: Decimal | float | str | None = None,
    currency: str | None = None,
    model_hint: str | None = None,
    condition: str | None = None,
) -> None:
    """Обновляет количество/цену/подсказку строки очереди на ПК."""
    with SessionLocal() as session, session.begin():
        row = session.get(IncomingQueueItem, int(queue_id))
        if row is None:
            raise ValueError("Nobatdaky ýazgy tapylmady.")
        if quantity is not None:
            q = int(quantity)
            if q <= 0:
                raise ValueError("Sany noldan uly bolmaly.")
            row.quantity = q
        if unit_cost is not None:
            parsed_cost = _parse_optional_cost(unit_cost)
            row.unit_cost = parsed_cost
        if currency is not None and currency.strip().upper() in ("USD", "TMT"):
            row.currency = currency.strip().upper()
        if model_hint is not None:
            row.model_hint = model_hint.strip() or None
        if condition is not None:
            row.condition = "used" if condition.strip().lower() in ("used", "b/u") else "new"


def delete_queue_item(queue_id: int) -> None:
    with SessionLocal() as session, session.begin():
        row = session.get(IncomingQueueItem, int(queue_id))
        if row is not None:
            session.delete(row)


def clear_queue(item_kind: str | None = None) -> int:
    with SessionLocal() as session, session.begin():
        stmt = select(IncomingQueueItem)
        if item_kind:
            stmt = stmt.where(IncomingQueueItem.item_kind == item_kind)
        rows = session.scalars(stmt).all()
        n = len(rows)
        for r in rows:
            session.delete(r)
        return n


def commit_known_items(
    queue_ids: list[int],
    supplier_name: str | None = None,
    currency: str = "USD",
    exchange_rate: Decimal | float | str | None = None,
    paid_amount: Decimal | float | str = Decimal("0.00"),
    note: str | None = None,
    overrides: dict[int, dict[str, Any]] | None = None,
) -> int:
    """Проводит один или несколько известных товаров из очереди одним документом закупки."""
    if not queue_ids:
        raise ValueError("Geçirmek üçin iň azyndan bir haryt saýlaň.")

    overrides = overrides or {}
    rate = Decimal(str(exchange_rate)) if exchange_rate else SettingsService.get_default_exchange_rate()
    curr = (currency or "USD").strip().upper()
    paid_dec = _parse_optional_cost(paid_amount) or Decimal("0.00")

    purchase_items: list[dict[str, Any]] = []
    ocr_pairs: list[tuple[int, str]] = []
    valid_ids: list[int] = []

    with SessionLocal() as session:
        rows = session.scalars(
            select(IncomingQueueItem).where(
                IncomingQueueItem.id.in_(queue_ids),
                IncomingQueueItem.item_kind == "known",
            )
        ).all()
        if not rows:
            raise ValueError("Saýlanan belli harytlar nobatda tapylmady.")

        for r in rows:
            if not r.product_id:
                raise ValueError(f"Nobat #{r.id} üçin haryt görkezilmedik.")
            ov = overrides.get(r.id, {})
            qty = int(ov.get("quantity", r.quantity or 1))
            if qty <= 0:
                raise ValueError("Harydyň sany noldan uly bolmaly.")
            cost = _parse_optional_cost(ov.get("unit_cost", r.unit_cost)) or Decimal("0.00")
            purchase_items.append({
                "product_id": int(r.product_id),
                "quantity": qty,
                "unit_cost": cost,
            })
            if r.ocr_raw_text:
                ocr_pairs.append((int(r.product_id), r.ocr_raw_text))
            valid_ids.append(r.id)

    payments = []
    if paid_dec > 0:
        payments.append({
            "currency": curr,
            "amount": paid_dec,
            "exchange_rate": rate,
        })

    purchase_id = create_purchase(
        items=purchase_items,
        currency=curr,
        exchange_rate=rate,
        payments=payments,
        note=(note or "Kabul ediş nobatyndan geçirildi").strip(),
        supplier_name=(supplier_name or "").strip() or None,
    )

    with SessionLocal() as session, session.begin():
        for pid, raw_txt in ocr_pairs:
            record_ocr_alias(session, pid, raw_txt)
        for qid in valid_ids:
            row = session.get(IncomingQueueItem, qid)
            if row is not None:
                session.delete(row)

    return purchase_id


def commit_unknown_item(
    queue_id: int,
    name: str,
    category_id: int,
    quantity: int,
    unit_cost: Decimal | float | str = Decimal("0.00"),
    currency: str = "USD",
    exchange_rate: Decimal | float | str | None = None,
    brand: str | None = None,
    model: str | None = None,
    specification: str | None = None,
    barcode: str | None = None,
    min_stock: int = 0,
    supplier_name: str | None = None,
    paid_amount: Decimal | float | str = Decimal("0.00"),
    note: str | None = None,
) -> tuple[int, int | None]:
    """Создаёт новый товар из вкладки 'Неизвестные', приходует количество и удаляет из очереди."""
    with SessionLocal() as session:
        q_row = session.get(IncomingQueueItem, int(queue_id))
        if q_row is None:
            raise ValueError("Nobatdaky ýazgy tapylmady.")
        saved_ocr = q_row.ocr_raw_text
        effective_barcode = (barcode if barcode is not None else q_row.barcode) or None

    cost_dec = _parse_optional_cost(unit_cost) or Decimal("0.00")
    curr = (currency or "USD").strip().upper()
    rate = Decimal(str(exchange_rate)) if exchange_rate else SettingsService.get_default_exchange_rate()
    paid_dec = _parse_optional_cost(paid_amount) or Decimal("0.00")

    product = save_product(
        product_id=None,
        name=name,
        category_id=category_id,
        brand=brand,
        model=model,
        specification=specification,
        stock_quantity=0,
        min_stock_quantity=int(min_stock or 0),
        barcode=effective_barcode,
        default_cost=cost_dec,
        default_cost_currency=curr,
    )
    if cost_dec > 0:
        SettingsService.set_product_default_cost(product.id, cost_dec, curr)

    purchase_id: int | None = None
    qty = int(quantity or 0)
    if qty > 0:
        payments = []
        if paid_dec > 0:
            payments.append({
                "currency": curr,
                "amount": paid_dec,
                "exchange_rate": rate,
            })
        purchase_id = create_purchase(
            items=[{
                "product_id": product.id,
                "quantity": qty,
                "unit_cost": cost_dec,
            }],
            currency=curr,
            exchange_rate=rate,
            payments=payments,
            note=(note or f"Näbelli haryt nobatdan goşuldy: {product.name}").strip(),
            supplier_name=(supplier_name or "").strip() or None,
        )

    with SessionLocal() as session, session.begin():
        if saved_ocr:
            record_ocr_alias(session, product.id, saved_ocr)
        row = session.get(IncomingQueueItem, int(queue_id))
        if row is not None:
            session.delete(row)

    return product.id, purchase_id


def commit_phone_item(
    queue_id: int,
    model_name: str,
    imei1: str,
    memory: str | None = None,
    color: str | None = None,
    imei2: str | None = None,
    serial_number: str | None = None,
    condition: str = "new",
    battery_health: str | None = None,
    cosmetic_condition: str | None = None,
    unit_cost: Decimal | float | str = Decimal("0.00"),
    currency: str = "USD",
    exchange_rate: Decimal | float | str | None = None,
    supplier_name: str | None = None,
    paid_amount: Decimal | float | str = Decimal("0.00"),
    acquisition_source: str | None = None,
    notes: str | None = None,
) -> tuple[int, int]:
    """Оформляет телефон из вкладки 'Telefonlar (IMEI)' как самостоятельную единицу и удаляет из очереди."""
    with SessionLocal() as session:
        q_row = session.get(IncomingQueueItem, int(queue_id))
        if q_row is None:
            raise ValueError("Nobatdaky telefon tapylmady.")

    rate = Decimal(str(exchange_rate)) if exchange_rate else SettingsService.get_default_exchange_rate()
    clean_supplier = (supplier_name or "").strip() or None
    paid_dec = _parse_optional_cost(paid_amount) or Decimal("0.00")

    prod, stock_item = register_standalone_phone(
        model_name=model_name,
        imei1=imei1,
        memory=memory,
        color=color,
        imei2=imei2,
        serial_number=serial_number,
        condition=condition,
        battery_health=battery_health,
        cosmetic_condition=cosmetic_condition,
        unit_cost=unit_cost,
        cost_currency=currency,
        cost_exchange_rate=rate,
        acquisition_source=acquisition_source,
        notes=notes,
        supplier_name=clean_supplier,
        create_purchase_record=True,
        paid_amount=paid_dec,
    )

    with SessionLocal() as session, session.begin():
        row = session.get(IncomingQueueItem, int(queue_id))
        if row is not None:
            session.delete(row)

    return prod.id, stock_item.id
