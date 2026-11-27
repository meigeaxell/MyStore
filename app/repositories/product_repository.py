from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.stock_item import StockItem
from app.services.settings_service import SettingsService

SYSTEM_PHONE_NEW_CODE = "PHONE_NEW"
SYSTEM_PHONE_USED_CODE = "PHONE_USED"
SYSTEM_PHONE_CATEGORY_CODES = frozenset({SYSTEM_PHONE_NEW_CODE, SYSTEM_PHONE_USED_CODE})

SYSTEM_PHONE_CATEGORY_SPECS = (
    (SYSTEM_PHONE_NEW_CODE, "Telefon Täze", "Täze telefonlar (IMEI boýunça hemişelik kategoriýa)"),
    (SYSTEM_PHONE_USED_CODE, "Telefon B/U", "Ulanylan B/U telefonlar (IMEI boýunça hemişelik kategoriýa)"),
)


def is_system_category_code(code: str | None) -> bool:
    return (code or "").strip().upper() in SYSTEM_PHONE_CATEGORY_CODES


def ensure_system_phone_categories(session: Session | None = None) -> dict[str, int]:
    """Гарантирует наличие двух постоянных категорий 'Telefon Täze' и 'Telefon B/U'."""
    def _ensure(sess: Session) -> dict[str, int]:
        ids: dict[str, int] = {}
        for code, name, desc in SYSTEM_PHONE_CATEGORY_SPECS:
            cat = sess.scalar(select(Category).where(Category.code == code))
            if cat is None:
                cat = sess.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
            if cat is None:
                cat = Category(name=name, code=code, description=desc, is_active=True)
                sess.add(cat)
                sess.flush()
            else:
                if not cat.is_active:
                    cat.is_active = True
                if cat.code != code:
                    cat.code = code
                if cat.name != name:
                    cat.name = name
                sess.flush()
            key = "new" if code == SYSTEM_PHONE_NEW_CODE else "used"
            ids[key] = cat.id
        return ids

    if session is not None:
        return _ensure(session)
    with SessionLocal() as owned, owned.begin():
        return _ensure(owned)


def get_low_stock_products():
    """Возвращает активные товары, остаток которых достиг минимума (исключая одиночные телефоны)."""
    with SessionLocal() as session:
        statement = (
            select(Product)
            .where(
                Product.is_active.is_(True),
                Product.is_phone_unit.is_(False),
                Product.min_stock_quantity > 0,
                Product.stock_quantity <= Product.min_stock_quantity,
            )
            .order_by(Product.stock_quantity.asc(), Product.name.asc())
        )
        return session.scalars(statement).all()


def get_low_stock_products_detailed() -> list[dict]:
    """Возвращает подробный список товаров с низким остатком (с категорией, брендом и моделью)."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Product, Category.name)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(
                Product.is_active.is_(True),
                Product.is_phone_unit.is_(False),
                Product.min_stock_quantity > 0,
                Product.stock_quantity <= Product.min_stock_quantity,
            )
            .order_by(Product.stock_quantity.asc(), Product.name.asc())
        ).all()

        result: list[dict] = []
        for prod, cat_name in rows:
            qty = int(prod.stock_quantity or 0)
            min_qty = int(prod.min_stock_quantity or 0)
            result.append({
                "id": prod.id,
                "name": prod.name,
                "category": cat_name or "Kategoriýasyz",
                "brand": (prod.brand or "").strip(),
                "model": (prod.model or "").strip(),
                "stock_quantity": qty,
                "min_stock_quantity": min_qty,
                "deficit": max(0, min_qty - qty),
            })
        return result


def list_categories(active_only: bool = False) -> list[Category]:
    """Возвращает список категорий товаров."""
    with SessionLocal() as session:
        stmt = select(Category).order_by(Category.name.asc())
        if active_only:
            stmt = stmt.where(Category.is_active.is_(True))
        return list(session.scalars(stmt).all())


def create_category(name: str) -> Category:
    """Создаёт новую категорию с автоматическим кодом CAT_XXX."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Kategoriýanyň adyny giriziň.")

    with SessionLocal() as session, session.begin():
        existing = session.scalar(
            select(Category).where(func.lower(Category.name) == clean_name.lower())
        )
        if existing is not None:
            raise ValueError("Şeýle atly kategoriýa eýýäm bar.")

        codes = session.scalars(select(Category.code)).all()
        numbers = [
            int(c.replace("CAT_", ""))
            for c in codes
            if c.startswith("CAT_") and c.replace("CAT_", "").isdigit()
        ]
        next_num = max(numbers, default=0) + 1
        category = Category(name=clean_name, code=f"CAT_{next_num:03d}")
        session.add(category)
        session.flush()
        session.refresh(category)
        return category


def rename_category(category_id: int, new_name: str) -> None:
    """Переименовывает категорию с проверкой уникальности."""
    clean_name = (new_name or "").strip()
    if not clean_name:
        raise ValueError("Kategoriýanyň ady boş bolup bilmez.")

    with SessionLocal() as session, session.begin():
        duplicate = session.scalar(
            select(Category).where(
                func.lower(Category.name) == clean_name.lower(),
                Category.id != category_id,
            )
        )
        if duplicate is not None:
            raise ValueError("Şeýle atly kategoriýa eýýäm bar.")

        category = session.get(Category, category_id)
        if category is None:
            raise ValueError("Kategoriýa tapylmady.")
        if is_system_category_code(category.code):
            raise ValueError("Hemişelik ulgam kategoriýasynyň adyny üýtgedip bolmaýar.")
        category.name = clean_name


def deactivate_category(category_id: int) -> None:
    """Деактивирует выбранную категорию."""
    with SessionLocal() as session, session.begin():
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError("Kategoriýa tapylmady.")
        if is_system_category_code(category.code):
            raise ValueError("Hemişelik ulgam kategoriýasyny öçürip bolmaýar.")
        category.is_active = False


def count_category_products(category_id: int, active_only: bool = True) -> int:
    """Возвращает количество товаров, привязанных к категории."""
    with SessionLocal() as session:
        stmt = select(func.count(Product.id)).where(Product.category_id == category_id)
        if active_only:
            stmt = stmt.where(Product.is_active.is_(True))
        return int(session.scalar(stmt) or 0)


def find_duplicate_product(
    name: str,
    brand: str | None = None,
    model: str | None = None,
    specification: str | None = None,
    exclude_id: int | None = None,
) -> Product | None:
    """Ищет активный товар с совпадающими названием, брендом, моделью и характеристиками."""
    clean_name = (name or "").strip().lower()
    clean_brand = (brand or "").strip().lower()
    clean_model = (model or "").strip().lower()
    clean_spec = (specification or "").strip().lower()
    if not clean_name:
        return None

    with SessionLocal() as session:
        candidates = session.scalars(
            select(Product).where(
                Product.is_active.is_(True),
                func.lower(Product.name) == clean_name,
            )
        ).all()
        for prod in candidates:
            if exclude_id is not None and prod.id == exclude_id:
                continue
            if (
                (prod.brand or "").strip().lower() == clean_brand
                and (prod.model or "").strip().lower() == clean_model
                and (prod.specification or "").strip().lower() == clean_spec
            ):
                return prod
    return None


def list_products_inventory(include_archived: bool = False) -> tuple[list[dict], dict[int, str]]:
    """Загружает единый список товаров со складскими остатками и разбивкой по IMEI (новые и Б/У)."""
    with SessionLocal() as session:
        stmt = (
            select(Product, Category.name)
            .join(Category, Product.category_id == Category.id)
            .order_by(Product.is_active.desc(), Product.name.asc())
        )
        if not include_archived:
            stmt = stmt.where(Product.is_active.is_(True))
        rows = session.execute(stmt).all()

        stock_items = session.scalars(select(StockItem)).all()
        by_product: dict[int, list[StockItem]] = {}
        for st in stock_items:
            by_product.setdefault(st.product_id, []).append(st)

        categories = session.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.name.asc())
        ).all()
        cat_map = {c.id: c.name for c in categories}

        # Пакетно подгружаем последние закупочные цены (чтобы не делать N+1 запросов)
        latest_purchase_cost: dict[int, tuple[Decimal, str]] = {}
        pi_rows = session.execute(
            select(PurchaseItem.product_id, PurchaseItem.unit_cost, Purchase.currency)
            .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
            .where(Purchase.status == "active")
            .order_by(Purchase.purchase_date.desc(), PurchaseItem.id.desc())
        ).all()
        for pid, u_cost, p_curr in pi_rows:
            if pid not in latest_purchase_cost and u_cost is not None:
                latest_purchase_cost[pid] = (Decimal(str(u_cost)), str(p_curr or "USD").upper())

        # Пакетно читаем сохранённые базовые себестоимости из настроек
        import json as _json

        raw_default_costs = SettingsService.get("product_default_costs", "{}")
        try:
            default_costs_map = _json.loads(raw_default_costs) if raw_default_costs else {}
            if not isinstance(default_costs_map, dict):
                default_costs_map = {}
        except ValueError:
            default_costs_map = {}

        products = []
        now = datetime.now()
        for product, category_name in rows:
            p_items = by_product.get(product.id, [])
            in_stock_items = [i for i in p_items if i.status == "in_stock"]
            is_phone_unit = bool(getattr(product, "is_phone_unit", False))
            phone_sold = is_phone_unit and len(in_stock_items) == 0

            # Проданные самостоятельные телефоны исчезают со склада (оставаясь только в истории чеков)
            if phone_sold and not include_archived:
                continue

            new_cnt = sum(1 for i in in_stock_items if i.condition == "new")
            used_cnt = sum(1 for i in in_stock_items if i.condition != "new")
            max_days = max(
                ((now - i.created_at).days for i in in_stock_items if i.created_at),
                default=0,
            )
            imei_blob = " ".join(
                f"{i.imei1} {i.imei2 or ''} {i.serial_number or ''} {i.memory or ''} {i.color or ''} {i.battery_health or ''} {i.cosmetic_condition or ''}"
                for i in p_items
            ).lower()

            primary_st = in_stock_items[-1] if in_stock_items else (p_items[-1] if p_items else None)

            unit_cost = Decimal("0.00")
            cost_currency = ""
            # Приоритет: 1) последний in_stock IMEI с ценой, 2) последняя закупка, 3) базовая цена из карточки
            priced_imei = next((i for i in reversed(in_stock_items) if i.unit_cost is not None and Decimal(str(i.unit_cost)) > 0), None)
            if priced_imei is not None:
                unit_cost = Decimal(str(priced_imei.unit_cost))
                cost_currency = (priced_imei.cost_currency or "USD").strip().upper()
            elif product.id in latest_purchase_cost:
                unit_cost, cost_currency = latest_purchase_cost[product.id]
            else:
                dc_entry = default_costs_map.get(str(product.id))
                if isinstance(dc_entry, dict) and "unit_cost" in dc_entry:
                    import contextlib

                    with contextlib.suppress(InvalidOperation, ValueError, TypeError):
                        c_val = Decimal(str(dc_entry["unit_cost"]))
                        if c_val > 0:
                            unit_cost = c_val
                            cost_currency = str(dc_entry.get("currency", "USD")).strip().upper()

            cost_display = f"{unit_cost:,.2f} {cost_currency}" if unit_cost > 0 and cost_currency else "—"

            products.append({
                "id": product.id,
                "sku": product.sku,
                "barcode": product.barcode or "",
                "name": product.name,
                "category_id": product.category_id,
                "category": category_name,
                "brand": product.brand or "",
                "model": product.model or "",
                "specification": product.specification or "",
                "reference": product.specification or "",
                "unit_cost": unit_cost,
                "cost_currency": cost_currency,
                "cost_display": cost_display,
                "quantity": product.stock_quantity,
                "minimum": product.min_stock_quantity,
                "new_devices": new_cnt,
                "used_devices": used_cnt,
                "devices_in_stock": new_cnt + used_cnt,
                "total_devices": len(p_items),
                "max_days_in_stock": max(0, max_days),
                "imei_search_blob": imei_blob,
                "is_active": bool(product.is_active),
                "is_phone_unit": is_phone_unit,
                "phone_sold": phone_sold,
                "primary_stock_item_id": primary_st.id if primary_st else None,
                "imei1": primary_st.imei1 if primary_st else "",
                "imei2": (primary_st.imei2 or "") if primary_st else "",
                "serial_number": (primary_st.serial_number or "") if primary_st else "",
                "memory": (primary_st.memory or "") if primary_st else "",
                "color": (primary_st.color or "") if primary_st else "",
                "battery_health": (primary_st.battery_health or "") if primary_st else "",
                "cosmetic_condition": (primary_st.cosmetic_condition or "") if primary_st else "",
                "phone_condition": primary_st.condition if primary_st else "new",
            })

        return products, cat_map


def list_distinct_brands_and_models() -> tuple[list[str], list[str]]:
    """Возвращает списки уникальных брендов и моделей каталога для автоподсказок."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Product.brand, Product.model).where(Product.is_active.is_(True))
        ).all()
    brands = sorted({(b or "").strip() for b, _m in rows if (b or "").strip()}, key=str.lower)
    models = sorted({(m or "").strip() for _b, m in rows if (m or "").strip()}, key=str.lower)
    return brands, models


def find_products_by_barcode(code: str) -> list[Product]:
    """Ищет все активные товары по штрихкоду (Product.barcode), SKU или упоминанию кода в характеристиках."""
    clean = (code or "").strip()
    if not clean:
        return []
    with SessionLocal() as session:
        exact_bc = list(
            session.scalars(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    func.lower(Product.barcode) == clean.lower(),
                )
                .order_by(Product.name.asc())
            ).all()
        )
        if exact_bc:
            return exact_bc
        exact_sku = list(
            session.scalars(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    func.lower(Product.sku) == clean.lower(),
                )
                .order_by(Product.name.asc())
            ).all()
        )
        if exact_sku:
            return exact_sku
        return list(
            session.scalars(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    Product.specification.ilike(f"%{clean}%"),
                )
                .order_by(Product.name.asc())
            ).all()
        )


def find_product_by_barcode(code: str) -> Product | None:
    """Ищет первый активный товар по штрихкоду (Product.barcode), SKU или характеристикам."""
    matches = find_products_by_barcode(code)
    return matches[0] if matches else None


def get_product_with_devices(product_id: int) -> tuple[Product | None, int, list[StockItem]]:
    """Возвращает товар, количество активных IMEI на складе и список всех его StockItem."""
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if product is None:
            return None, 0, []
        items = list(
            session.scalars(
                select(StockItem)
                .where(StockItem.product_id == product_id)
                .order_by(StockItem.id.desc())
            ).all()
        )
        in_stock_cnt = sum(1 for i in items if i.status == "in_stock")
        return product, in_stock_cnt, items


def _resolve_existing_product_cost(session: Session, product_id: int) -> tuple[Decimal, str]:
    """Возвращает базовую себестоимость товара (amount, currency) из настроек или последней закупки."""
    saved = SettingsService.get_product_default_cost(product_id)
    if saved is not None:
        return Decimal(str(saved[0])).quantize(Decimal("0.01")), str(saved[1]).strip().upper()
    row = session.execute(
        select(PurchaseItem.unit_cost, Purchase.currency)
        .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
        .where(
            PurchaseItem.product_id == product_id,
            Purchase.status == "active",
        )
        .order_by(Purchase.purchase_date.desc(), PurchaseItem.id.desc())
        .limit(1)
    ).first()
    if row and row[0] is not None:
        return Decimal(str(row[0])).quantize(Decimal("0.01")), str(row[1] or "USD").strip().upper()
    return Decimal("0.00"), "USD"


def save_product(
    product_id: int | None,
    name: str,
    category_id: int | None,
    brand: str | None = None,
    model: str | None = None,
    specification: str | None = None,
    stock_quantity: int = 0,
    min_stock_quantity: int = 0,
    barcode: str | None = None,
    default_cost: Decimal | float | str | None = None,
    default_cost_currency: str | None = None,
    merge_duplicates: bool = True,
) -> Product:
    """Создаёт или обновляет товар в каталоге.

    Штрихкоды могут быть общими для нескольких товаров (например, разные цвета одной модели).
    При создании нового количественного товара с совпадающими названием, моделью, категорией,
    характеристиками и себестоимостью количество суммируется с существующим товаром.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Harydyň adyny giriziň.")
    if category_id is None:
        raise ValueError("Haryt kategoriýasyny saýlaň.")
    if stock_quantity < 0:
        raise ValueError("Skladdaky sany otrisatel bolup bilmez.")
    if min_stock_quantity < 0:
        raise ValueError("Iň az galyndy otrisatel bolup bilmez.")

    clean_brand = (brand or "").strip() or None
    clean_model = (model or "").strip() or None
    clean_spec = (specification or "").strip() or None
    clean_barcode = (barcode or "").strip() or None

    cost_dec: Decimal | None = None
    cost_curr: str = (default_cost_currency or "USD").strip().upper()
    if default_cost is not None:
        try:
            cost_dec = Decimal(str(default_cost)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            cost_dec = Decimal("0.00")

    created_product: Product | None = None
    with SessionLocal() as session, session.begin():
        if product_id is None:
            if merge_duplicates:
                candidates = session.scalars(
                    select(Product).where(
                        Product.is_active.is_(True),
                        Product.is_phone_unit.is_(False),
                        Product.category_id == category_id,
                        func.lower(Product.name) == clean_name.lower(),
                    )
                ).all()
                target_model = (clean_model or "").lower()
                target_spec = (clean_spec or "").lower()
                for existing in candidates:
                    if (existing.model or "").strip().lower() != target_model:
                        continue
                    if (existing.specification or "").strip().lower() != target_spec:
                        continue
                    ex_cost, ex_curr = _resolve_existing_product_cost(session, existing.id)
                    if cost_dec is not None:
                        if cost_dec == Decimal("0.00") and ex_cost == Decimal("0.00"):
                            cost_matches = True
                        else:
                            cost_matches = (ex_cost == cost_dec and ex_curr == cost_curr)
                    else:
                        cost_matches = ex_cost == Decimal("0.00")
                    if cost_matches:
                        existing.stock_quantity = int(existing.stock_quantity or 0) + int(stock_quantity)
                        if clean_barcode and not existing.barcode:
                            existing.barcode = clean_barcode
                        if clean_brand and not existing.brand:
                            existing.brand = clean_brand
                        if min_stock_quantity > 0 and existing.min_stock_quantity == 0:
                            existing.min_stock_quantity = min_stock_quantity
                        session.flush()
                        session.refresh(existing)
                        existing._merged_duplicate = True
                        return existing

            last_product = session.scalar(
                select(Product).order_by(Product.id.desc()).limit(1)
            )
            next_number = (last_product.id + 1) if last_product else 1
            product = Product(
                category_id=category_id,
                sku=f"PRD_{next_number:06d}",
                barcode=clean_barcode,
                name=clean_name,
                brand=clean_brand,
                model=clean_model,
                specification=clean_spec,
                stock_quantity=stock_quantity,
                min_stock_quantity=min_stock_quantity,
            )
            session.add(product)
            session.flush()
            from app.services.accessory_matcher import sync_product_glossary
            from app.services.search_engine import sync_product_fts

            sync_product_glossary(session, product)
            sync_product_fts(session, product)
            session.refresh(product)
            product._merged_duplicate = False
            created_product = product

        else:
            product = session.get(Product, product_id)
            if product is None:
                raise ValueError("Haryt tapylmady.")

            in_stock_imeis = session.scalars(
                select(StockItem).where(
                    StockItem.product_id == product_id,
                    StockItem.status == "in_stock",
                )
            ).all()
            imei_cnt = len(in_stock_imeis)
            if imei_cnt > 0 and stock_quantity < imei_cnt:
                raise ValueError(
                    f"Bu harydyň skladynda IMEI boýunça {imei_cnt} enjam hasaba alnan.\n"
                    f"Skladdaky jemi galyndy {imei_cnt} sanydan az bolup bilmez."
                )

            product.category_id = category_id
            product.barcode = clean_barcode
            product.name = clean_name
            product.brand = clean_brand
            product.model = clean_model
            product.specification = clean_spec
            product.stock_quantity = stock_quantity
            product.min_stock_quantity = min_stock_quantity
            session.flush()
            from app.services.accessory_matcher import sync_product_glossary
            from app.services.search_engine import sync_product_fts

            sync_product_glossary(session, product)
            sync_product_fts(session, product)
            session.refresh(product)
            return product

    if created_product is not None and cost_dec is not None and cost_dec > Decimal("0.00"):
        SettingsService.set_product_default_cost(created_product.id, cost_dec, cost_curr)
    return created_product


def deactivate_product(product_id: int, force: bool = True) -> None:
    """Переводит товар в архив (is_active=False). При force=True разрешено даже при наличии остатков."""
    with SessionLocal() as session, session.begin():
        product = session.get(Product, product_id)
        if product is None:
            raise ValueError("Haryt tapylmady.")

        if not force:
            active_imei = session.scalars(
                select(StockItem).where(
                    StockItem.product_id == product_id,
                    StockItem.status == "in_stock",
                )
            ).first()
            if product.stock_quantity > 0 or active_imei is not None:
                raise ValueError(
                    "Harydyň skladynda entek galyndy bar.\n"
                    "Ilki olary satmaly ýa-da hasapdan çykarmaly."
                )
        product.is_active = False


def restore_product(product_id: int) -> None:
    """Восстанавливает архивный товар обратно в активный каталог."""
    with SessionLocal() as session, session.begin():
        product = session.get(Product, product_id)
        if product is None:
            raise ValueError("Haryt tapylmady.")
        product.is_active = True


def find_stock_item_by_imei(imei: str) -> dict | None:
    """Ищет устройство по IMEI 1 или IMEI 2 и возвращает полную информацию."""
    clean_imei = (imei or "").strip()
    if not clean_imei:
        return None

    with SessionLocal() as session:
        row = session.execute(
            select(StockItem, Product)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                (StockItem.imei1 == clean_imei) | (StockItem.imei2 == clean_imei)
            )
        ).first()
        if row is None:
            return None

        st, prod = row
        return {
            "id": st.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "sku": prod.sku,
            "imei1": st.imei1,
            "imei2": st.imei2,
            "serial_number": st.serial_number,
            "condition": st.condition,
            "status": st.status,
            "unit_cost": st.unit_cost,
            "cost_currency": st.cost_currency,
            "cost_exchange_rate": st.cost_exchange_rate,
            "acquisition_source": st.acquisition_source,
            "notes": st.notes,
            "created_at": st.created_at,
        }


def register_stock_item(
    product_id: int,
    imei1: str,
    imei2: str | None = None,
    serial_number: str | None = None,
    condition: str = "new",
    unit_cost: Decimal | float | str | None = Decimal("0.00"),
    cost_currency: str = "USD",
    cost_exchange_rate: Decimal | float | str = Decimal("19.5000"),
    acquisition_source: str | None = None,
    notes: str | None = None,
    increment_stock: bool = True,
) -> StockItem:
    """Регистрирует новое или Б/У устройство с IMEI на складе и синхронизирует остаток товара."""
    clean_imei1 = (imei1 or "").strip()
    clean_imei2 = (imei2 or "").strip() or None
    clean_sn = (serial_number or "").strip() or None
    clean_cond = "used" if str(condition).lower() in ("used", "b/u", "б/у") else "new"
    clean_source = (acquisition_source or "").strip() or None
    clean_notes = (notes or "").strip() or None

    if not clean_imei1:
        raise ValueError("Hökmany IMEI 1 giriziň.")
    if clean_imei2 and clean_imei1 == clean_imei2:
        raise ValueError("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")

    cost_dec = Decimal(str(unit_cost)) if unit_cost is not None else Decimal("0.00")
    if cost_dec < 0:
        raise ValueError("Öz bahasy otrisatel bolup bilmez.")
    rate_dec = Decimal(str(cost_exchange_rate)) if cost_exchange_rate else Decimal("1.0000")
    if rate_dec <= 0:
        raise ValueError("Kurs noldan uly bolmaly.")

    with SessionLocal() as session, session.begin():
        product = session.get(Product, product_id)
        if product is None or not product.is_active:
            raise ValueError("Saýlanan haryt tapylmady ýa-da öçürilen.")

        existing = session.execute(
            select(StockItem, Product.name)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                (StockItem.imei1 == clean_imei1)
                | (StockItem.imei2 == clean_imei1)
                | (
                    (StockItem.imei1 == clean_imei2) | (StockItem.imei2 == clean_imei2)
                    if clean_imei2
                    else False
                )
            )
        ).first()
        if existing is not None:
            ex_item, ex_prod_name = existing
            status_lbl = "Skladda bar" if ex_item.status == "in_stock" else "Satyldy"
            raise ValueError(
                f"IMEI {clean_imei1} enjam eýýäm bazada hasaba alnan:\n"
                f"Model: {ex_prod_name} (ID #{ex_item.id}, status: {status_lbl})."
            )

        in_stock_imeis = session.scalars(
            select(StockItem).where(
                StockItem.product_id == product_id,
                StockItem.status == "in_stock",
            )
        ).all()

        stock_item = StockItem(
            product_id=product_id,
            imei1=clean_imei1,
            imei2=clean_imei2,
            serial_number=clean_sn,
            condition=clean_cond,
            status="in_stock",
            unit_cost=cost_dec,
            cost_currency=(cost_currency or "USD").strip().upper(),
            cost_exchange_rate=rate_dec,
            acquisition_source=clean_source,
            notes=clean_notes,
            created_at=datetime.now(),
        )
        session.add(stock_item)

        if increment_stock:
            product.stock_quantity = max(
                product.stock_quantity + 1,
                len(in_stock_imeis) + 1,
            )
        else:
            product.stock_quantity = max(
                product.stock_quantity,
                len(in_stock_imeis) + 1,
            )

        session.flush()
        session.refresh(stock_item)
        return stock_item


def update_stock_item(
    stock_item_id: int,
    product_id: int,
    imei1: str,
    imei2: str | None = None,
    serial_number: str | None = None,
    condition: str = "new",
    status: str = "in_stock",
    unit_cost: Decimal | float | str | None = Decimal("0.00"),
    cost_currency: str = "USD",
    cost_exchange_rate: Decimal | float | str = Decimal("19.5000"),
    acquisition_source: str | None = None,
    notes: str | None = None,
) -> StockItem:
    """Полное редактирование IMEI-устройства (StockItem) с пересчётом складских остатков."""
    clean_imei1 = (imei1 or "").strip()
    clean_imei2 = (imei2 or "").strip() or None
    clean_sn = (serial_number or "").strip() or None
    clean_cond = "used" if str(condition).lower() in ("used", "b/u", "б/у") else "new"
    clean_status = (status or "in_stock").strip().lower()
    if clean_status not in ("in_stock", "sold", "written_off"):
        raise ValueError("Rugsat berlen statuslar: in_stock, sold, written_off.")
    clean_source = (acquisition_source or "").strip() or None
    clean_notes = (notes or "").strip() or None

    if not clean_imei1:
        raise ValueError("Hökmany IMEI 1 giriziň.")
    if clean_imei2 and clean_imei1 == clean_imei2:
        raise ValueError("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")

    cost_dec = Decimal(str(unit_cost)) if unit_cost is not None else Decimal("0.00")
    if cost_dec < 0:
        raise ValueError("Öz bahasy otrisatel bolup bilmez.")
    rate_dec = Decimal(str(cost_exchange_rate)) if cost_exchange_rate else Decimal("1.0000")
    if rate_dec <= 0:
        raise ValueError("Kurs noldan uly bolmaly.")

    with SessionLocal() as session, session.begin():
        stock_item = session.get(StockItem, int(stock_item_id))
        if stock_item is None:
            raise ValueError("Enjam (StockItem) tapylmady.")

        target_product = session.get(Product, int(product_id))
        if target_product is None:
            raise ValueError("Saýlanan haryt tapylmady.")

        existing = session.execute(
            select(StockItem, Product.name)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                StockItem.id != stock_item.id,
                (StockItem.imei1 == clean_imei1)
                | (StockItem.imei2 == clean_imei1)
                | (
                    (StockItem.imei1 == clean_imei2) | (StockItem.imei2 == clean_imei2)
                    if clean_imei2
                    else False
                ),
            )
        ).first()
        if existing is not None:
            ex_item, ex_prod_name = existing
            raise ValueError(
                f"IMEI {clean_imei1} (ýa-da IMEI 2) eýýäm başga enjamda bar: "
                f"{ex_prod_name} (ID #{ex_item.id})."
            )

        old_product_id = stock_item.product_id
        old_in_stock = stock_item.status == "in_stock"
        new_in_stock = clean_status == "in_stock"

        stock_item.product_id = target_product.id
        stock_item.imei1 = clean_imei1
        stock_item.imei2 = clean_imei2
        stock_item.serial_number = clean_sn
        stock_item.condition = clean_cond
        stock_item.status = clean_status
        stock_item.unit_cost = cost_dec
        stock_item.cost_currency = (cost_currency or "USD").strip().upper()
        stock_item.cost_exchange_rate = rate_dec
        stock_item.acquisition_source = clean_source
        stock_item.notes = clean_notes
        session.flush()

        # Синхронизируем остатки старого и нового товара
        if old_product_id != target_product.id:
            old_prod = session.get(Product, old_product_id)
            if old_prod is not None and old_in_stock:
                old_prod.stock_quantity = max(0, old_prod.stock_quantity - 1)
            if new_in_stock:
                in_stock_cnt = len(
                    session.scalars(
                        select(StockItem).where(
                            StockItem.product_id == target_product.id,
                            StockItem.status == "in_stock",
                        )
                    ).all()
                )
                target_product.stock_quantity = max(target_product.stock_quantity + 1, in_stock_cnt)
        else:
            if old_in_stock and not new_in_stock:
                target_product.stock_quantity = max(0, target_product.stock_quantity - 1)
            elif not old_in_stock and new_in_stock:
                in_stock_cnt = len(
                    session.scalars(
                        select(StockItem).where(
                            StockItem.product_id == target_product.id,
                            StockItem.status == "in_stock",
                        )
                    ).all()
                )
                target_product.stock_quantity = max(target_product.stock_quantity + 1, in_stock_cnt)

        session.flush()
        session.refresh(stock_item)
        return stock_item


def delete_stock_item(stock_item_id: int) -> None:
    """Удаляет StockItem, если на него нет ссылок в продажах и обменах, и обновляет остаток."""
    from app.models.device_exchange import DeviceExchange
    from app.models.sale_item import SaleItem

    with SessionLocal() as session, session.begin():
        stock_item = session.get(StockItem, int(stock_item_id))
        if stock_item is None:
            raise ValueError("Enjam tapylmady.")

        used_in_sale = session.scalar(
            select(SaleItem.id).where(SaleItem.stock_item_id == stock_item.id).limit(1)
        )
        if used_in_sale is not None:
            raise ValueError(
                "Bu enjam satyş çekinde görkezilen. Ony pozup bolmaýar — statusyny üýtgediň ýa-da çeki ýatyryň."
            )
        used_in_exchange = session.scalar(
            select(DeviceExchange.id)
            .where(
                (DeviceExchange.old_stock_item_id == stock_item.id)
                | (DeviceExchange.new_stock_item_id == stock_item.id)
            )
            .limit(1)
        )
        if used_in_exchange is not None:
            raise ValueError("Bu enjam Trade-in çalyşygynda görkezilen we pozup bolmaýar.")

        prod = session.get(Product, stock_item.product_id)
        was_in_stock = stock_item.status == "in_stock"
        session.delete(stock_item)
        session.flush()

        if prod is not None:
            if was_in_stock:
                prod.stock_quantity = max(0, prod.stock_quantity - 1)
            if getattr(prod, "is_phone_unit", False):
                remaining_imeis = session.scalar(
                    select(func.count(StockItem.id)).where(StockItem.product_id == prod.id)
                )
                if not remaining_imeis:
                    prod.stock_quantity = 0
                    prod.is_active = False
            session.flush()


def _format_phone_spec(
    memory: str | None = None,
    color: str | None = None,
    battery_health: str | None = None,
    cosmetic_condition: str | None = None,
) -> str | None:
    parts: list[str] = []
    if memory and memory.strip():
        parts.append(memory.strip())
    if color and color.strip():
        parts.append(color.strip())
    if battery_health and battery_health.strip():
        bh = battery_health.strip()
        if not bh.lower().startswith("bat"):
            bh = f"Bat: {bh}"
        parts.append(bh)
    if cosmetic_condition and cosmetic_condition.strip():
        parts.append(cosmetic_condition.strip())
    return " • ".join(parts) if parts else None


def list_distinct_phone_models() -> list[str]:
    """Возвращает уникальные названия моделей телефонов для автодополнения в окне IMEI."""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Product.name)
            .where(
                Product.is_phone_unit.is_(True)
                | Product.id.in_(select(StockItem.product_id))
            )
            .distinct()
        ).all()
    return sorted({(n or "").strip() for n in rows if (n or "").strip()}, key=str.lower)


def register_standalone_phone(
    model_name: str,
    imei1: str,
    memory: str | None = None,
    color: str | None = None,
    imei2: str | None = None,
    serial_number: str | None = None,
    condition: str = "new",
    battery_health: str | None = None,
    cosmetic_condition: str | None = None,
    unit_cost: Decimal | float | str | None = Decimal("0.00"),
    cost_currency: str = "USD",
    cost_exchange_rate: Decimal | float | str = Decimal("19.5000"),
    acquisition_source: str | None = None,
    notes: str | None = None,
    supplier_name: str | None = None,
    create_purchase_record: bool = False,
    paid_amount: Decimal | float | str | None = None,
) -> tuple[Product, StockItem]:
    """Регистрирует самостоятельный телефон по IMEI в постоянной категории Telefon Täze / Telefon B/U."""
    from app.services.purchase_service import create_purchase

    clean_model = (model_name or "").strip()
    clean_memory = (memory or "").strip() or None
    clean_color = (color or "").strip() or None
    clean_imei1 = (imei1 or "").strip()
    clean_imei2 = (imei2 or "").strip() or None
    clean_sn = (serial_number or "").strip() or None
    clean_cond = "used" if str(condition).lower() in ("used", "b/u", "б/у") else "new"
    clean_battery = (battery_health or "").strip() or None if clean_cond == "used" else None
    clean_cosmetic = (cosmetic_condition or "").strip() or None if clean_cond == "used" else None
    clean_source = (acquisition_source or "").strip() or None
    clean_notes = (notes or "").strip() or None
    clean_supplier = (supplier_name or "").strip() or None

    if not clean_model:
        raise ValueError("Telefon modeliniň adyny giriziň.")
    if not clean_imei1:
        raise ValueError("Hökmany IMEI 1 giriziň.")
    if clean_imei2 and clean_imei1 == clean_imei2:
        raise ValueError("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")

    cost_dec = Decimal(str(unit_cost)) if unit_cost is not None and str(unit_cost).strip() != "" else Decimal("0.00")
    if cost_dec < 0:
        raise ValueError("Öz bahasy otrisatel bolup bilmez.")
    curr = (cost_currency or "USD").strip().upper()
    if curr not in ("USD", "TMT"):
        curr = "USD"
    rate_dec = Decimal(str(cost_exchange_rate)) if cost_exchange_rate else Decimal("19.5000")
    if rate_dec <= 0:
        raise ValueError("Kurs noldan uly bolmaly.")

    spec_summary = _format_phone_spec(
        memory=clean_memory,
        color=clean_color,
        battery_health=clean_battery,
        cosmetic_condition=clean_cosmetic,
    )

    with SessionLocal() as session, session.begin():
        existing = session.execute(
            select(StockItem, Product.name)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                (StockItem.imei1 == clean_imei1)
                | (StockItem.imei2 == clean_imei1)
                | (
                    (StockItem.imei1 == clean_imei2) | (StockItem.imei2 == clean_imei2)
                    if clean_imei2
                    else False
                )
            )
        ).first()
        if existing is not None:
            ex_item, ex_prod_name = existing
            status_lbl = "Skladda bar" if ex_item.status == "in_stock" else "Satyldy"
            raise ValueError(
                f"IMEI {clean_imei1} enjam eýýäm bazada hasaba alnan:\n"
                f"Model: {ex_prod_name} (ID #{ex_item.id}, status: {status_lbl})."
            )

        cat_ids = ensure_system_phone_categories(session)
        cat_id = cat_ids["used"] if clean_cond == "used" else cat_ids["new"]

        sku = f"PHN-{uuid4().hex[:8].upper()}"
        product = Product(
            category_id=cat_id,
            sku=sku,
            barcode=None,
            name=clean_model,
            brand=None,
            model=clean_memory,
            specification=spec_summary,
            stock_quantity=0 if create_purchase_record else 1,
            min_stock_quantity=0,
            is_active=True,
            is_phone_unit=True,
        )
        session.add(product)
        session.flush()
        product_id = product.id

        if not create_purchase_record:
            stock_item = StockItem(
                product_id=product_id,
                imei1=clean_imei1,
                imei2=clean_imei2,
                serial_number=clean_sn,
                condition=clean_cond,
                status="in_stock",
                unit_cost=cost_dec,
                cost_currency=curr,
                cost_exchange_rate=rate_dec,
                acquisition_source=clean_source or ("direct_buyout" if clean_cond == "used" else "initial_stock"),
                memory=clean_memory,
                color=clean_color,
                battery_health=clean_battery,
                cosmetic_condition=clean_cosmetic,
                notes=clean_notes,
                created_at=datetime.now(),
            )
            session.add(stock_item)
            session.flush()
            session.refresh(product)
            session.refresh(stock_item)
            return product, stock_item

    # Если оформляется как закупка (например, из очереди приёмки или закупки)
    payments = []
    if paid_amount is not None and Decimal(str(paid_amount)) > 0:
        payments.append({
            "currency": curr,
            "amount": Decimal(str(paid_amount)),
            "exchange_rate": rate_dec,
        })

    create_purchase(
        items=[
            {
                "product_id": product_id,
                "quantity": 1,
                "unit_cost": cost_dec,
                "imeis": [
                    {
                        "imei1": clean_imei1,
                        "imei2": clean_imei2,
                        "serial_number": clean_sn,
                        "condition": clean_cond,
                    }
                ],
            }
        ],
        currency=curr,
        exchange_rate=rate_dec,
        payments=payments,
        note=clean_notes or f"Telefon kabul ediş: {clean_model}",
        supplier_name=clean_supplier,
    )

    with SessionLocal() as session, session.begin():
        prod = session.get(Product, product_id)
        st = session.scalar(
            select(StockItem).where(
                StockItem.product_id == product_id,
                StockItem.imei1 == clean_imei1,
            )
        )
        if st is not None:
            st.memory = clean_memory
            st.color = clean_color
            st.battery_health = clean_battery
            st.cosmetic_condition = clean_cosmetic
            st.acquisition_source = clean_source or ("supplier" if clean_supplier else "initial_stock")
            st.notes = clean_notes
            session.flush()
            session.refresh(st)
        if prod is not None:
            session.refresh(prod)
        return prod, st


def update_standalone_phone(
    stock_item_id: int,
    model_name: str,
    imei1: str,
    memory: str | None = None,
    color: str | None = None,
    imei2: str | None = None,
    serial_number: str | None = None,
    condition: str = "new",
    status: str = "in_stock",
    battery_health: str | None = None,
    cosmetic_condition: str | None = None,
    unit_cost: Decimal | float | str | None = Decimal("0.00"),
    cost_currency: str = "USD",
    cost_exchange_rate: Decimal | float | str = Decimal("19.5000"),
    acquisition_source: str | None = None,
    notes: str | None = None,
) -> StockItem:
    """Обновляет самостоятельный телефон (StockItem + его 1-к-1 Product и авто-категорию)."""
    clean_model = (model_name or "").strip()
    clean_memory = (memory or "").strip() or None
    clean_color = (color or "").strip() or None
    clean_imei1 = (imei1 or "").strip()
    clean_imei2 = (imei2 or "").strip() or None
    clean_sn = (serial_number or "").strip() or None
    clean_cond = "used" if str(condition).lower() in ("used", "b/u", "б/у") else "new"
    clean_status = (status or "in_stock").strip().lower()
    if clean_status not in ("in_stock", "sold", "written_off"):
        raise ValueError("Rugsat berlen statuslar: in_stock, sold, written_off.")
    clean_battery = (battery_health or "").strip() or None if clean_cond == "used" else None
    clean_cosmetic = (cosmetic_condition or "").strip() or None if clean_cond == "used" else None
    clean_source = (acquisition_source or "").strip() or None
    clean_notes = (notes or "").strip() or None

    if not clean_model:
        raise ValueError("Telefon modeliniň adyny giriziň.")
    if not clean_imei1:
        raise ValueError("Hökmany IMEI 1 giriziň.")
    if clean_imei2 and clean_imei1 == clean_imei2:
        raise ValueError("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez.")

    cost_dec = Decimal(str(unit_cost)) if unit_cost is not None else Decimal("0.00")
    if cost_dec < 0:
        raise ValueError("Öz bahasy otrisatel bolup bilmez.")
    rate_dec = Decimal(str(cost_exchange_rate)) if cost_exchange_rate else Decimal("19.5000")
    if rate_dec <= 0:
        raise ValueError("Kurs noldan uly bolmaly.")

    spec_summary = _format_phone_spec(
        memory=clean_memory,
        color=clean_color,
        battery_health=clean_battery,
        cosmetic_condition=clean_cosmetic,
    )

    with SessionLocal() as session, session.begin():
        stock_item = session.get(StockItem, int(stock_item_id))
        if stock_item is None:
            raise ValueError("Enjam (StockItem) tapylmady.")

        existing = session.execute(
            select(StockItem, Product.name)
            .join(Product, StockItem.product_id == Product.id)
            .where(
                StockItem.id != stock_item.id,
                (StockItem.imei1 == clean_imei1)
                | (StockItem.imei2 == clean_imei1)
                | (
                    (StockItem.imei1 == clean_imei2) | (StockItem.imei2 == clean_imei2)
                    if clean_imei2
                    else False
                ),
            )
        ).first()
        if existing is not None:
            ex_item, ex_prod_name = existing
            raise ValueError(
                f"IMEI {clean_imei1} (ýa-da IMEI 2) eýýäm başga enjamda bar: "
                f"{ex_prod_name} (ID #{ex_item.id})."
            )

        prod = session.get(Product, stock_item.product_id)
        stock_item.imei1 = clean_imei1
        stock_item.imei2 = clean_imei2
        stock_item.serial_number = clean_sn
        stock_item.condition = clean_cond
        stock_item.status = clean_status
        stock_item.memory = clean_memory
        stock_item.color = clean_color
        stock_item.battery_health = clean_battery
        stock_item.cosmetic_condition = clean_cosmetic
        stock_item.unit_cost = cost_dec
        stock_item.cost_currency = (cost_currency or "USD").strip().upper()
        stock_item.cost_exchange_rate = rate_dec
        stock_item.acquisition_source = clean_source
        stock_item.notes = clean_notes

        if prod is not None and getattr(prod, "is_phone_unit", False):
            cat_ids = ensure_system_phone_categories(session)
            prod.category_id = cat_ids["used"] if clean_cond == "used" else cat_ids["new"]
            prod.name = clean_model
            prod.model = clean_memory
            prod.specification = spec_summary
            prod.stock_quantity = 1 if clean_status == "in_stock" else 0
        elif prod is not None:
            in_stock_cnt = len(
                session.scalars(
                    select(StockItem).where(
                        StockItem.product_id == prod.id,
                        StockItem.status == "in_stock",
                    )
                ).all()
            )
            prod.stock_quantity = max(in_stock_cnt, 0)

        session.flush()
        session.refresh(stock_item)
        return stock_item
