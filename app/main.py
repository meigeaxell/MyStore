import ctypes
import sys
import traceback

from PySide6.QtCore import QEvent, QLocale, QObject, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPalette
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QMessageBox

from app.config import BUNDLE_ROOT, DATA_DIR, ensure_app_directories
from app.database.engine import initialize_database
from app.ui import theme
from app.ui.main_window import MainWindow


def _build_light_palette() -> QPalette:
    """Принудительная светлая палитра Qt, чтобы тёмная тема ОС (Linux KDE / Windows Dark)
    не просвечивала в QFileDialog, QComboBox, QCalendarWidget и QCheckBox."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(theme.BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#FAFBFC"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.NAVY))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Text, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.BrightText, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(theme.ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#98A2B3"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#98A2B3"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#98A2B3"))
    return pal


class DecimalDotEventFilter(QObject):
    """Заменяет ввод запятой на точку в числовых полях QDoubleSpinBox (удобно для NumPad и любых раскладок)."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.text() == ","
        ):
            target = watched
            parent = target.parent() if isinstance(target, QObject) else None
            if isinstance(target, QDoubleSpinBox) or isinstance(parent, QDoubleSpinBox):
                dot_event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_Period,
                    event.modifiers(),
                    ".",
                    event.isAutoRepeat(),
                    event.count(),
                )
                QApplication.sendEvent(target, dot_event)
                return True
        return super().eventFilter(watched, event)


def _resolve_app_icon() -> QIcon:
    candidates = (
        ("resources/mobilestore.ico", "resources/mobilestore.svg", "resources/mobilestore.png")
        if sys.platform == "win32"
        else ("resources/mobilestore.svg", "resources/mobilestore.png", "resources/mobilestore.ico")
    )
    for rel in candidates:
        path = BUNDLE_ROOT / rel
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    smoke_test = "--smoke-test" in args

    if sys.platform == "win32":
        import contextlib

        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MobileStore.Desktop.App"
            )

    QLocale.setDefault(QLocale.c())

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(_build_light_palette())
    app.setApplicationName("MobileStore")
    app.setOrganizationName("MobileStore")

    app_icon = _resolve_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    dot_filter = DecimalDotEventFilter(app)
    app.installEventFilter(dot_filter)

    try:
        ensure_app_directories()
        initialize_database()
        window = MainWindow()
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
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
