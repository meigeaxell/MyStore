"""Кастомный выдвижной сайдбар MobileStore с векторными duotone-иконками."""

import math
from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QButtonGroup, QFrame, QPushButton, QVBoxLayout, QWidget

from app.config import APP_VERSION, BUNDLE_ROOT
from app.ui import theme

SIDEBAR_COLLAPSED_W = 72
SIDEBAR_EXPANDED_W = 248


def paint_nav_icon(
    painter: QPainter,
    rect: QRectF,
    icon_key: str,
    stroke_color: QColor,
    fill_color: QColor,
) -> None:
    """Отрисовывает выразительную векторную duotone-иконку в координатах 24×24."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    scale = min(rect.width(), rect.height()) / 24.0
    ox = rect.left() + (rect.width() - 24.0 * scale) / 2.0
    oy = rect.top() + (rect.height() - 24.0 * scale) / 2.0
    painter.translate(ox, oy)
    painter.scale(scale, scale)

    pen = QPen(stroke_color, 1.85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    if icon_key == "stock":
        # Изометрическая 3D-коробка склада
        top_face = QPainterPath()
        top_face.moveTo(12.0, 3.0)
        top_face.lineTo(20.2, 7.4)
        top_face.lineTo(12.0, 11.8)
        top_face.lineTo(3.8, 7.4)
        top_face.closeSubpath()

        left_face = QPainterPath()
        left_face.moveTo(3.8, 7.4)
        left_face.lineTo(12.0, 11.8)
        left_face.lineTo(12.0, 20.8)
        left_face.lineTo(3.8, 16.4)
        left_face.closeSubpath()

        painter.fillPath(top_face, fill_color)
        painter.fillPath(left_face, QColor(fill_color.red(), fill_color.green(), fill_color.blue(), int(fill_color.alpha() * 0.55)))

        outline = QPainterPath()
        outline.moveTo(12.0, 3.0)
        outline.lineTo(20.2, 7.4)
        outline.lineTo(20.2, 16.4)
        outline.lineTo(12.0, 20.8)
        outline.lineTo(3.8, 16.4)
        outline.lineTo(3.8, 7.4)
        outline.closeSubpath()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)

        painter.drawLine(QPointF(3.8, 7.4), QPointF(12.0, 11.8))
        painter.drawLine(QPointF(20.2, 7.4), QPointF(12.0, 11.8))
        painter.drawLine(QPointF(12.0, 11.8), QPointF(12.0, 20.8))
        # Лента упаковки на крышке
        painter.drawLine(QPointF(8.0, 5.2), QPointF(16.0, 9.5))

    elif icon_key == "purchases":
        # Входящая поставка: контейнер с акцентированной стрелкой приёмки вниз
        tray = QPainterPath()
        tray.addRoundedRect(QRectF(3.5, 11.5, 17.0, 9.0), 2.8, 2.8)
        painter.fillPath(tray, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(tray)

        # Линия крышки и стрелка входа сверху
        painter.drawLine(QPointF(7.2, 15.8), QPointF(16.8, 15.8))
        painter.drawLine(QPointF(12.0, 3.0), QPointF(12.0, 11.2))
        arrow = QPainterPath()
        arrow.moveTo(8.4, 8.0)
        arrow.lineTo(12.0, 11.6)
        arrow.lineTo(15.6, 8.0)
        painter.drawPath(arrow)

    elif icon_key == "queue":
        # Мобильный сканер / очередь приёма: рамка сканера (4 уголка) + смартфон + луч
        phone = QPainterPath()
        phone.addRoundedRect(QRectF(7.6, 5.0, 8.8, 14.0), 2.0, 2.0)
        painter.fillPath(phone, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(phone)

        # Горизонтальный луч сканирования по центру
        painter.drawLine(QPointF(5.2, 12.0), QPointF(18.8, 12.0))
        # 4 уголка рамки сканера
        corners = [
            (3.4, 3.4, 1.0, 1.0),
            (20.6, 3.4, -1.0, 1.0),
            (3.4, 20.6, 1.0, -1.0),
            (20.6, 20.6, -1.0, -1.0),
        ]
        for cx0, cy0, dx, dy in corners:
            painter.drawLine(QPointF(cx0, cy0), QPointF(cx0 + dx * 3.0, cy0))
            painter.drawLine(QPointF(cx0, cy0), QPointF(cx0, cy0 + dy * 3.0))

    elif icon_key == "sales":
        # Касса / POS-корзина: фирменная сумка-терминал с ручкой и чековой полосой
        bag = QPainterPath()
        bag.moveTo(5.0, 8.2)
        bag.lineTo(19.0, 8.2)
        bag.lineTo(19.8, 18.6)
        bag.quadTo(19.9, 20.6, 17.8, 20.6)
        bag.lineTo(6.2, 20.6)
        bag.quadTo(4.1, 20.6, 4.2, 18.6)
        bag.closeSubpath()
        painter.fillPath(bag, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bag)

        # Дуга ручки
        handle = QPainterPath()
        handle.moveTo(8.6, 8.2)
        handle.cubicTo(8.6, 3.6, 15.4, 3.6, 15.4, 8.2)
        painter.drawPath(handle)

        # Деталь кассы / чека внутри
        painter.drawLine(QPointF(9.0, 13.4), QPointF(15.0, 13.4))
        painter.drawLine(QPointF(10.5, 16.8), QPointF(13.5, 16.8))

    elif icon_key == "tradein":
        # Trade-in: две круговые стрелки обмена вокруг компактного телефона
        center_phone = QPainterPath()
        center_phone.addRoundedRect(QRectF(9.4, 7.6, 5.2, 8.8), 1.3, 1.3)
        painter.fillPath(center_phone, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(center_phone)

        # Верхняя дуга слева направо
        top_arc = QPainterPath()
        top_arc.moveTo(4.6, 9.6)
        top_arc.cubicTo(5.6, 4.2, 14.8, 2.4, 18.8, 6.2)
        painter.drawPath(top_arc)
        # Наконечник верхней стрелки
        painter.drawLine(QPointF(15.8, 6.3), QPointF(19.1, 6.4))
        painter.drawLine(QPointF(18.9, 3.2), QPointF(19.1, 6.4))

        # Нижняя дуга справа налево
        bot_arc = QPainterPath()
        bot_arc.moveTo(19.4, 14.4)
        bot_arc.cubicTo(18.4, 19.8, 9.2, 21.6, 5.2, 17.8)
        painter.drawPath(bot_arc)
        # Наконечник нижней стрелки
        painter.drawLine(QPointF(8.2, 17.7), QPointF(4.9, 17.6))
        painter.drawLine(QPointF(5.1, 20.8), QPointF(4.9, 17.6))

    elif icon_key == "finance":
        # Финансы / касса: современный кошелёк с застёжкой и картой
        wallet = QPainterPath()
        wallet.addRoundedRect(QRectF(3.4, 6.6, 17.2, 13.2), 3.0, 3.0)
        painter.fillPath(wallet, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(wallet)

        # Верхний край карты, выглядывающий из кошелька
        card_edge = QPainterPath()
        card_edge.moveTo(6.2, 6.6)
        card_edge.lineTo(15.6, 3.8)
        card_edge.quadTo(17.2, 3.4, 17.6, 5.0)
        card_edge.lineTo(18.0, 6.6)
        painter.drawPath(card_edge)

        # Застёжка справа
        clasp = QPainterPath()
        clasp.addRoundedRect(QRectF(14.8, 11.2, 5.8, 4.4), 1.6, 1.6)
        painter.fillPath(clasp, fill_color)
        painter.drawPath(clasp)
        painter.setBrush(stroke_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(17.2, 13.4), 1.05, 1.05)

    elif icon_key == "reports":
        # Аналитика и отчёты: 3 восходящих столбца + линия тренда вверх
        bars = [
            QRectF(4.0, 14.2, 3.6, 6.2),
            QRectF(10.2, 11.0, 3.6, 9.4),
            QRectF(16.4, 7.6, 3.6, 12.8),
        ]
        for b in bars:
            bp = QPainterPath()
            bp.addRoundedRect(b, 1.3, 1.3)
            painter.fillPath(bp, fill_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(bp)

        # Восходящий тренд со стрелкой
        trend = QPainterPath()
        trend.moveTo(4.2, 9.4)
        trend.lineTo(9.8, 6.2)
        trend.lineTo(13.2, 7.8)
        trend.lineTo(19.4, 3.4)
        painter.drawPath(trend)
        painter.drawLine(QPointF(16.6, 3.4), QPointF(19.6, 3.3))
        painter.drawLine(QPointF(19.4, 6.3), QPointF(19.6, 3.3))

    elif icon_key == "settings":
        # Настройки: геометрическая 8-зубчатая шестерёнка с чистым центром
        cx, cy = 12.0, 12.0
        r_outer = 9.0
        r_inner = 6.7
        teeth = 8
        gear = QPainterPath()
        steps = teeth * 4
        for idx in range(steps):
            angle = (2.0 * math.pi * idx) / steps - math.pi / 2.0
            slot = idx % 4
            r = r_outer if slot in (0, 1) else r_inner
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            if idx == 0:
                gear.moveTo(px, py)
            else:
                gear.lineTo(px, py)
        gear.closeSubpath()

        painter.fillPath(gear, fill_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(gear)
        painter.drawEllipse(QPointF(cx, cy), 3.1, 3.1)

    else:
        painter.drawRoundedRect(QRectF(5.0, 5.0, 14.0, 14.0), 3.5, 3.5)

    painter.restore()


class BrandNavButton(QPushButton):
    """Верхняя кнопка логотипа MobileStore (открывает Esasy panel),
    фиксированная по X при раскрытии сайдбара."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("brandNavButton")
        self.setProperty("title", "MobileStore")
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Esasy panel (Ctrl+1)")
        self.setFixedHeight(54)
        self._progress = 0.0
        self._hovered = False
        self._logo_pixmap = self._load_logo_pixmap(38)

    @staticmethod
    def _load_logo_pixmap(size: int) -> QPixmap | None:
        logo_svg = BUNDLE_ROOT / "resources" / "mobilestore.svg"
        logo_png = BUNDLE_ROOT / "resources" / "mobilestore.png"
        if logo_svg.exists():
            icon = QIcon(str(logo_svg))
            pm = icon.pixmap(QSize(size * 2, size * 2))
            pm.setDevicePixelRatio(2.0)
            return pm
        if logo_png.exists():
            pm = QPixmap(str(logo_png)).scaled(
                size * 2,
                size * 2,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pm.setDevicePixelRatio(2.0)
            return pm
        return None

    def set_expand_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isChecked()

        # Фон карточки бренда
        if checked:
            p.setBrush(QColor(theme.ACCENT_BG))
            p.setPen(QPen(QColor("#FDBA74"), 1.2))
            p.drawRoundedRect(rect, 11, 11)
        elif self._hovered:
            p.setBrush(QColor("#F2F4F7"))
            p.setPen(QPen(QColor(theme.BORDER), 1.0))
            p.drawRoundedRect(rect, 11, 11)

        # Фиксированная иконка логотипа по X (центрирована в 72px: margin 8 + offset 9 = 17, 17+38+17=72)
        icon_size = 38.0
        icon_x = 9.0
        icon_y = (self.height() - icon_size) / 2.0
        icon_rect = QRectF(icon_x, icon_y, icon_size, icon_size)
        if self._logo_pixmap is not None and not self._logo_pixmap.isNull():
            p.drawPixmap(icon_rect.toRect(), self._logo_pixmap)
        else:
            grad = QLinearGradient(icon_rect.topLeft(), icon_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FF9F43"))
            grad.setColorAt(1.0, QColor("#E06F14"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(icon_rect, 10, 10)
            f = QFont(self.font())
            f.setPointSizeF(13.0)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "M")

        # Название и подзаголовок (плавно проявляются при раскрытии сайдбара)
        if self._progress > 0.06:
            alpha = min(1.0, (self._progress - 0.06) / 0.72)
            p.save()
            p.setOpacity(alpha)
            text_left = icon_x + icon_size + 11.0
            text_w = max(0.0, self.width() - text_left - 8.0)

            title_font = QFont(self.font())
            title_font.setPointSizeF(12.6)
            title_font.setWeight(QFont.Weight.ExtraBold)
            p.setFont(title_font)
            p.setPen(QColor(theme.ACCENT if checked else theme.NAVY))
            p.drawText(
                QRectF(text_left, 7.0, text_w, 22.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "MobileStore",
            )

            sub_font = QFont(self.font())
            sub_font.setPointSizeF(8.1)
            sub_font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Normal)
            p.setFont(sub_font)
            p.setPen(QColor("#C2410C" if checked else theme.MUTED))
            p.drawText(
                QRectF(text_left, 28.0, text_w, 16.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "Esasy panel",
            )
            p.restore()


class NavItemButton(QPushButton):
    """Кнопка вкладки навигации с кастомной векторной duotone-иконкой,
    бейджем счётчика и фиксированной позицией иконки при слайде."""

    def __init__(
        self,
        title: str,
        icon_key: str,
        shortcut_hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._icon_key = icon_key
        self._badge_count = 0
        self._progress = 0.0
        self._hovered = False

        self.setObjectName("navButton")
        self.setProperty("title", title)
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self._update_tooltip(shortcut_hint)
        self._shortcut_hint = shortcut_hint

    def _update_tooltip(self, shortcut_hint: str) -> None:
        tip = self._title
        if self._badge_count > 0:
            tip = f"{tip} ({self._badge_count})"
        if shortcut_hint:
            tip = f"{tip}  •  {shortcut_hint}"
        self.setToolTip(tip)

    def set_badge_count(self, count: int) -> None:
        self._badge_count = max(0, int(count))
        self._update_tooltip(self._shortcut_hint)
        self.update()

    def set_expand_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect())
        checked = self.isChecked()

        # Фон строки
        if checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT_BG))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)
            # Левая акцентная полоска
            bar = QRectF(1.0, (rect.height() - 22.0) / 2.0, 3.5, 22.0)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(bar, 2.0, 2.0)
        elif self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F2F4F7"))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)

        # Плитка иконки 36×36 (центрирована в 72px: 8 + 10 = 18, 18+36+18=72)
        tile_size = 36.0
        tile_x = 10.0
        tile_y = (rect.height() - tile_size) / 2.0
        tile_rect = QRectF(tile_x, tile_y, tile_size, tile_size)

        if checked:
            grad = QLinearGradient(tile_rect.topLeft(), tile_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FF9F43"))
            grad.setColorAt(0.55, QColor(theme.ACCENT))
            grad.setColorAt(1.0, QColor("#E06F14"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(tile_rect, 9.5, 9.5)
            stroke_c = QColor("#FFFFFF")
            fill_c = QColor(255, 255, 255, 76)
        elif self._hovered:
            p.setPen(QPen(QColor("#FED7AA"), 1.0))
            p.setBrush(QColor("#FFF8F1"))
            p.drawRoundedRect(tile_rect, 9.5, 9.5)
            stroke_c = QColor(theme.NAVY)
            fill_c = QColor(245, 138, 46, 48)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F8FAFC"))
            p.drawRoundedRect(tile_rect, 9.5, 9.5)
            stroke_c = QColor("#475467")
            fill_c = QColor(203, 213, 225, 115)

        icon_inner = tile_rect.adjusted(7.0, 7.0, -7.0, -7.0)
        paint_nav_icon(p, icon_inner, self._icon_key, stroke_c, fill_c)

        # Компактный бейдж на углу иконки в свёрнутом состоянии
        if self._badge_count > 0 and self._progress < 0.45:
            badge_alpha = 1.0 - (self._progress / 0.45)
            p.save()
            p.setOpacity(badge_alpha)
            b_txt = "99+" if self._badge_count > 99 else str(self._badge_count)
            bf = QFont(self.font())
            bf.setPointSizeF(7.2)
            bf.setBold(True)
            bfm = QFontMetrics(bf)
            bw = max(16.0, bfm.horizontalAdvance(b_txt) + 8.0)
            bh = 15.0
            brect = QRectF(tile_rect.right() - bw + 4.0, tile_rect.top() - 2.0, bw, bh)
            p.setPen(QPen(QColor("#FFFFFF"), 1.5))
            p.setBrush(QColor(theme.RED))
            p.drawRoundedRect(brect, bh / 2.0, bh / 2.0)
            p.setFont(bf)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(brect, Qt.AlignmentFlag.AlignCenter, b_txt)
            p.restore()

        # Текст вкладки + раскрытый бейдж
        if self._progress > 0.08:
            text_alpha = min(1.0, (self._progress - 0.08) / 0.68)
            p.save()
            p.setOpacity(text_alpha)

            text_left = tile_rect.right() + 11.0
            text_right = rect.right() - 10.0

            if self._badge_count > 0:
                b_txt = "99+" if self._badge_count > 99 else str(self._badge_count)
                bf = QFont(self.font())
                bf.setPointSizeF(8.0)
                bf.setBold(True)
                bfm = QFontMetrics(bf)
                bw = max(22.0, bfm.horizontalAdvance(b_txt) + 12.0)
                bh = 20.0
                brect = QRectF(text_right - bw, (rect.height() - bh) / 2.0, bw, bh)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT if checked else theme.RED))
                p.drawRoundedRect(brect, bh / 2.0, bh / 2.0)
                p.setFont(bf)
                p.setPen(QColor("#FFFFFF"))
                p.drawText(brect, Qt.AlignmentFlag.AlignCenter, b_txt)
                text_right = brect.left() - 6.0
            elif self._shortcut_hint and self._progress > 0.45:
                hint_alpha = min(1.0, (self._progress - 0.45) / 0.45) * text_alpha
                p.save()
                p.setOpacity(hint_alpha)
                hf = QFont(self.font())
                hf.setPointSizeF(7.6)
                hf.setWeight(QFont.Weight.Medium)
                hfm = QFontMetrics(hf)
                hw = hfm.horizontalAdvance(self._shortcut_hint) + 4.0
                hrect = QRectF(text_right - hw, 0.0, hw, rect.height())
                p.setFont(hf)
                p.setPen(QColor(theme.FAINT))
                p.drawText(
                    hrect,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    self._shortcut_hint,
                )
                p.restore()
                text_right = hrect.left() - 6.0

            lbl_font = QFont(self.font())
            lbl_font.setPointSizeF(9.6)
            lbl_font.setWeight(QFont.Weight.Bold if checked else QFont.Weight.DemiBold if self._hovered else QFont.Weight.Medium)
            p.setFont(lbl_font)
            p.setPen(QColor("#C2410C" if checked else theme.NAVY if self._hovered else "#344054"))
            lbl_w = max(0.0, text_right - text_left)
            lbl_fm = QFontMetrics(lbl_font)
            elided = lbl_fm.elidedText(self._title, Qt.TextElideMode.ElideRight, int(lbl_w))
            p.drawText(
                QRectF(text_left, 0.0, lbl_w, rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )
            p.restore()


class NavSectionHeader(QWidget):
    """Заголовок секции: тонкая линия-разделитель в свёрнутом виде,
    аккуратный заголовок в раскрытом."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title.upper()
        self._progress = 0.0
        self.setFixedHeight(24)

    def set_expand_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mid_y = self.height() / 2.0 + 2.0

        # Разделитель в свёрнутом виде
        if self._progress < 0.7:
            line_alpha = max(0.0, 1.0 - self._progress / 0.6)
            p.save()
            p.setOpacity(line_alpha)
            p.setPen(QPen(QColor("#E4E7EC"), 1.2))
            p.drawLine(QPointF(16.0, mid_y), QPointF(40.0, mid_y))
            p.restore()

        # Заголовок секции в раскрытом виде
        if self._progress > 0.15:
            txt_alpha = min(1.0, (self._progress - 0.15) / 0.65)
            p.save()
            p.setOpacity(txt_alpha)
            f = QFont(self.font())
            f.setPointSizeF(7.6)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.7)
            p.setFont(f)
            p.setPen(QColor("#98A2B3"))
            p.drawText(
                QRectF(12.0, 4.0, max(0.0, self.width() - 20.0), self.height() - 4.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._title,
            )
            p.restore()


class _SidebarModeButton(QPushButton):
    """Компактная кнопка переключения режима сайдбара: hover → expanded → collapsed."""

    _LABELS: ClassVar[dict[str, str]] = {
        "hover": "Menýu: Hover",
        "expanded": "Menýu: Berkidilen",
        "collapsed": "Menýu: Ýapyk",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = "hover"
        self._progress = 0.0
        self._hovered = False
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(32)
        self._sync_tooltip()

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in self._LABELS else "hover"
        self._sync_tooltip()
        self.update()

    def _sync_tooltip(self) -> None:
        cur = self._LABELS.get(self._mode, self._LABELS["hover"])
        self.setToolTip(f"{cur}\nÜýtgetmek üçin basyň (Hover → Berkidilen → Ýapyk)")

    def set_expand_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        active_bg = self._mode != "hover"
        if self._hovered:
            p.setPen(QPen(QColor("#CBD5E1"), 1.0))
            p.setBrush(QColor("#F2F4F7"))
            p.drawRoundedRect(rect, 8, 8)
        elif active_bg:
            p.setPen(QPen(QColor("#E2E8F0"), 1.0))
            p.setBrush(QColor("#F8FAFC"))
            p.drawRoundedRect(rect, 8, 8)

        # Компактная иконка панели слева (выровнена по центру 72px)
        ix = 18.0
        iy = (self.height() - 16.0) / 2.0
        stroke = QColor(theme.ACCENT if active_bg else "#667085")
        p.setPen(QPen(stroke, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(ix, iy, 18.0, 14.0), 2.8, 2.8)
        div_x = ix + (7.5 if self._mode == "expanded" else 5.0)
        p.drawLine(QPointF(div_x, iy + 0.8), QPointF(div_x, iy + 13.2))
        if self._mode == "expanded":
            p.fillRect(QRectF(ix + 1.0, iy + 1.0, 6.0, 12.0), QColor(245, 138, 46, 70))
        elif self._mode == "collapsed":
            p.drawLine(QPointF(ix + 10.5, iy + 7.0), QPointF(ix + 14.5, iy + 7.0))

        if self._progress > 0.15:
            alpha = min(1.0, (self._progress - 0.15) / 0.65)
            p.save()
            p.setOpacity(alpha)
            f = QFont(self.font())
            f.setPointSizeF(8.3)
            f.setWeight(QFont.Weight.DemiBold if active_bg else QFont.Weight.Medium)
            p.setFont(f)
            p.setPen(QColor(theme.NAVY if active_bg else "#667085"))
            text_left = ix + 28.0
            p.drawText(
                QRectF(text_left, 0.0, max(0.0, self.width() - text_left - 8.0), self.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._LABELS.get(self._mode, "Menýu"),
            )
            p.restore()


class _SidebarVersionFooter(QWidget):
    """Компактный нижний индикатор версии."""

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._version = version
        self._progress = 0.0
        self.setFixedHeight(22)

    def set_expand_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(self.font())
        f.setPointSizeF(8.0)
        f.setWeight(QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(QColor("#98A2B3"))
        if self._progress < 0.35:
            p.drawText(
                QRectF(0.0, 0.0, self.width(), self.height()),
                Qt.AlignmentFlag.AlignCenter,
                f"v{self._version}",
            )
        else:
            p.setOpacity(min(1.0, (self._progress - 0.2) / 0.6))
            p.drawText(
                QRectF(12.0, 0.0, max(0.0, self.width() - 20.0), self.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"MobileStore  •  v{self._version}",
            )


class _SidebarShadowStrip(QWidget):
    """Лёгкая градиентная тень справа от выдвинутого сайдбара (не перехватывает мышь)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._intensity = 0.0
        self.setFixedWidth(16)

    def set_intensity(self, value: float) -> None:
        self._intensity = max(0.0, min(1.0, value))
        self.setVisible(self._intensity > 0.02)
        self.update()

    def paintEvent(self, _event) -> None:
        if self._intensity <= 0.02:
            return
        p = QPainter(self)
        grad = QLinearGradient(0.0, 0.0, float(self.width()), 0.0)
        grad.setColorAt(0.0, QColor(15, 23, 42, int(36 * self._intensity)))
        grad.setColorAt(0.45, QColor(15, 23, 42, int(14 * self._intensity)))
        grad.setColorAt(1.0, QColor(15, 23, 42, 0))
        p.fillRect(self.rect(), QBrush(grad))


class SlidingSidebar(QFrame):
    """Левый сайдбар с 3 режимами:
    - hover: 72px в покое, при наведении плавно раскрывается поверх контента до 248px;
    - expanded: всегда закреплён раскрытым (248px);
    - collapsed: всегда компактный (72px, без раскрытия при наведении).
    """

    modeChanged = Signal(str)

    def __init__(
        self,
        sections: list[tuple[str, list[tuple[str, str]]]],
        bottom_item: tuple[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._collapsed_w = SIDEBAR_COLLAPSED_W
        self._expanded_w = SIDEBAR_EXPANDED_W
        self._drawer_width = self._collapsed_w
        self._is_expanded = False
        self._mode = "hover"

        self._shadow_strip = _SidebarShadowStrip(parent)
        self._shadow_strip.hide()

        self._anim = QPropertyAnimation(self, b"drawerWidth", self)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._do_collapse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 10)
        layout.setSpacing(3)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.nav_buttons: list[QPushButton] = []
        self._animatables: list[QWidget] = []

        # 1. Верхняя кнопка бренда -> Esasy panel
        self.brand_btn = BrandNavButton(self)
        self.button_group.addButton(self.brand_btn)
        layout.addWidget(self.brand_btn)
        layout.addSpacing(4)
        self.nav_buttons.append(self.brand_btn)
        self._animatables.append(self.brand_btn)

        # 2. Основные секции навигации
        shortcut_num = 2
        for section_title, items in sections:
            hdr = NavSectionHeader(section_title, self)
            layout.addWidget(hdr)
            self._animatables.append(hdr)

            for name, icon_key in items:
                hint = f"Ctrl+{shortcut_num}" if shortcut_num <= 9 else ""
                shortcut_num += 1
                btn = NavItemButton(name, icon_key, shortcut_hint=hint, parent=self)
                self.button_group.addButton(btn)
                layout.addWidget(btn)
                self.nav_buttons.append(btn)
                self._animatables.append(btn)

        # 3. Пружина -> «Sazlamalar» всегда в самом низу
        layout.addStretch(1)

        bottom_divider = QFrame(self)
        bottom_divider.setFixedHeight(1)
        bottom_divider.setStyleSheet(f"background: {theme.BORDER}; border: none;")
        layout.addWidget(bottom_divider)
        layout.addSpacing(4)

        b_name, b_icon = bottom_item
        b_hint = f"Ctrl+{shortcut_num}" if shortcut_num <= 9 else ""
        self.settings_btn = NavItemButton(b_name, b_icon, shortcut_hint=b_hint, parent=self)
        self.button_group.addButton(self.settings_btn)
        layout.addWidget(self.settings_btn)
        self.nav_buttons.append(self.settings_btn)
        self._animatables.append(self.settings_btn)

        layout.addSpacing(4)
        self.mode_btn = _SidebarModeButton(self)
        self.mode_btn.clicked.connect(self._cycle_mode)
        layout.addWidget(self.mode_btn)
        self._animatables.append(self.mode_btn)

        layout.addSpacing(2)
        self._footer = _SidebarVersionFooter(APP_VERSION, self)
        layout.addWidget(self._footer)
        self._animatables.append(self._footer)

        self.setFixedWidth(self._collapsed_w)
        self._sync_progress()

    def _cycle_mode(self) -> None:
        order = ("hover", "expanded", "collapsed")
        idx = order.index(self._mode) if self._mode in order else 0
        next_mode = order[(idx + 1) % len(order)]
        self.set_mode(next_mode)
        self.modeChanged.emit(next_mode)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        clean = mode if mode in ("hover", "expanded", "collapsed") else "hover"
        self._mode = clean
        self.mode_btn.set_mode(clean)
        if clean == "expanded":
            self.set_expanded_immediate(True)
        else:
            self.set_expanded_immediate(False)

    def _get_drawer_width(self) -> int:
        return self._drawer_width

    def _set_drawer_width(self, value: int) -> None:
        w = max(self._collapsed_w, min(self._expanded_w, int(value)))
        self._drawer_width = w
        self.setFixedWidth(w)
        self.sync_geometry()
        self._sync_progress()

    drawerWidth = Property(int, _get_drawer_width, _set_drawer_width)

    def _sync_progress(self) -> None:
        span = max(1, self._expanded_w - self._collapsed_w)
        progress = (self._drawer_width - self._collapsed_w) / span
        for w in self._animatables:
            if hasattr(w, "set_expand_progress"):
                w.set_expand_progress(progress)
        self._shadow_strip.set_intensity(progress if self._mode == "hover" else 0.0)

    def sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        h = parent.height()
        self.setGeometry(0, 0, self._drawer_width, h)
        self._shadow_strip.setGeometry(self._drawer_width, 0, self._shadow_strip.width(), h)
        if self.isVisible():
            self._shadow_strip.raise_()
            self.raise_()

    def expand(self) -> None:
        self._collapse_timer.stop()
        if self._is_expanded and self._drawer_width == self._expanded_w:
            return
        self._is_expanded = True
        self._anim.stop()
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._drawer_width)
        self._anim.setEndValue(self._expanded_w)
        self._anim.start()

    def collapse(self) -> None:
        self._collapse_timer.start(130)

    def _do_collapse(self) -> None:
        if self.underMouse():
            return
        self._is_expanded = False
        self._anim.stop()
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.setStartValue(self._drawer_width)
        self._anim.setEndValue(self._collapsed_w)
        self._anim.start()

    def set_expanded_immediate(self, expanded: bool) -> None:
        self._collapse_timer.stop()
        self._anim.stop()
        self._is_expanded = bool(expanded)
        self._set_drawer_width(self._expanded_w if expanded else self._collapsed_w)

    def enterEvent(self, event) -> None:
        if self._mode == "hover":
            self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._mode == "hover":
            self.collapse()
        super().leaveEvent(event)
