import sys

from PySide6.QtWidgets import QApplication

from app.config import ensure_app_directories
from app.database.engine import initialize_database
from app.ui.main_window import MainWindow


def run() -> int:
    ensure_app_directories()
    initialize_database()
    app = QApplication(sys.argv)
    app.setApplicationName("MobileStore")
    app.setOrganizationName("MobileStore")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())

