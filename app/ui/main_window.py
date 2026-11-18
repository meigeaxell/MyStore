
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui import theme
from app.ui.catalog_page import CatalogPage
from app.ui.dashboard_page import DashboardPage
from app.ui.purchase_page import PurchasePage
from app.ui.stock_page import StockPage
from app.ui.sales_page import SalesPage

NAV = [
    ("Основное", [
        ("Главная панель", "⌂"),
    ]),
    ("Товары", [
        ("Каталог товаров", "▤"),
        ("Склад", "▦"),
        ("Закупки", "⇩"),
    ]),
    ("Продажи", [
        ("Продажи и касса", "◉"),
        ("Trade-in", "⇄"),
    ]),
    ("Финансы", [
        ("Финансы", "₮"),
    ]),
    ("Аналитика", [
        ("Отчёты", "▥"),
    ]),
    ("Система", [
        ("Настройки", "⚙"),
    ]),
]


class PlaceholderPage(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)

        head = QLabel(title)
        head.setObjectName("pageTitle")

        note = QLabel("Раздел в разработке")
        note.setObjectName("mutedText")

        layout.addWidget(head)
        layout.addWidget(note)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MobileStore")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(theme.STYLE)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)

        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self._register_pages()
        self.statusBar().showMessage("Готово • Локальная база данных")

    def _register_pages(self) -> None:
        for index, button in enumerate(self.nav_buttons):
            name = button.property("title")

            if name == "Главная панель":
                page = DashboardPage()
            elif name == "Каталог товаров":
                page = CatalogPage()
            elif name == "Склад":
                page = StockPage()
            elif name == "Продажи и касса":
                page = SalesPage()
            elif name == "Закупки":
                page = PurchasePage()
            else:
                page = PlaceholderPage(name)

            self.pages.addWidget(page)
            button.clicked.connect(
                lambda _=False, idx=index: self.pages.setCurrentIndex(idx)
            )

        self.nav_buttons[0].setChecked(True)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(64)

        row = QHBoxLayout(bar)
        row.setContentsMargins(28, 0, 28, 0)
        row.setSpacing(10)

        search = QLineEdit()
        search.setObjectName("search")
        search.setPlaceholderText("Поиск товара, IMEI, клиента…")
        row.addWidget(search)

        row.addStretch()

        sale = QPushButton("+  Новая продажа")
        sale.setObjectName("primaryBtn")

        cash = QPushButton("Касса")
        cash.setObjectName("darkBtn")

        for button in (sale, cash):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button)

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 10)

        mark = QLabel("M")
        mark.setObjectName("brandMark")

        brand = QLabel("MobileStore")
        brand.setObjectName("brand")

        brand_row.addWidget(mark)
        brand_row.addSpacing(8)
        brand_row.addWidget(brand, 1)

        layout.addLayout(brand_row)

        group = QButtonGroup(self)
        group.setExclusive(True)

        self.nav_buttons: list[QPushButton] = []

        for section, items in NAV:
            label = QLabel(section)
            label.setObjectName("navSection")
            layout.addWidget(label)

            for name, icon in items:
                button = QPushButton(f"{icon}   {name}")
                button.setObjectName("navButton")
                button.setProperty("title", name)
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)

                group.addButton(button)
                layout.addWidget(button)
                self.nav_buttons.append(button)

        layout.addStretch()

        footer = QLabel("Версия 0.1.0")
        footer.setObjectName("sideFooter")
        layout.addWidget(footer)

        return sidebar
