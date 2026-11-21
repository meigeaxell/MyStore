import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import DATA_DIR, ensure_app_directories
from app.database.engine import initialize_database
from app.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    smoke_test = "--smoke-test" in args

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MobileStore")
    app.setOrganizationName("MobileStore")

    try:
        ensure_app_directories()
        initialize_database()
        window = MainWindow()
    except Exception as exc:
        ensure_app_directories()
        log_path = DATA_DIR / "startup_error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        if smoke_test:
            raise
        QMessageBox.critical(
            None,
            "MobileStore — Başlatma ýalňyşlygy",
            f"Programmany açyp bolmady:\n{exc}\n\nJikme-jik maglumat: {log_path}",
        )
        return 1

    if smoke_test:
        window.close()
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
