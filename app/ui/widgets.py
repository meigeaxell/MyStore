"""Переиспользуемые виджеты: карточки, таблицы, кнопки, списки и график."""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui import theme


def money_str(value) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "0.00"


def make_button(text: str, variant: str = "secondary") -> QPushButton:
    """Создаёт кнопку в едином стиле дизайн-системы MobileStore.

    variant: 'primary' | 'secondary' | 'danger' | 'dark' | 'success' | 'link'
    По умолчанию autoDefault=False, чтобы Enter в диалогах срабатывал строго на главной кнопке.
    """
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    obj_map = {
        "primary": "primaryBtn",
        "secondary": "secondaryBtn",
        "danger": "dangerBtn",
        "dark": "darkBtn",
        "success": "successBtn",
        "link": "linkBtn",
    }
    if variant in obj_map:
        btn.setObjectName(obj_map[variant])
    return btn


def configure_dialog_buttons(
    dialog: QDialog,
    primary_btn: QPushButton | None = None,
    cancel_btn: QPushButton | None = None,
) -> None:
    """Настраивает клавиатурное поведение диалога:

    - Снимает autoDefault/default со всех второстепенных кнопок.
    - Назначает единственной default-кнопкой главную цветную кнопку (primary_btn).
    - Привязывает Ctrl+Enter / Ctrl+Return к primary_btn (работает даже из QTextEdit и полей поиска).
    - Привязывает Esc к отмене (cancel_btn или dialog.reject).
    """
    for btn in dialog.findChildren(QPushButton):
        btn.setAutoDefault(False)
        btn.setDefault(False)

    if primary_btn is not None:
        primary_btn.setAutoDefault(True)
        primary_btn.setDefault(True)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(seq), dialog)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(
                lambda b=primary_btn: b.click() if b.isEnabled() and b.isVisible() else None
            )

    if cancel_btn is not None:
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)


class ToastNotification(QFrame):
    """Неблокирующее всплывающее уведомление с автоисчезновением."""

    _active_toast: "ToastNotification | None" = None

    def __init__(
        self,
        parent: QWidget,
        message: str,
        kind: str = "success",
        duration_ms: int = 2800,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toastNotification")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        palettes = {
            "success": ("#15803D", "#ECFDF3", "#BBF7D0", "✔"),
            "info": (theme.NAVY, "#EFF6FF", "#BFDBFE", "ℹ"),
            "warning": ("#B45309", "#FFFBEB", "#FDE68A", "⚠"),
            "error": (theme.RED, "#FEF2F2", "#FECACA", "✕"),
        }
        fg, bg, border, icon = palettes.get(kind, palettes["info"])

        self.setStyleSheet(
            f"QFrame#toastNotification {{ background: {bg}; border: 1.5px solid {border}; "
            f"border-radius: 10px; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {fg}; font-size: 12pt; font-weight: 800; background: transparent;")
        row.addWidget(icon_lbl)

        text_lbl = QLabel(message)
        text_lbl.setWordWrap(True)
        text_lbl.setMaximumWidth(380)
        text_lbl.setStyleSheet(f"color: {fg}; font-size: 9.8pt; font-weight: 600; background: transparent;")
        row.addWidget(text_lbl, 1)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._duration_ms = max(1200, int(duration_ms))

    def mousePressEvent(self, event) -> None:
        self._timer.stop()
        self.close()
        super().mousePressEvent(event)

    def show_animated(self) -> None:
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            pw = parent.width()
            x = max(16, pw - self.width() - 24)
            y = 18
            self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start(self._duration_ms)

    def _fade_out(self) -> None:
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(260)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self.close)
        self._fade_anim = anim
        anim.start()


def show_toast(
    parent: QWidget | None,
    message: str,
    kind: str = "success",
    duration_ms: int = 2800,
) -> ToastNotification | None:
    """Показывает аккуратное всплывающее уведомление без блокировки экрана."""
    host = parent.window() if parent is not None else QApplication.activeWindow()
    if host is None:
        return None
    prev = ToastNotification._active_toast
    if prev is not None:
        try:
            prev.close()
        except RuntimeError:
            pass
    toast = ToastNotification(host, message, kind=kind, duration_ms=duration_ms)
    ToastNotification._active_toast = toast
    toast.show_animated()
    return toast


def style_combo(combo: QComboBox) -> QComboBox:
    """Настраивает всплывающий список QComboBox со светлой палитрой и удобной высотой строк."""
    view = QListView(combo)
    view.setSpacing(1)
    combo.setView(view)
    container = view.window()
    container.setAutoFillBackground(True)
    pal = container.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Base, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Text, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(theme.TEXT))
    container.setPalette(pal)
    view.setPalette(pal)
    return combo


def configure_table(
    table: QTableWidget,
    stretch_col: int | list[int] | None = None,
    row_height: int = 46,
) -> None:
    """Применяет единые настройки и поведение таблицы MobileStore."""
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    header = table.horizontalHeader()
    if stretch_col is not None:
        header.setStretchLastSection(False)
        cols = [stretch_col] if isinstance(stretch_col, int) else stretch_col
        for col in cols:
            if 0 <= col < table.columnCount():
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.customContextMenuRequested.connect(
        lambda pos, tbl=table: _show_header_column_menu(tbl, pos)
    )


def _show_header_column_menu(table: QTableWidget, pos) -> None:
    """Контекстное меню заголовка таблицы для включения/скрытия колонок."""
    menu = QMenu(table)
    visible_cnt = sum(not table.isColumnHidden(c) for c in range(table.columnCount()))
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        title = (item.text() if item else "").strip() or f"Sütün {col + 1}"
        action = menu.addAction(title)
        action.setCheckable(True)
        is_vis = not table.isColumnHidden(col)
        action.setChecked(is_vis)
        if is_vis and visible_cnt <= 1:
            action.setEnabled(False)
        action.toggled.connect(
            lambda checked, c=col, t=table: t.setColumnHidden(c, not checked)
        )
    menu.exec(table.horizontalHeader().mapToGlobal(pos))


def make_stat_card(
    title: str,
    value_label: QLabel,
    color: str,
    subtitle: str = "",
    small_value: bool = False,
) -> "Card":
    """Создаёт компактную карточку показателя со значением и подписью."""
    card = Card(margins=(16, 12, 16, 12), spacing=4)
    title_lbl = QLabel(title)
    title_lbl.setObjectName("mutedText")
    font_size = "13.5pt" if small_value else "19pt"
    value_label.setStyleSheet(f"color: {color}; font-size: {font_size}; font-weight: 700;")
    card.body.addWidget(title_lbl)
    card.body.addWidget(value_label)
    if subtitle:
        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.5pt;")
        card.body.addWidget(sub_lbl)
    return card


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


class ClickableCard(Card):
    """Интерактивная карточка, реагирующая на клик и наведение (например, «Çykdajylar» или «Simurg»)."""

    clicked = Signal()

    def __init__(self, margins=(16, 12, 16, 12), spacing=4) -> None:
        super().__init__(margins=margins, spacing=spacing)
        self.setObjectName("clickableCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


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
                   f" <span style='color:{theme.MUTED}'>• häzirki görkeziji</span>")
        d.setStyleSheet("font-size:9pt;")
        self.body.addWidget(d)


class BarChart(QWidget):
    """Столбчатый график с всплывающим окном продаж и прибыли сверху при наведении на столбец."""

    def __init__(
        self,
        labels: list[str],
        purchases: list[float],
        sales: list[float],
        y_max: float = 60,
        buckets_meta: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self.labels = labels
        self.purchases = purchases
        self.sales = sales
        self.y_max = max(float(y_max or 1), 1.0)
        self.buckets_meta = buckets_meta or []
        self._hovered_index = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(305)

    def _chart_geometry(self) -> tuple[int, int, int, int, int, int]:
        left, right, top, bottom = 52, 10, 74, 26
        w = max(10, self.width() - left - right)
        h = max(10, self.height() - top - bottom)
        return left, right, top, bottom, w, h

    @staticmethod
    def _format_axis_val(val: float) -> str:
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"{val / 1_000:.1f}K".replace(".0K", "K")
        return f"{round(val)}"

    def mouseMoveEvent(self, event) -> None:
        left, _right, top, _bottom, w, h = self._chart_geometry()
        pos = event.position()
        n = len(self.labels)
        new_hover = -1
        if n > 0 and left <= pos.x() <= left + w and 0 <= pos.y() <= top + h + 24:
            slot = w / n
            idx = int((pos.x() - left) / slot)
            if 0 <= idx < n:
                new_hover = idx
        if new_hover != self._hovered_index:
            self._hovered_index = new_hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if new_hover >= 0
                else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_index != -1:
            self._hovered_index = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, _right, top, _bottom, w, h = self._chart_geometry()
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        p.setFont(font)

        steps = 5
        for i in range(steps + 1):
            y = top + h - h * i / steps
            p.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine))
            p.drawLine(left, int(y), left + w, int(y))
            p.setPen(QColor(theme.MUTED))
            axis_label = self._format_axis_val(self.y_max * i / steps)
            p.drawText(
                QRectF(0, y - 8, left - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                axis_label,
            )

        n = len(self.labels)
        if n == 0:
            p.end()
            return

        slot = w / n
        bw = max(6.0, min(26.0, slot * 0.58))
        label_step = 1 if n <= 14 else (2 if n <= 24 else 3)

        for i, name in enumerate(self.labels):
            cx = left + slot * (i + 0.5)
            is_hovered = i == self._hovered_index

            if is_hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(245, 138, 46, 26))
                p.drawRoundedRect(QRectF(cx - slot / 2 + 2, top, slot - 4, h), 6, 6)

            for value, color, is_sales in (
                (self.purchases[i], theme.ACCENT_SOFT, False),
                (self.sales[i], theme.ACCENT, True),
            ):
                bh = min(h, max(0.0, h * float(value) / self.y_max))
                if bh <= 0 and not is_hovered:
                    continue
                draw_h = max(3.0, bh) if value > 0 else 0.0
                if draw_h <= 0:
                    continue
                rect = QRectF(cx - bw / 2, top + h - draw_h, bw, draw_h + 6)
                if is_hovered and is_sales:
                    p.setPen(QPen(QColor(theme.NAVY), 1.5))
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawRoundedRect(rect, 5, 5)

            if i % label_step == 0 or i == n - 1 or is_hovered:
                lbl_font = QFont(font)
                lbl_font.setBold(is_hovered)
                p.setFont(lbl_font)
                p.setPen(QColor(theme.NAVY if is_hovered else theme.MUTED))
                p.drawText(
                    QRectF(cx - max(slot, 36) / 2, top + h + 6, max(slot, 36), 16),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )
                p.setFont(font)

        # закрываем скруглённые «хвосты» столбцов под осью
        p.fillRect(QRectF(left, top + h, w, 6), QColor("white"))

        # Всплывающее окно сверху диаграммы при наведении на столбец
        if 0 <= self._hovered_index < n:
            self._draw_hover_popup(p, left, w, slot, self._hovered_index)
        else:
            hint_font = QFont(font)
            hint_font.setPointSizeF(8.5)
            p.setFont(hint_font)
            p.setPen(QColor(theme.MUTED))
            p.drawText(
                QRectF(left, 6, w, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "Satyşy we peýdany görmek üçin sütüniň üstüne syçanjygy eltiň",
            )

        p.end()

    def _draw_hover_popup(
        self,
        p: QPainter,
        left: int,
        w: int,
        slot: float,
        idx: int,
    ) -> None:
        meta = (
            self.buckets_meta[idx]
            if idx < len(self.buckets_meta)
            else {
                "title": self.labels[idx],
                "sales_usd": Decimal("0.00"),
                "sales_tmt": Decimal(str(self.sales[idx])),
                "profit_usd": Decimal("0.00"),
                "profit_tmt": Decimal("0.00"),
                "purchases_usd": Decimal("0.00"),
                "purchases_tmt": Decimal(str(self.purchases[idx])),
                "receipts_count": 0,
            }
        )

        title_line = f"{meta['title']}  •  Çekler: {meta.get('receipts_count', 0)}"
        sales_line = (
            f"Satyş: ${money_str(meta['sales_usd'])} USD  |  {money_str(meta['sales_tmt'])} TMT"
        )
        profit_line = (
            f"Peýda (girdeji): ${money_str(meta['profit_usd'])} USD  |  {money_str(meta['profit_tmt'])} TMT"
        )

        popup_w = min(float(w), 390.0)
        popup_h = 62.0
        cx = left + slot * (idx + 0.5)
        px = max(float(left), min(cx - popup_w / 2, float(left + w) - popup_w))
        py = 4.0

        box_rect = QRectF(px, py, popup_w, popup_h)
        p.setPen(QPen(QColor(theme.ACCENT), 1.4))
        p.setBrush(QColor(theme.NAVY))
        p.drawRoundedRect(box_rect, 9, 9)

        head_font = QFont(self.font())
        head_font.setPointSizeF(8.8)
        head_font.setBold(True)
        p.setFont(head_font)
        p.setPen(QColor("#FFE6CC"))
        p.drawText(
            QRectF(px + 12, py + 5, popup_w - 24, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_line,
        )

        body_font = QFont(self.font())
        body_font.setPointSizeF(8.4)
        body_font.setBold(False)
        p.setFont(body_font)

        p.setPen(QColor("#FFFFFF"))
        p.drawText(
            QRectF(px + 12, py + 23, popup_w - 24, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            sales_line,
        )

        p.setPen(QColor("#6EE7B7"))
        p.drawText(
            QRectF(px + 12, py + 40, popup_w - 24, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            profit_line,
        )
