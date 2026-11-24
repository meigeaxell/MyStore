import json
import secrets
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKUP_DIR
from app.database.engine import SessionLocal
from app.models.settings import Setting

DEFAULT_SETTINGS: dict[str, str] = {
    "store_name": "MobileStore",
    "store_phone": "+993 65 00-00-00",
    "store_address": "Aşgabat, Türkmenistan",
    "default_currency": "TMT",
    "default_exchange_rate": "19.5000",
    "date_format": "%d.%m.%Y %H:%M",
    "receipt_footer": "Satyn alanyňyz üçin sag boluň! Enjam çalyşygy dükanyň düzgünlerine görä geçirilýär.",
    "default_min_stock_quantity": "2",
    "backup_directory": str(BACKUP_DIR),
    "auto_backup_enabled": "1",
    "auto_backup_frequency": "daily",  # daily, on_startup, manual
    "backup_retention_count": "15",
    "last_backup_at": "",
    "mobile_server_enabled": "1",
    "mobile_server_port": "8765",
    "mobile_server_token": "",
    "stock_group_mode": "name",  # name | brand | category | none
    "product_remember_fields": json.dumps({
        "category": True,
        "brand": True,
        "model": True,
        "reference": True,
        "cost": True,
        "min_stock": True,
        "name": False,
        "barcode": False,
    }),
    "last_product_draft": "{}",
}


class SettingsService:
    """Централизованный сервис настроек приложения (Фаза VI)."""

    @staticmethod
    def get_all(session: Session | None = None) -> dict[str, str]:
        """Возвращает словарь всех настроек с подстановкой значений по умолчанию."""
        result = dict(DEFAULT_SETTINGS)
        if session is not None:
            rows = session.scalars(select(Setting)).all()
            for r in rows:
                if r.value is not None:
                    result[r.key] = r.value
            return result

        with SessionLocal() as db:
            rows = db.scalars(select(Setting)).all()
            for r in rows:
                if r.value is not None:
                    result[r.key] = r.value
        return result

    @staticmethod
    def get(key: str, default: str | None = None) -> str:
        """Возвращает строковое значение настройки по ключу."""
        fallback = default if default is not None else DEFAULT_SETTINGS.get(key, "")
        with SessionLocal() as session:
            row = session.scalar(select(Setting).where(Setting.key == key))
            if row is not None and row.value is not None:
                return row.value
        return fallback

    @staticmethod
    def get_default_exchange_rate() -> Decimal:
        """Возвращает настроенный курс по умолчанию (1 USD = X TMT)."""
        raw = SettingsService.get("default_exchange_rate", "19.5000")
        try:
            rate = Decimal(str(raw))
            if rate > 0:
                return rate
        except (InvalidOperation, ValueError):
            pass
        return Decimal("19.5000")

    @staticmethod
    def get_default_min_stock() -> int:
        """Возвращает порог минимального остатка по умолчанию."""
        raw = SettingsService.get("default_min_stock_quantity", "2")
        try:
            val = int(raw)
            return max(0, val)
        except ValueError:
            return 2

    @staticmethod
    def set_many(values: dict[str, str]) -> None:
        """Атомарно сохраняет набор настроек в базу данных."""
        with SessionLocal() as session, session.begin():
            existing = {
                row.key: row
                for row in session.scalars(
                    select(Setting).where(Setting.key.in_(list(values.keys())))
                ).all()
            }
            for k, v in values.items():
                str_val = str(v).strip()
                if k in existing:
                    existing[k].value = str_val
                else:
                    session.add(Setting(key=k, value=str_val))

    @staticmethod
    def get_product_default_cost(product_id: int) -> tuple[Decimal, str] | None:
        """Возвращает базовую себестоимость товара (unit_cost, currency), если она была задана в карточке или кассе."""
        raw = SettingsService.get("product_default_costs", "{}")
        try:
            data = json.loads(raw) if raw else {}
            entry = data.get(str(product_id))
            if isinstance(entry, dict) and "unit_cost" in entry:
                cost = Decimal(str(entry["unit_cost"]))
                curr = str(entry.get("currency", "USD")).strip().upper()
                if cost > 0 and curr in ("USD", "TMT"):
                    return cost, curr
        except ( ValueError, TypeError, InvalidOperation):
            pass
        return None

    @staticmethod
    def set_product_default_cost(product_id: int, unit_cost: Decimal | float | str, currency: str = "USD") -> None:
        """Сохраняет базовую себестоимость товара без необходимости создавать документ закупки."""
        raw = SettingsService.get("product_default_costs", "{}")
        try:
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}

        cost_dec = Decimal(str(unit_cost))
        data[str(product_id)] = {
            "unit_cost": f"{cost_dec:.2f}",
            "currency": (currency or "USD").strip().upper(),
        }
        SettingsService.set_many({"product_default_costs": json.dumps(data, ensure_ascii=False)})

    @staticmethod
    def get_held_carts() -> list[dict]:
        """Возвращает список отложенных чеков (черновиков корзин кассы)."""
        raw = SettingsService.get("held_sales_carts", "[]")
        try:
            carts = json.loads(raw) if raw else []
            return carts if isinstance(carts, list) else []
        except ValueError:
            return []

    @staticmethod
    def save_held_carts(carts: list[dict]) -> None:
        """Сохраняет список отложенных чеков."""
        SettingsService.set_many({"held_sales_carts": json.dumps(carts, ensure_ascii=False)})

    @staticmethod
    def get_or_create_mobile_token() -> str:
        """Возвращает 6-значный PIN/токен подключения смартфонов (создаёт при первом запуске)."""
        token = SettingsService.get("mobile_server_token", "").strip()
        if not token:
            token = f"{secrets.randbelow(900000) + 100000}"
            SettingsService.set_many({"mobile_server_token": token})
        return token

    @staticmethod
    def regenerate_mobile_token() -> str:
        """Генерирует и сохраняет новый 6-значный токен сопряжения смартфонов."""
        token = f"{secrets.randbelow(900000) + 100000}"
        SettingsService.set_many({"mobile_server_token": token})
        return token

    @staticmethod
    def get_mobile_server_port() -> int:
        raw = SettingsService.get("mobile_server_port", "8765")
        try:
            port = int(raw)
            if 1024 <= port <= 65535:
                return port
        except ValueError:
            pass
        return 8765

    @staticmethod
    def get_stock_group_mode() -> str:
        """Режим группировки товаров на складе: 'name' | 'brand' | 'category' | 'none'."""
        mode = SettingsService.get("stock_group_mode", "name").strip().lower()
        return mode if mode in ("name", "brand", "category", "none") else "name"

    @staticmethod
    def set_stock_group_mode(mode: str) -> None:
        clean = mode if mode in ("name", "brand", "category", "none") else "name"
        SettingsService.set_many({"stock_group_mode": clean})

    @staticmethod
    def get_product_remember_fields() -> dict[str, bool]:
        """Возвращает карту полей, которые автоматически запоминаются при добавлении товара."""
        defaults = {
            "category": True,
            "brand": True,
            "model": True,
            "reference": True,
            "cost": True,
            "min_stock": True,
            "name": False,
            "barcode": False,
        }
        raw = SettingsService.get("product_remember_fields", "")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    for key in defaults:
                        if key in parsed:
                            defaults[key] = bool(parsed[key])
            except ValueError:
                pass
        return defaults

    @staticmethod
    def set_product_remember_fields(fields: dict[str, bool]) -> None:
        current = SettingsService.get_product_remember_fields()
        for k in current:
            if k in fields:
                current[k] = bool(fields[k])
        SettingsService.set_many({"product_remember_fields": json.dumps(current)})

    @staticmethod
    def get_last_product_draft() -> dict:
        raw = SettingsService.get("last_product_draft", "{}")
        try:
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def save_last_product_draft(draft: dict) -> None:
        SettingsService.set_many({"last_product_draft": json.dumps(draft, ensure_ascii=False)})
