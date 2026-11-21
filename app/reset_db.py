"""Консольная утилита для полного сброса данных базы MobileStore без затрагивания кода.

Запуск:
    .venv/bin/python -m app.reset_db
    или
    ./reset_db.sh
"""
import argparse
import shutil
import sys
from datetime import datetime

from alembic import command
from alembic.config import Config

from app.config import (
    BACKUP_DIR,
    DATABASE_PATH,
    PROJECT_ROOT,
    ensure_app_directories,
)
from app.database.engine import engine


def reset_database(skip_confirm: bool = False, clear_backups: bool = False) -> int:
    ensure_app_directories()

    print("=== MobileStore: Сброс базы данных ===")
    print(f"Файл базы данных: {DATABASE_PATH}")
    print("ВНИМАНИЕ: Все товары, складские остатки, IMEI, закупки, продажи и финансы будут очищены.")
    print("Исходный код приложения затронут НЕ будет.\n")

    if not skip_confirm:
        answer = input("Вы уверены, что хотите очистить все данные и начать с нуля? [y/N]: ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено пользователем.")
            return 0

    engine.dispose()

    # Создаём страховочную копию перед удалением, если база существует и не выбран флаг очистки бэкапов
    if DATABASE_PATH.exists() and not clear_backups:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_path = BACKUP_DIR / f"pre_reset_safety_{stamp}.db"
        shutil.copy2(DATABASE_PATH, safety_path)
        print(f"✔ Создана страховочная резервная копия: {safety_path}")

    # Удаляем только файлы базы данных SQLite
    for suffix in ("", "-wal", "-shm"):
        db_file = DATABASE_PATH.parent / f"{DATABASE_PATH.name}{suffix}"
        if db_file.exists():
            db_file.unlink()

    if clear_backups:
        removed = 0
        for b_file in BACKUP_DIR.glob("*.db"):
            b_file.unlink()
            removed += 1
        print(f"✔ Удалено старых резервных копий: {removed}")

    # Применяем миграции Alembic для создания чистой структуры таблиц
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(alembic_cfg, "head")

    print("\n✔ База данных MobileStore успешно сброшена и готова к работе с чистого листа!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сброс всех пользовательских данных MobileStore и создание чистой базы данных."
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Сбросить базу без интерактивного запроса подтверждения.",
    )
    parser.add_argument(
        "--clear-backups",
        action="store_true",
        help="Также удалить все старые резервные копии из папки backups/.",
    )
    args = parser.parse_args()
    return reset_database(skip_confirm=args.yes, clear_backups=args.clear_backups)


if __name__ == "__main__":
    sys.exit(main())
