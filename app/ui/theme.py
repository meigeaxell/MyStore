
"""Единая светлая тема приложения MobileStore."""

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

STYLE = f"""
* {{
    font-family: "Inter", "Segoe UI", "SF Pro Text", "Noto Sans", sans-serif;
}}

QMainWindow, QWidget#page,
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {BG};
}}

QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}

QDialog {{
    background: {BG};
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
    border-color: #D0D5DD;
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
    background-color: #F2F4F7;
    color: #98A2B3;
}}

/* ---------- Выпадающие списки ---------- */

QComboBox {{
    padding-right: 28px;
}}

QComboBox::drop-down {{
    background: transparent;
    border: none;
    width: 28px;
}}

QComboBox::down-arrow {{
    width: 8px;
    height: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: {ACCENT_BG};
    selection-color: {TEXT};
}}

QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 5px 8px;
    border: none;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {ACCENT_BG};
    color: {TEXT};
}}

/* ---------- Кнопки числовых полей ---------- */

QSpinBox::up-button,
QDoubleSpinBox::up-button,
QDateEdit::up-button,
QDateTimeEdit::up-button,
QTimeEdit::up-button {{
    background: transparent;
    border: none;
    width: 20px;
}}

QSpinBox::down-button,
QDoubleSpinBox::down-button,
QDateEdit::down-button,
QDateTimeEdit::down-button,
QTimeEdit::down-button {{
    background: transparent;
    border: none;
    width: 20px;
}}

QSpinBox::up-button:hover,
QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{
    background: {ACCENT_BG};
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
    color: #98A2B3;
    font-size: 8.5pt;
    font-weight: 600;
    padding: 14px 12px 4px;
}}

QPushButton#navButton {{
    color: #475467;
    background: transparent;
    border: 0;
    border-radius: 8px;
    text-align: left;
    padding: 10px 12px;
    font-weight: 500;
}}

QPushButton#navButton:hover {{
    background: #F2F4F7;
    color: {NAVY};
}}

QPushButton#navButton:checked {{
    background: {ACCENT_BG};
    color: {ACCENT};
    font-weight: 700;
}}

QLabel#sideFooter {{
    color: #98A2B3;
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
    background: #E57C20;
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
    background: #26395A;
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
    background: #F2F4F7;
    color: #98A2B3;
    border-color: {BORDER};
}}

/* ---------- Карточки ---------- */

QFrame#card {{
    background: white;
    border: 1px solid {BORDER};
    border-radius: 12px;
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
    alternate-background-color: #FAFBFC;
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
    border-bottom: 1px solid #F0F1F3;
}}

QTableWidget::item:selected,
QTableView::item:selected {{
    background: {ACCENT_BG};
    color: {TEXT};
}}

QHeaderView::section {{
    background: #F8F9FB;
    color: {MUTED};
    padding: 12px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}

/* ---------- Уведомления ---------- */

QFrame#alert {{
    background: #FDECEA;
    border: 1px solid #F9CFCB;
    border-radius: 9px;
}}

QLabel#alertText {{
    color: #B42318;
}}

QPushButton#alertClose {{
    background: transparent;
    border: 0;
    color: #B42318;
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
    background: #D0D5DD;
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: #98A2B3;
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
    background: #D0D5DD;
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
