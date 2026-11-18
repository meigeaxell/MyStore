"""Переиспользуемые виджеты: карточки, график."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui import theme


def shadow(widget: QWidget) -> None:
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(18)
    fx.setOffset(0, 2)
    fx.setColor(QColor(16, 24, 40, 18))
    widget.setGraphicsEffect(fx)


class Card(QFrame):
    """Белая карточка с мягкой тенью."""

    def __init__(self, margins=(20, 18, 20, 18), spacing=12) -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)
        shadow(self)


def delta_badge(text: str, positive: bool) -> QLabel:
    color, bg = (theme.GREEN, "#E7F6EC") if positive else (theme.RED, "#FDECEA")
    arrow = "▲" if positive else "▼"
    label = QLabel(f"{arrow} {text}")
    label.setStyleSheet(
        f"background:{bg}; color:{color}; border-radius:9px; padding:2px 8px;"
        "font-size:8.5pt; font-weight:600;"
    )
    return label


class ColorStatCard(QFrame):
    """Яркая карточка-показатель (верхний ряд)."""

    def __init__(self, title: str, value: str, delta: str, positive: bool, color: str, glyph: str) -> None:
        super().__init__()
        self.setStyleSheet(f"QFrame#stat {{ background:{color}; border-radius:12px; }}")
        self.setObjectName("stat")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(14)

        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(44, 44)
        icon.setStyleSheet("background:rgba(255,255,255,0.95); border-radius:10px; "
                           f"color:{color}; font-size:17pt;")
        row.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("color:rgba(255,255,255,0.85); font-size:9pt;")
        v = QLabel(value)
        v.setStyleSheet("color:white; font-size:15pt; font-weight:700;")
        col.addWidget(t)
        col.addWidget(v)
        row.addLayout(col, 1)

        badge = delta_badge(delta, positive)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        shadow(self)


class KpiCard(Card):
    """Белая карточка с числом и сравнением с прошлым месяцем."""

    def __init__(self, title: str, value: str, delta: str, positive: bool, tint: str, glyph: str) -> None:
        super().__init__(margins=(18, 16, 18, 14), spacing=8)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        v = QLabel(value)
        v.setObjectName("kpiValue")
        t = QLabel(title)
        t.setObjectName("mutedText")
        col.addWidget(v)
        col.addWidget(t)
        top.addLayout(col, 1)
        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        icon.setStyleSheet(f"background:{tint}; border-radius:10px; font-size:14pt;")
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)

        color = theme.GREEN if positive else theme.RED
        sign = "+" if positive else "−"
        d = QLabel(f"<span style='color:{color}; font-weight:600'>{sign}{delta}</span>"
                   f" <span style='color:{theme.MUTED}'>к прошлому месяцу</span>")
        d.setStyleSheet("font-size:9pt;")
        self.body.addWidget(d)


class BarChart(QWidget):
    """Столбчатый график: закупки (светлые) и продажи (яркие) по месяцам."""

    def __init__(self, labels, purchases, sales, y_max=60) -> None:
        super().__init__()
        self.labels, self.purchases, self.sales, self.y_max = labels, purchases, sales, y_max
        self.setMinimumHeight(260)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, top, bottom = 38, 4, 6, 24
        w, h = self.width() - left - right, self.height() - top - bottom
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        p.setFont(font)

        steps = 6
        for i in range(steps + 1):
            y = top + h - h * i / steps
            p.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine))
            p.drawLine(left, int(y), left + w, int(y))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, y - 8, left - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{int(self.y_max * i / steps)}K")

        n = len(self.labels)
        slot = w / n
        bw = min(26, slot * 0.6)
        for i, name in enumerate(self.labels):
            cx = left + slot * (i + 0.5)
            for value, color in ((self.purchases[i], theme.ACCENT_SOFT), (self.sales[i], theme.ACCENT)):
                bh = h * value / self.y_max
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawRoundedRect(QRectF(cx - bw / 2, top + h - bh, bw, bh + 6), 5, 5)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(cx - slot / 2, top + h + 6, slot, 16), Qt.AlignmentFlag.AlignCenter, name)
        # закрываем скруглённые «хвосты» столбцов под осью
        p.fillRect(QRectF(left, top + h, w, 6), QColor("white"))
        p.end()
