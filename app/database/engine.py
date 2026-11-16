from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL

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


def initialize_database() -> None:
    """Проверяет соединение; схему позже будем обновлять миграциями Alembic."""
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
