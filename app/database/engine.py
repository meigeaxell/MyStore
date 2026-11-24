from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import BUNDLE_ROOT, DATABASE_URL, ensure_app_directories

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def _run_migrations() -> None:
    """Применяет миграции Alembic (автоматически создаёт или обновляет схему БД)."""
    from alembic import command
    from alembic.config import Config

    migrations_dir = BUNDLE_ROOT / "migrations"
    alembic_ini = BUNDLE_ROOT / "alembic.ini"
    if not migrations_dir.exists():
        return

    alembic_cfg = Config(str(alembic_ini)) if alembic_ini.exists() else Config()
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    existing_tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in existing_tables and "categories" in existing_tables:
        command.stamp(alembic_cfg, "head")
    else:
        command.upgrade(alembic_cfg, "head")


def initialize_database() -> None:
    """Создаёт каталоги данных, применяет миграции Alembic и проверяет соединение."""
    ensure_app_directories()
    _run_migrations()
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    from app.repositories.product_repository import ensure_system_phone_categories

    ensure_system_phone_categories()
