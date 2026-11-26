import os
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _resolve_bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_VERSION = "1.5.5"

PROJECT_ROOT = _resolve_project_root()
BUNDLE_ROOT = _resolve_bundle_root()
_CUSTOM_DATA_ROOT = os.environ.get("MOBILESTORE_DATA_DIR")
_STORAGE_ROOT = Path(_CUSTOM_DATA_ROOT).resolve() if _CUSTOM_DATA_ROOT else PROJECT_ROOT

DATA_DIR = _STORAGE_ROOT / "data"
BACKUP_DIR = _STORAGE_ROOT / "backups"
DATABASE_PATH = DATA_DIR / "mobilestore.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


def ensure_app_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

