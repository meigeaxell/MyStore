"""Единый реестр векторных иконок MobileStore (замена эмодзи в кнопках, вкладках, уведомлениях).

Стиль как в сайдбаре: сетка 24×24, обводка 1.85 со скруглёнными концами.
Ключи навигации (stock, sales, ...) делегируются в `sidebar.paint_nav_icon`.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from app.ui import theme
from app.ui.sidebar import paint_nav_icon

NAV_KEYS = {"stock", "purchases", "queue", "sales", "tradein", "finance", "reports", "settings"}


def _p(*pts: tuple[float, float]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*pts[0])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    return path


def _rr(x: float, y: float, w: float, h: float, r: float = 2.0) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _arc_arrow(flip: bool = False) -> list[QPainterPath]:
    arc = QPainterPath()
    arc.moveTo(19.0, 12.0)
    arc.arcTo(QRectF(5.0, 5.0, 14.0, 14.0), 0, 270)
    head = _p((3.0, 9.0), (6.0, 12.5), (9.0, 9.5))
    return [arc, head]


# Каждая иконка — список контуров (только обводка) в координатах 24×24.
_SHAPES: dict[str, list[QPainterPath]] = {
    "plus": [_p((12, 5), (12, 19)), _p((5, 12), (19, 12))],
    "check": [_p((5, 12.5), (10, 17.5), (19, 7))],
    "close": [_p((6, 6), (18, 18)), _p((18, 6), (6, 18))],
    "info": [_circle(12, 12, 8.5), _p((12, 11), (12, 16.5)), _p((12, 7.8), (12, 8.0))],
    "warning": [_p((12, 3.8), (21, 19.5), (3, 19.5), (12, 3.8)), _p((12, 10), (12, 14.5)), _p((12, 17), (12, 17.2))],
    "edit": [_p((4, 20), (4.8, 16), (16, 4.8), (19.2, 8), (8, 19.2), (4, 20)), _p((14, 7), (17, 10))],
    "trash": [_p((4.5, 7), (19.5, 7)), _p((9, 7), (9, 4.5), (15, 4.5), (15, 7)),
              _p((6.5, 7), (7.5, 20), (16.5, 20), (17.5, 7)), _p((10, 11), (10, 16)), _p((14, 11), (14, 16))],
    "print": [_rr(7, 3.5, 10, 5), _rr(3.5, 8.5, 17, 8, 2.5), _rr(7, 14, 10, 6.5, 1.2)],
    "search": [_circle(10.5, 10.5, 6), _p((15, 15), (20, 20))],
    "phone": [_rr(7, 3, 10, 18, 2.2), _p((10.5, 18), (13.5, 18))],
    "pause": [_rr(6.5, 5, 3.6, 14, 1.2), _rr(13.9, 5, 3.6, 14, 1.2)],
    "folder": [_p((3.5, 7), (3.5, 19), (20.5, 19), (20.5, 8.5), (11, 8.5), (9.5, 6), (3.5, 6), (3.5, 7))],
    "calc": [_rr(5, 3.5, 14, 17, 2.2), _rr(8, 6.5, 8, 3.5, 0.8), _p((8.5, 14), (8.6, 14)), _p((12, 14), (12.1, 14)),
             _p((15.5, 14), (15.6, 14)), _p((8.5, 17.2), (8.6, 17.2)), _p((12, 17.2), (12.1, 17.2)),
             _p((15.5, 17.2), (15.6, 17.2))],
    "lock": [_rr(5, 10.5, 14, 10, 2.4), _p((8, 10.5), (8, 7.5)), _p((16, 10.5), (16, 7.5)),
             _p((8, 7.5), (8.6, 5), (12, 3.6), (15.4, 5), (16, 7.5)), _p((12, 14.5), (12, 17))],
    "refresh": _arc_arrow(),
    "history": [_circle(12, 12, 8.5), _p((12, 7), (12, 12), (15.5, 14))],
    "price": [_p((3.5, 12), (12, 3.5), (20, 3.5), (20, 11.5), (11.5, 20), (3.5, 12)), _p((15.5, 8.5), (15.6, 8.5))],
    "qty": [_p((9, 4), (7.5, 20)), _p((16.5, 4), (15, 20)), _p((4.5, 9), (19.5, 9)), _p((4, 15), (19, 15))],
    "bolt": [_p((13.5, 3), (5.5, 13.5), (11.5, 13.5), (10.5, 21), (18.5, 10.2), (12.5, 10.2), (13.5, 3))],
    "repeat": [_p((4.5, 11), (4.5, 8.5), (7, 6), (18, 6)), _p((15, 3), (18.2, 6), (15, 9)),
               _p((19.5, 13), (19.5, 15.5), (17, 18), (6, 18)), _p((9, 15), (5.8, 18), (9, 21))],
    "archive": [_rr(3.5, 4.5, 17, 4.5, 1.2), _p((5, 9), (5, 19.5), (19, 19.5), (19, 9)), _p((10, 13), (14, 13))],
    "restore": [_p((9, 6), (4.5, 10.5), (9, 15)), _p((4.5, 10.5), (14, 10.5), (19.5, 13.5), (19.5, 16.5), (16.5, 19.5), (10, 19.5))],
    "cash": [_rr(3, 6.5, 18, 11, 2), _circle(12, 12, 2.8), _p((6.5, 12), (6.6, 12)), _p((17.4, 12), (17.5, 12))],
    "scale": [_p((12, 4), (12, 20)), _p((7, 20), (17, 20)), _p((4.5, 7.5), (19.5, 7.5)),
              _p((4.5, 7.5), (2.5, 13), (6.5, 13), (4.5, 7.5)), _p((19.5, 7.5), (17.5, 13), (21.5, 13), (19.5, 7.5))],
    "bank": [_p((3.5, 9), (12, 4), (20.5, 9), (3.5, 9)), _p((6, 11), (6, 17)), _p((10, 11), (10, 17)),
             _p((14, 11), (14, 17)), _p((18, 11), (18, 17)), _p((4, 19.5), (20, 19.5))],
    "export": [_p((12, 15), (12, 4)), _p((8, 8), (12, 4), (16, 8)), _p((5, 14), (5, 19.5), (19, 19.5), (19, 14))],
    "copy": [_rr(8.5, 8.5, 11.5, 11.5, 2.2), _p((15.5, 8.5), (15.5, 6), (13.5, 4), (6, 4), (4, 6), (4, 13.5), (6, 15.5), (8.5, 15.5))],
    "list": [_p((9, 7), (19.5, 7)), _p((9, 12), (19.5, 12)), _p((9, 17), (19.5, 17)),
             _p((4.5, 7), (4.6, 7)), _p((4.5, 12), (4.6, 12)), _p((4.5, 17), (4.6, 17))],
}


def has_icon(icon_key: str) -> bool:
    return icon_key in _SHAPES or icon_key in NAV_KEYS


def make_icon(icon_key: str, color: str = theme.NAVY, size: int = 18) -> QIcon:
    """Векторная иконка (рендер в pixmap ×2 для чёткости на HiDPI)."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(0, 0, size, size)
    qcolor = QColor(color)
    if icon_key in NAV_KEYS:
        fill = QColor(qcolor.red(), qcolor.green(), qcolor.blue(), 50)
        paint_nav_icon(p, rect, icon_key, qcolor, fill)
    else:
        k = size / 24.0
        p.scale(k, k)
        pen = QPen(qcolor, 1.85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for path in _SHAPES.get(icon_key, []):
            p.drawPath(path)
    p.end()
    return QIcon(pm)


def icon_size(size: int = 18) -> QSize:
    return QSize(size, size)
