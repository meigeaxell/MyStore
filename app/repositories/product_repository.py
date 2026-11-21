from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.stock_item import StockItem


def get_low_stock_products():
    """Возвращает активные товары, остаток которых достиг минимума."""
    with SessionLocal() as session:
        statement = (
            select(Product)
            .where(
                Product.is_active.is_(True),
                Product.min_stock_quantity > 0,
                Product.stock_quantity <= Product.min_stock_quantity,
            )
            .order_by(Product.stock_quantity.asc(), Product.name.asc())
        )
        return session.scalars(statement).all()


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
        category.name = clean_name


def deactivate_category(category_id: int) -> None:
    """Деактивирует выбранную категорию."""
    with SessionLocal() as session, session.begin():
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError("Kategoriýa tapylmady.")
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


def list_products_inventory() -> tuple[list[dict], dict[int, str]]:
    """Загружает единый список товаров со складскими остатками и разбивкой по IMEI (новые и Б/У)."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Product, Category.name)
            .join(Category, Product.category_id == Category.id)
            .where(Product.is_active.is_(True))
            .order_by(Product.name.asc())
        ).all()

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

        products = []
        now = datetime.now()
        for product, category_name in rows:
            p_items = by_product.get(product.id, [])
            in_stock_items = [i for i in p_items if i.status == "in_stock"]
            new_cnt = sum(1 for i in in_stock_items if i.condition == "new")
            used_cnt = sum(1 for i in in_stock_items if i.condition != "new")
            max_days = max(
                ((now - i.created_at).days for i in in_stock_items if i.created_at),
                default=0,
            )
            imei_blob = " ".join(
                f"{i.imei1} {i.imei2 or ''} {i.serial_number or ''}"
                for i in p_items
            ).lower()

            products.append({
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "category_id": product.category_id,
                "category": category_name,
                "brand": product.brand or "",
                "model": product.model or "",
                "specification": product.specification or "",
                "quantity": product.stock_quantity,
                "minimum": product.min_stock_quantity,
                "new_devices": new_cnt,
                "used_devices": used_cnt,
                "devices_in_stock": new_cnt + used_cnt,
                "total_devices": len(p_items),
                "max_days_in_stock": max(0, max_days),
                "imei_search_blob": imei_blob,
            })

        return products, cat_map


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


def save_product(
    product_id: int | None,
    name: str,
    category_id: int | None,
    brand: str | None = None,
    model: str | None = None,
    specification: str | None = None,
    stock_quantity: int = 0,
    min_stock_quantity: int = 0,
) -> Product:
    """Создаёт или обновляет товар в каталоге с проверкой синхронизации IMEI."""
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

    with SessionLocal() as session, session.begin():
        if product_id is None:
            last_product = session.scalar(
                select(Product).order_by(Product.id.desc()).limit(1)
            )
            next_number = (last_product.id + 1) if last_product else 1
            product = Product(
                category_id=category_id,
                sku=f"PRD_{next_number:06d}",
                name=clean_name,
                brand=clean_brand,
                model=clean_model,
                specification=clean_spec,
                stock_quantity=stock_quantity,
                min_stock_quantity=min_stock_quantity,
            )
            session.add(product)
            session.flush()
            session.refresh(product)
            return product

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
        product.name = clean_name
        product.brand = clean_brand
        product.model = clean_model
        product.specification = clean_spec
        product.stock_quantity = stock_quantity
        product.min_stock_quantity = min_stock_quantity
        session.flush()
        session.refresh(product)
        return product


def deactivate_product(product_id: int) -> None:
    """Деактивирует товар, если на складе нет остатков и активных IMEI."""
    with SessionLocal() as session, session.begin():
        product = session.get(Product, product_id)
        if product is None:
            raise ValueError("Haryt tapylmady.")

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
