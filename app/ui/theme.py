
"""Единая светлая тема приложения MobileStore."""

from app.config import BUNDLE_ROOT

ACCENT = "#F58A2E"
ACCENT_SOFT = "#FFE6CC"
ACCENT_BG = "#FFF3E6"
NAVY = "#1B2A41"
TEAL = "#1E9E86"
BLUE = "#2F6BFF"
GREEN = "#16A34A"
RED = "#E5484D"
TEXT = "#1D2939"
MUTED = "#667085"
BORDER = "#E8EBF0"
BG = "#F6F7F9"
WHITE = "#FFFFFF"

# --- Производные цвета (токены; значения не менять без визуальной проверки) ---
ACCENT_HOVER = "#E57C20"
NAVY_HOVER = "#26395A"
GREEN_HOVER = "#15803D"
BORDER_STRONG = "#D0D5DD"
FAINT = "#98A2B3"
TEXT_NAV = "#475467"
SURFACE_SUBTLE = "#F2F4F7"
SURFACE_HEADER = "#F8F9FB"
SURFACE_ALT = "#FAFBFC"
TAB_BG = "#EAECF0"
ROW_DIVIDER = "#F0F1F3"
DANGER_BG = "#FDECEA"
DANGER_BORDER = "#F9CFCB"
DANGER_TEXT = "#B42318"

# --- Типографическая шкала (pt) ---
FS_CAPTION = 8.5
FS_BODY = 10
FS_SECTION = 12
FS_KPI = 16
FS_TITLE = 20

# --- Отступы, радиусы, высоты (px, шаг 4) ---
SP_1, SP_2, SP_3, SP_4, SP_6 = 4, 8, 12, 16, 24
RADIUS_SM, RADIUS_MD, RADIUS_LG = 6, 8, 12
ROW_H_COMFORTABLE, ROW_H_COMPACT = 46, 34

_ICONS_DIR = BUNDLE_ROOT / "resources" / "icons"
_ICON_CHEVRON_DOWN = (_ICONS_DIR / "chevron_down.svg").as_posix()
_ICON_CHEVRON_DOWN_ACCENT = (_ICONS_DIR / "chevron_down_accent.svg").as_posix()
_ICON_CHECK_WHITE = (_ICONS_DIR / "check_white.svg").as_posix()
_ICON_LEFT_WHITE = (_ICONS_DIR / "chevron_left_white.svg").as_posix()
_ICON_RIGHT_WHITE = (_ICONS_DIR / "chevron_right_white.svg").as_posix()

STYLE = f"""
* {{
    font-family: "Inter", "Segoe UI", "SF Pro Text", "Noto Sans", sans-serif;
}}

QMainWindow, QWidget#page,
QScrollArea, QScrollArea > QWidget > QWidget,
QTabWidget::pane > QWidget {{
    background: {BG};
}}

QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}

QDialog, QMessageBox, QInputDialog, QFileDialog {{
    background: {BG};
    color: {TEXT};
}}

QWidget#dialogFooter {{
    background: {WHITE};
    border-top: 1px solid {BORDER};
}}

QTreeView {{
    background-color: {WHITE};
    alternate-background-color: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT_BG};
    selection-color: {TEXT};
    outline: none;
}}

QTreeView::item {{
    padding: 5px 8px;
}}

QTreeView::item:hover {{
    background: {ACCENT_BG};
}}

QTreeView::item:selected {{
    background: {ACCENT_SOFT};
    color: {NAVY};
}}

/* ---------- Флажки (QCheckBox) ---------- */

QCheckBox {{
    spacing: 8px;
    color: {TEXT};
    background: transparent;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid {BORDER_STRONG};
    background-color: {WHITE};
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT};
    background-color: {ACCENT_BG};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border: 1.5px solid {ACCENT};
    image: url("{_ICON_CHECK_WHITE}");
}}

QCheckBox::indicator:checked:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QCheckBox::indicator:disabled {{
    background-color: {SURFACE_SUBTLE};
    border-color: {BORDER};
}}

/* ---------- Вкладки (QTabWidget / QTabBar) ---------- */

QTabWidget::pane {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
    top: -1px;
}}

QTabBar {{
    background: transparent;
}}

QTabBar::tab {{
    background: {TAB_BG};
    color: {MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 9px 18px;
    margin-right: 4px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    background: {ACCENT_BG};
    color: {NAVY};
}}

QTabBar::tab:selected {{
    background: {WHITE};
    color: {ACCENT};
    border-color: {BORDER};
    border-bottom: 2px solid {ACCENT};
}}

/* ---------- Списки (QListWidget / QListView) ---------- */

QListWidget, QListView {{
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QListWidget::item, QListView::item {{
    padding: 8px 10px;
    border-radius: 6px;
    color: {TEXT};
}}

QListWidget::item:hover, QListView::item:hover {{
    background-color: {ACCENT_BG};
    color: {TEXT};
}}

QListWidget::item:selected, QListView::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}

QLabel {{
    background: transparent;
    color: {TEXT};
}}

QScrollArea {{
    border: none;
}}

/* ---------- Поля ввода ---------- */

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QDateEdit,
QDateTimeEdit,
QTimeEdit,
QComboBox {{
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 20px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

QLineEdit:hover,
QTextEdit:hover,
QPlainTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QDateEdit:hover,
QDateTimeEdit:hover,
QTimeEdit:hover,
QComboBox:hover {{
    border-color: {BORDER_STRONG};
}}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QDateEdit:focus,
QDateTimeEdit:focus,
QTimeEdit:focus,
QComboBox:focus {{
    background-color: {WHITE};
    border: 1px solid {ACCENT};
}}

QLineEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled,
QComboBox:disabled {{
    background-color: {SURFACE_SUBTLE};
    color: {FAINT};
}}

/* ---------- Выпадающие списки и календари ---------- */

QComboBox,
QDateEdit,
QDateTimeEdit {{
    padding-right: 30px;
}}

QComboBox::drop-down,
QDateEdit::drop-down,
QDateTimeEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    background: transparent;
    border: none;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}}

QComboBox::drop-down:hover,
QDateEdit::drop-down:hover,
QDateTimeEdit::drop-down:hover {{
    background: {ACCENT_BG};
}}

QComboBox::down-arrow,
QDateEdit::down-arrow,
QDateTimeEdit::down-arrow {{
    image: url("{_ICON_CHEVRON_DOWN}");
    width: 12px;
    height: 12px;
}}

QComboBox::down-arrow:hover,
QComboBox::down-arrow:on,
QDateEdit::down-arrow:hover,
QDateEdit::down-arrow:on,
QDateTimeEdit::down-arrow:hover,
QDateTimeEdit::down-arrow:on {{
    image: url("{_ICON_CHEVRON_DOWN_ACCENT}");
}}

QComboBox QAbstractItemView {{
    background-color: {WHITE};
    color: {TEXT};
    border: none;
    padding: 2px;
    outline: none;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {NAVY};
}}

QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 6px 10px;
    border: none;
    background-color: {WHITE};
    color: {TEXT};
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {ACCENT_BG};
    color: {NAVY};
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {NAVY};
}}

/* ---------- Выпадающий календарь (QCalendarWidget) ---------- */

QCalendarWidget {{
    background-color: {WHITE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
    min-width: 330px;
    min-height: 260px;
}}

QCalendarWidget QTableView {{
    background-color: {WHITE};
    alternate-background-color: {SURFACE_HEADER};
    border: none;
    border-radius: 0px;
    padding: 0px;
    selection-background-color: {ACCENT};
    selection-color: {WHITE};
    outline: none;
}}

QCalendarWidget QTableView::item {{
    padding: 2px;
    border: none;
}}

QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {NAVY};
    min-height: 40px;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 4px 6px;
}}

QCalendarWidget QToolButton {{
    color: {WHITE};
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 700;
    font-size: 10pt;
}}

QCalendarWidget QToolButton:hover {{
    background-color: rgba(255, 255, 255, 0.16);
}}

QCalendarWidget QToolButton::menu-indicator {{
    image: none;
    width: 0px;
}}

QCalendarWidget QToolButton#qt_calendar_prevmonth {{
    qproperty-icon: none;
    image: url("{_ICON_LEFT_WHITE}");
    min-width: 28px;
    min-height: 28px;
}}

QCalendarWidget QToolButton#qt_calendar_nextmonth {{
    qproperty-icon: none;
    image: url("{_ICON_RIGHT_WHITE}");
    min-width: 28px;
    min-height: 28px;
}}

QCalendarWidget QMenu {{
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 4px;
}}

QCalendarWidget QMenu::item {{
    padding: 6px 14px;
    border-radius: 5px;
}}

QCalendarWidget QMenu::item:selected {{
    background-color: {ACCENT_BG};
    color: {NAVY};
}}

QCalendarWidget QSpinBox {{
    background-color: rgba(255, 255, 255, 0.14);
    color: {WHITE};
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 6px;
    padding: 2px 6px;
    font-weight: 700;
}}

QCalendarWidget QAbstractItemView:enabled {{
    background-color: {WHITE};
    alternate-background-color: {SURFACE_HEADER};
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {WHITE};
    outline: none;
    font-size: 9.5pt;
}}

QCalendarWidget QAbstractItemView:disabled {{
    color: {FAINT};
}}

/* ---------- Числовые поля (без стрелок для чистого вида) ---------- */

QSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}}

QSpinBox::up-arrow,
QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow,
QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}

QTimeEdit::up-button,
QTimeEdit::down-button {{
    background: transparent;
    border: none;
    width: 18px;
}}

/* ---------- Сайдбар ---------- */

QFrame#sidebar {{
    background: white;
    border-right: 1px solid {BORDER};
}}

QLabel#brand {{
    font-size: 16pt;
    font-weight: 700;
    color: {NAVY};
}}

QLabel#brandMark {{
    background: {ACCENT};
    color: white;
    border-radius: 9px;
    font-weight: 800;
    font-size: 13pt;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    qproperty-alignment: AlignCenter;
}}

QLabel#navSection {{
    color: {FAINT};
    font-size: 8.5pt;
    font-weight: 600;
    padding: 14px 12px 4px;
}}

QPushButton#brandNavButton {{
    background: transparent;
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 8px 10px;
    text-align: left;
    font-size: 14pt;
    font-weight: 800;
    color: {NAVY};
}}

QPushButton#brandNavButton:hover {{
    background: {SURFACE_SUBTLE};
    border-color: {BORDER};
}}

QPushButton#brandNavButton:checked {{
    background: {ACCENT_BG};
    border-color: {ACCENT};
    color: {ACCENT};
}}

QPushButton#navButton {{
    color: {TEXT_NAV};
    background: transparent;
    border: 0;
    border-radius: 8px;
    text-align: left;
    padding: 10px 12px;
    font-weight: 500;
}}

QPushButton#navButton:hover {{
    background: {SURFACE_SUBTLE};
    color: {NAVY};
}}

QPushButton#navButton:checked {{
    background: {ACCENT_BG};
    color: {ACCENT};
    font-weight: 700;
}}

QLabel#sideFooter {{
    color: {FAINT};
    font-size: 8.5pt;
    padding: 4px 12px;
}}

/* ---------- Верхняя панель ---------- */

QFrame#topbar {{
    background: white;
    border-bottom: 1px solid {BORDER};
}}

QLineEdit#search {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 8px 12px;
    min-width: 260px;
}}

QLineEdit#search:focus {{
    border: 1px solid {ACCENT};
    background: white;
}}

QPushButton#primaryBtn {{
    background: {ACCENT};
    color: white;
    border: 0;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}}

QPushButton#primaryBtn:hover {{
    background: {ACCENT_HOVER};
}}

QPushButton#primaryBtn:focus {{
    border: 2px solid {NAVY};
}}

QPushButton#successBtn {{
    background: {GREEN};
    color: white;
    border: 0;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}}

QPushButton#successBtn:hover {{
    background: {GREEN_HOVER};
}}

QPushButton#successBtn:focus {{
    border: 2px solid {NAVY};
}}

QPushButton#darkBtn {{
    background: {NAVY};
    color: white;
    border: 0;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}}

QPushButton#darkBtn:hover {{
    background: {NAVY_HOVER};
}}

QPushButton#dangerBtn {{
    background: white;
    color: {RED};
    border: 1px solid {RED};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}}

QPushButton#dangerBtn:hover {{
    background: {DANGER_BG};
    border-color: {RED};
}}

QPushButton#secondaryBtn {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}}

QPushButton#secondaryBtn:hover {{
    background: {ACCENT_BG};
    border-color: {ACCENT};
}}

/* ---------- Обычные кнопки ---------- */

QPushButton {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 500;
}}

QPushButton:hover {{
    background: {ACCENT_BG};
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background: {ACCENT_SOFT};
}}

QPushButton:disabled {{
    background: {SURFACE_SUBTLE};
    color: {FAINT};
    border-color: {BORDER};
}}

/* ---------- Размеры кнопок (property "btnSize") ---------- */

QPushButton[btnSize="sm"] {{
    padding: 5px 10px;
    font-size: 9pt;
}}

QPushButton[btnSize="lg"] {{
    padding: 12px 22px;
    font-size: 11pt;
}}

QPushButton#ghostBtn {{
    background: transparent;
    color: {TEXT_NAV};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}}

QPushButton#ghostBtn:hover {{
    background: {SURFACE_SUBTLE};
    color: {NAVY};
}}

/* ---------- Бейджи статуса и встроенные предупреждения ---------- */

QLabel#statusBadge {{
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 8.5pt;
    font-weight: 600;
    background: {SURFACE_SUBTLE};
    color: {TEXT_NAV};
}}

QLabel#statusBadge[tone="success"] {{ background: #E7F6EC; color: {GREEN_HOVER}; }}
QLabel#statusBadge[tone="warning"] {{ background: #FEF3C7; color: #92400E; }}
QLabel#statusBadge[tone="danger"] {{ background: {DANGER_BG}; color: {DANGER_TEXT}; }}
QLabel#statusBadge[tone="info"] {{ background: #E0EAFF; color: #1D4ED8; }}
QLabel#statusBadge[tone="accent"] {{ background: {ACCENT_SOFT}; color: #C2410C; }}

QFrame#inlineAlert {{
    border-radius: 9px;
    border: 1px solid {BORDER};
    background: {SURFACE_SUBTLE};
}}

QFrame#inlineAlert[tone="info"] {{ background: #EEF4FF; border-color: #C7D7FE; }}
QFrame#inlineAlert[tone="warning"] {{ background: #FFFAEB; border-color: #FEDF89; }}
QFrame#inlineAlert[tone="danger"] {{ background: {DANGER_BG}; border-color: {DANGER_BORDER}; }}

QLabel#inlineAlertText {{ color: {TEXT}; background: transparent; }}

/* ---------- Карточки ---------- */

QFrame#card {{
    background: white;
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#clickableCard {{
    background: white;
    border: 1.5px solid {BORDER};
    border-radius: 12px;
}}

QFrame#clickableCard:hover,
QFrame#clickableCard:focus {{
    background: {ACCENT_BG};
    border: 1.5px solid {ACCENT};
}}

QLabel#pageTitle {{
    font-size: 20pt;
    font-weight: 700;
    color: {NAVY};
}}

QLabel#mutedText {{
    color: {MUTED};
}}

QLabel#cardTitle {{
    font-size: 12pt;
    font-weight: 700;
    color: {NAVY};
}}

QLabel#kpiValue {{
    font-size: 16pt;
    font-weight: 700;
    color: {NAVY};
}}

QLabel#datePill {{
    background: white;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

/* ---------- Таблицы ---------- */

QTableWidget,
QTableView {{
    background-color: white;
    alternate-background-color: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_BG};
    selection-color: {TEXT};
    outline: none;
}}

QTableWidget::item,
QTableView::item {{
    padding: 9px;
    border: none;
    border-bottom: 1px solid {ROW_DIVIDER};
}}

QTableWidget::item:selected,
QTableView::item:selected {{
    background: {ACCENT_BG};
    color: {TEXT};
}}

QHeaderView::section {{
    background: {SURFACE_HEADER};
    color: {MUTED};
    padding: 12px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}

/* ---------- Уведомления ---------- */

QFrame#alert {{
    background: {DANGER_BG};
    border: 1px solid {DANGER_BORDER};
    border-radius: 9px;
}}

QLabel#alertText {{
    color: {DANGER_TEXT};
}}

QPushButton#alertClose {{
    background: transparent;
    border: 0;
    color: {DANGER_TEXT};
    font-size: 12pt;
}}

/* ---------- Чипы и ссылки ---------- */

QPushButton#chip {{
    background: {BG};
    border: 0;
    border-radius: 6px;
    padding: 5px 11px;
    color: {MUTED};
}}

QPushButton#chip:checked {{
    background: {ACCENT};
    color: white;
    font-weight: 600;
}}

QPushButton#linkBtn {{
    background: transparent;
    border: 0;
    color: {ACCENT};
    font-weight: 600;
}}

QPushButton#linkBtn:hover {{
    text-decoration: underline;
}}

/* ---------- Статусная панель ---------- */

QStatusBar {{
    background: white;
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}

/* ---------- Разделители ---------- */

QFrame[frameShape="4"],
QFrame[frameShape="5"] {{
    color: {BORDER};
}}

/* ---------- Полосы прокрутки ---------- */

QScrollBar:vertical {{
    width: 10px;
    background: transparent;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {FAINT};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    border: none;
}}

QScrollBar:horizontal {{
    height: 10px;
    background: transparent;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 30px;
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    border: none;
}}

/* ---------- Всплывающие подсказки ---------- */

QToolTip {{
    background: {NAVY};
    color: white;
    border: none;
    border-radius: 5px;
    padding: 5px 8px;
}}
"""
