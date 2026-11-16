from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.pages.dashboard_page import DashboardPage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MobileStore")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.addWidget(DashboardPage())
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Готово • Локальная база данных")

        self.setStyleSheet("""
            QMainWindow, QWidget { background: #F5F7FA; color: #1D2939; font-family: sans-serif; }
            QFrame#sidebar { background: #17263C; min-width: 220px; max-width: 220px; }
            QLabel#brand { color: white; font-size: 19pt; font-weight: bold; padding: 8px 4px 22px; }
            QPushButton#navButton { color: #D7DFEA; background: transparent; border: 0;
                border-radius: 7px; text-align: left; padding: 11px 12px; }
            QPushButton#navButton:hover { background: #263B58; color: white; }
            QLabel#pageTitle { color: #17263C; font-size: 22pt; font-weight: bold; }
            QLabel#mutedText { color: #667085; font-size: 10pt; }
            QStatusBar { background: white; color: #667085; border-top: 1px solid #E4E7EC; }
        """)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(7)
        brand = QLabel("MobileStore")
        brand.setObjectName("brand")
        layout.addWidget(brand)

        for name in [
            "Главная панель", "Каталог товаров", "Склад", "Закупки",
            "Продажи и касса", "Trade-in", "Бонусы", "Финансы",
            "Отчёты", "Настройки"
        ]:
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setEnabled(name == "Главная панель")
            layout.addWidget(button)

        layout.addStretch()
        footer = QLabel("Версия 0.1.0 • Каркас")
        footer.setStyleSheet("color: #91A0B5; font-size: 8pt; padding: 4px;")
        layout.addWidget(footer)
        return sidebar
