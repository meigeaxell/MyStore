import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import BACKUP_DIR, DATABASE_PATH
from app.database.engine import engine, initialize_database
from app.services.settings_service import SettingsService

REQUIRED_TABLES = {
    "categories",
    "products",
    "stock_items",
    "purchases",
    "sales",
    "cash_movements",
}


class BackupService:
    """Сервис безопасного резервного копирования, проверки и восстановления БД SQLite (Фаза VII)."""

    @staticmethod
    def get_backup_directory() -> Path:
        configured = SettingsService.get("backup_directory", str(BACKUP_DIR)).strip()
        path = Path(configured) if configured else BACKUP_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def create_backup(
        target_dir: Path | str | None = None,
        prefix: str = "mobilestore_backup",
        apply_retention: bool = True,
    ) -> Path:
        """Создает консистентную резервную копию с помощью SQLite Online Backup API."""
        if not DATABASE_PATH.exists():
            raise FileNotFoundError(f"Maglumat bazasynyň faýly tapylmady: {DATABASE_PATH}")

        dest_dir = Path(target_dir) if target_dir else BackupService.get_backup_directory()
        dest_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = dest_dir / f"{prefix}_{timestamp}.db"

        src_conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
        dst_conn = sqlite3.connect(str(backup_path), timeout=30)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        ok, msg = BackupService.verify_backup(backup_path)
        if not ok:
            backup_path.unlink(missing_ok=True)
            raise ValueError(f"Döredilen ätiýaçlyk nusga barlagdan geçmedi: {msg}")

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        SettingsService.set_many({"last_backup_at": now_iso})

        if apply_retention:
            BackupService.enforce_retention_policy(dest_dir)

        return backup_path

    @staticmethod
    def verify_backup(backup_file: Path | str) -> tuple[bool, str]:
        """Проверяет целостность файла резервной копии и наличие основных таблиц MobileStore (Раздел 11.4)."""
        path = Path(backup_file)
        if not path.exists() or not path.is_file():
            return False, "Ätiýaçlyk nusga faýly ýok."
        if path.stat().st_size < 4096:
            return False, "Faýl gaty kiçi we dogry SQLite maglumat bazasy däl."

        try:
            uri = f"file:{path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=15)
            try:
                cur = conn.cursor()
                integrity = cur.execute("PRAGMA integrity_check").fetchone()
                if not integrity or str(integrity[0]).lower() != "ok":
                    return False, f"SQLite bitewilik ýalňyşlygy: {integrity}"

                tables_rows = cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                existing_tables = {r[0] for r in tables_rows}

                missing = REQUIRED_TABLES - existing_tables
                if missing:
                    return (
                        False,
                        f"Bazada MobileStore-yň hökmany tablisalary ýok: {', '.join(sorted(missing))}",
                    )

                return True, f"Bitewilik tassyklandy (tablisalar: {len(existing_tables)})."
            finally:
                conn.close()
        except sqlite3.Error as err:
            return False, f"SQLite okama ýalňyşlygy: {err}"

    @staticmethod
    def list_backups(directory: Path | str | None = None) -> list[dict]:
        """Возвращает список доступных резервных копий в выбранной папке."""
        target = Path(directory) if directory else BackupService.get_backup_directory()
        if not target.exists():
            return []

        files = sorted(
            target.glob("*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        results = []
        for f in files:
            stat = f.stat()
            results.append({
                "path": f,
                "name": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified_at": datetime.fromtimestamp(stat.st_mtime),
            })
        return results

    @staticmethod
    def enforce_retention_policy(directory: Path | str | None = None) -> int:
        """Удаляет старые резервные копии, оставляя последние N файлов (Раздел 11.1)."""
        raw_keep = SettingsService.get("backup_retention_count", "15")
        try:
            keep_count = max(1, int(raw_keep))
        except ValueError:
            keep_count = 15

        target = Path(directory) if directory else BackupService.get_backup_directory()
        if not target.exists():
            return 0

        backups = sorted(
            target.glob("mobilestore_backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        deleted = 0
        for old_file in backups[keep_count:]:
            try:
                old_file.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    @staticmethod
    def restore_backup(
        backup_file: Path | str,
        create_safety_backup: bool = True,
    ) -> Path | None:
        """Безопасно восстанавливает базу данных из проверенной резервной копии (Раздел 11.3)."""
        src_path = Path(backup_file)
        ok, msg = BackupService.verify_backup(src_path)
        if not ok:
            raise ValueError(f"Zeperlenen faýldan bazany dikeldip bolmaýar:\n{msg}")

        safety_path = None
        if create_safety_backup and DATABASE_PATH.exists():
            safety_path = BackupService.create_backup(
                prefix="pre_restore_safety",
                apply_retention=False,
            )

        # Закрываем пул соединений SQLAlchemy перед перезаписью БД
        engine.dispose()

        src_conn = sqlite3.connect(str(src_path), timeout=30)
        dst_conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Повторно инициализируем соединение SQLAlchemy
        initialize_database()
        return safety_path

    @staticmethod
    def run_auto_backup_if_due() -> Path | None:
        """Выполняет автоматическое резервное копирование при запуске, если оно включено и подошел срок."""
        cfg = SettingsService.get_all()
        if cfg.get("auto_backup_enabled") != "1":
            return None

        freq = cfg.get("auto_backup_frequency", "daily")
        if freq == "manual":
            return None

        last_str = (cfg.get("last_backup_at") or "").strip()
        if freq == "daily" and last_str:
            try:
                last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                if last_dt.date() == datetime.now().date():
                    return None
            except ValueError:
                pass

        try:
            return BackupService.create_backup(prefix="mobilestore_backup", apply_retention=True)
        except (OSError, ValueError, sqlite3.Error):
            return None
