from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = PROJECT_ROOT / "backups"
DATABASE_PATH = DATA_DIR / "mobilestore.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


def ensure_app_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
