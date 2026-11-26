"""Переиспользуемые виджеты: карточки, таблицы, кнопки, списки и график."""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
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
            "success": (theme.WHITE, theme.ACCENT, "#E57C20", "✔"),
            "info": (theme.WHITE, theme.ACCENT, "#E57C20", "ℹ"),
            "warning": (theme.WHITE, "#D97706", "#B45309", "⚠"),
            "error": (theme.WHITE, theme.RED, "#C81E1E", "✕"),
        }
        fg, bg, border, icon = palettes.get(kind, palettes["info"])

        self.setStyleSheet(
            f"QFrame#toastNotification {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 10px; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 18, 8)
        row.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {fg}; font-size: 11pt; font-weight: 800; background: transparent;")
        row.addWidget(icon_lbl)

        text_lbl = QLabel(message)
        text_lbl.setWordWrap(True)
        text_lbl.setMaximumWidth(460)
        text_lbl.setStyleSheet(f"color: {fg}; font-size: 9.5pt; font-weight: 600; background: transparent;")
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
            # Центрируем по рабочей области (с учётом сайдбара, если это MainWindow)
            x = max(16, (pw - self.width()) // 2)
            y = 12
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
    """Настраивает всплывающий список QComboBox со строго непрозрачным белым фоном без наезда строк."""
    view = QListView(combo)
    view.setUniformItemSizes(True)
    view.setSpacing(0)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setAutoFillBackground(True)
    combo.setView(view)

    container = view.window()
    container.setAutoFillBackground(True)
    container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    container.setStyleSheet(
        f"background-color: {theme.WHITE}; border: 1px solid #D0D5DD;"
    )

    pal = view.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Base, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.WHITE))
    pal.setColor(QPalette.ColorRole.Text, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(theme.TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(theme.ACCENT_SOFT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.NAVY))
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


def shadow(widget: QWidget, blur: int = 18, y: int = 2, alpha: int = 18) -> None:
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, y)
    fx.setColor(QColor(16, 24, 40, alpha))
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
    """Яркая карточка-показатель (верхний ряд), опционально кликабельная."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str,
        delta: str,
        positive: bool,
        color: str,
        glyph: str,
        clickable: bool = False,
    ) -> None:
        super().__init__()
        self._clickable = clickable
        self.setStyleSheet(f"QFrame#stat {{ background:{color}; border-radius:12px; }}")
        self.setObjectName("stat")
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Jikme-jik görmek üçin basyň")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setStyleSheet("background:rgba(255,255,255,0.95); border-radius:9px; "
                           f"color:{color}; font-size:14pt;")
        row.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("color:rgba(255,255,255,0.9); font-size:8.5pt;")
        v = QLabel(value)
        v.setStyleSheet("color:white; font-size:12pt; font-weight:700;")
        col.addWidget(t)
        col.addWidget(v)
        row.addLayout(col, 1)

        badge = delta_badge(delta, positive)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        shadow(self)

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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
    """Столбчатый график с поддержкой семантического зума по таймлайнам
    (часы ↔ дни ↔ недели ↔ месяцы ↔ годы), перетаскивания (Pan),
    динамических осей X/Y и всплывающего окна продаж/прибыли при наведении."""

    zoomChanged = Signal(str)
    timelineZoomRequested = Signal(int, object)
    timelinePanRequested = Signal(int)

    def __init__(
        self,
        labels: list[str],
        purchases: list[float],
        sales: list[float],
        y_max: float = 60,
        buckets_meta: list[dict] | None = None,
        timeline_mode: bool = False,
        can_zoom_in: bool = True,
        can_zoom_out: bool = True,
    ) -> None:
        super().__init__()
        self.labels = labels
        self.purchases = purchases
        self.sales = sales
        self.base_y_max = max(float(y_max or 1), 1.0)
        self.y_max = self._nice_axis_max(self.base_y_max)
        self.buckets_meta = buckets_meta or []
        self._hovered_index = -1
        self._timeline_mode = bool(timeline_mode)
        self._can_zoom_in = bool(can_zoom_in)
        self._can_zoom_out = bool(can_zoom_out)
        self._last_wheel_ts = 0.0

        # Состояние масштабирования: окно видимых баров [start_idx .. end_idx) + вертикальный зум
        self._total_n = len(labels)
        self._view_start = 0
        self._view_count = max(1, self._total_n)
        self._y_zoom = 1.0  # > 1.0 означает приближение по вертикальной оси Y
        self._dragging = False
        self._drag_last_x = 0.0
        self._drag_accum_x = 0.0

        self.setMouseTracking(True)
        self.setMinimumHeight(185)

    @staticmethod
    def _nice_axis_max(raw_max: float) -> float:
        """Округляет максимум оси Y вверх до красивого шага (1, 2, 2.5, 5 × 10^k)."""
        import math

        val = max(float(raw_max or 0.0), 1.0)
        exp = math.floor(math.log10(val))
        base = 10 ** exp
        norm = val / base
        if norm <= 1.0:
            nice = 1.0
        elif norm <= 1.5:
            nice = 1.5
        elif norm <= 2.0:
            nice = 2.0
        elif norm <= 2.5:
            nice = 2.5
        elif norm <= 3.0:
            nice = 3.0
        elif norm <= 4.0:
            nice = 4.0
        elif norm <= 5.0:
            nice = 5.0
        elif norm <= 7.5:
            nice = 7.5
        else:
            nice = 10.0
        return max(5.0, nice * base)

    def _effective_y_max(self) -> float:
        """Динамически пересчитывает максимум оси Y для текущего видимого окна и вертикального зума."""
        if self._total_n == 0:
            return self.base_y_max
        s = self._view_start
        e = min(self._total_n, s + self._view_count)
        vis_pur = self.purchases[s:e]
        vis_sal = self.sales[s:e]
        local_max = max(max(vis_pur, default=0.0), max(vis_sal, default=0.0))
        target = local_max if local_max > 0 else self.base_y_max
        scaled = target / max(self._y_zoom, 0.25)
        return self._nice_axis_max(scaled)

    def zoom_percent_label(self) -> str:
        if self._total_n <= 0:
            return "100%"
        x_ratio = self._total_n / max(1, self._view_count)
        pct = round(x_ratio * self._y_zoom * 100)
        return f"{pct}%"

    def _emit_zoom_state(self) -> None:
        self.y_max = self._effective_y_max()
        self.zoomChanged.emit(self.zoom_percent_label())
        self.update()

    def zoom_in(self, anchor_ratio: float = 0.85) -> None:
        """Приближение: сначала сужает видимое окно по оси X, затем масштабирует ось Y."""
        if self._total_n <= 0:
            return
        min_count = min(self._total_n, 4)
        if self._view_count > min_count:
            new_count = max(min_count, round(self._view_count * 0.7))
            if new_count == self._view_count:
                new_count = max(min_count, self._view_count - 1)
            anchor_idx = self._view_start + anchor_ratio * self._view_count
            new_start = round(anchor_idx - anchor_ratio * new_count)
            new_start = max(0, min(self._total_n - new_count, new_start))
            self._view_start = new_start
            self._view_count = new_count
        else:
            # Достигнут минимум баров по X -> приближаем вертикальную ось Y
            self._y_zoom = min(16.0, self._y_zoom * 1.4)
        self._hovered_index = -1
        self._emit_zoom_state()

    def zoom_out(self, anchor_ratio: float = 0.5) -> None:
        """Отдаление: сначала возвращает ось Y, затем расширяет окно по оси X (и допускает Y-отдаление)."""
        if self._total_n <= 0:
            return
        if self._y_zoom > 1.05:
            self._y_zoom = max(1.0, self._y_zoom / 1.4)
        elif self._view_count < self._total_n:
            new_count = min(self._total_n, max(self._view_count + 1, round(self._view_count / 0.7)))
            anchor_idx = self._view_start + anchor_ratio * self._view_count
            new_start = round(anchor_idx - anchor_ratio * new_count)
            new_start = max(0, min(self._total_n - new_count, new_start))
            self._view_start = new_start
            self._view_count = new_count
        else:
            # На полном диапазоне можно слегка отдалить шкалу Y (до 50%)
            self._y_zoom = max(0.5, self._y_zoom / 1.25)
        self._hovered_index = -1
        self._emit_zoom_state()

    def reset_zoom(self) -> None:
        self._view_start = 0
        self._view_count = max(1, self._total_n)
        self._y_zoom = 1.0
        self._hovered_index = -1
        self._emit_zoom_state()

    def _chart_geometry(self) -> tuple[int, int, int, int, int, int]:
        left, right, top, bottom = 54, 10, 68, 24
        w = max(10, self.width() - left - right)
        h = max(10, self.height() - top - bottom)
        return left, right, top, bottom, w, h

    @staticmethod
    def _format_axis_val(val: float) -> str:
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M".replace(".0M", "M")
        if val >= 1_000:
            return f"{val / 1_000:.1f}K".replace(".0K", "K")
        if val >= 10:
            return f"{round(val)}"
        if val > 0:
            return f"{val:.1f}".rstrip("0").rstrip(".")
        return "0"

    def _bucket_focus_date(self, idx: int):
        if 0 <= idx < len(self.buckets_meta):
            return self.buckets_meta[idx].get("focus_date")
        return None

    def _bar_index_at_x(self, pos_x: float) -> int:
        left, _right, _top, _bottom, w, _h = self._chart_geometry()
        vis_n = min(self._view_count, max(0, self._total_n - self._view_start))
        if vis_n <= 0 or pos_x < left or pos_x > left + w:
            return -1
        slot = w / vis_n
        rel_idx = int((pos_x - left) / slot)
        if 0 <= rel_idx < vis_n:
            return self._view_start + rel_idx
        return -1

    def wheelEvent(self, event) -> None:
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            super().wheelEvent(event)
            return
        if self._timeline_mode:
            import time as _time

            now = _time.monotonic()
            if now - self._last_wheel_ts < 0.11:
                event.accept()
                return
            self._last_wheel_ts = now
            idx = self._bar_index_at_x(event.position().x())
            focus_dt = self._bucket_focus_date(idx) if idx >= 0 else None
            if delta_y > 0 and self._can_zoom_in:
                self.timelineZoomRequested.emit(1, focus_dt)
            elif delta_y < 0 and self._can_zoom_out:
                self.timelineZoomRequested.emit(-1, focus_dt)
            event.accept()
            return

        left, _right, _top, _bottom, w, _h = self._chart_geometry()
        pos_x = event.position().x()
        ratio = max(0.0, min(1.0, (pos_x - left) / max(1, w)))
        if delta_y > 0:
            self.zoom_in(anchor_ratio=ratio)
        else:
            self.zoom_out(anchor_ratio=ratio)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if (
            self._timeline_mode
            and event.button() == Qt.MouseButton.LeftButton
            and self._can_zoom_in
        ):
            idx = self._bar_index_at_x(event.position().x())
            focus_dt = self._bucket_focus_date(idx) if idx >= 0 else None
            self.timelineZoomRequested.emit(1, focus_dt)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and (
            self._timeline_mode or self._view_count < self._total_n
        ):
            self._dragging = True
            self._drag_last_x = event.position().x()
            self._drag_accum_x = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_accum_x = 0.0
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        left, _right, top, _bottom, w, h = self._chart_geometry()
        pos = event.position()

        if self._dragging:
            dx = pos.x() - self._drag_last_x
            if self._timeline_mode:
                self._drag_accum_x += dx
                self._drag_last_x = pos.x()
                if abs(self._drag_accum_x) >= 65.0:
                    step = -1 if self._drag_accum_x > 0 else 1
                    self._drag_accum_x = 0.0
                    self._dragging = False
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.timelinePanRequested.emit(step)
                return
            if self._view_count < self._total_n:
                slot = w / max(1, self._view_count)
                shift = round(-dx / max(12.0, slot))
                if shift != 0:
                    new_start = max(0, min(self._total_n - self._view_count, self._view_start + shift))
                    if new_start != self._view_start:
                        self._view_start = new_start
                        self._drag_last_x = pos.x()
                        self._hovered_index = -1
                        self._emit_zoom_state()
                return

        vis_n = min(self._view_count, max(0, self._total_n - self._view_start))
        new_hover = -1
        if vis_n > 0 and left <= pos.x() <= left + w and 0 <= pos.y() <= top + h + 24:
            slot = w / vis_n
            rel_idx = int((pos.x() - left) / slot)
            if 0 <= rel_idx < vis_n:
                new_hover = self._view_start + rel_idx
        if new_hover != self._hovered_index:
            self._hovered_index = new_hover
            if self._view_count < self._total_n:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if new_hover >= 0
                    else Qt.CursorShape.ArrowCursor
                )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._dragging = False
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

        eff_y_max = self._effective_y_max()
        self.y_max = eff_y_max

        steps = 5
        for i in range(steps + 1):
            y = top + h - h * i / steps
            p.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine))
            p.drawLine(left, int(y), left + w, int(y))
            p.setPen(QColor(theme.MUTED))
            axis_label = self._format_axis_val(eff_y_max * i / steps)
            p.drawText(
                QRectF(0, y - 8, left - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                axis_label,
            )

        if self._total_n == 0:
            p.end()
            return

        start = self._view_start
        end = min(self._total_n, start + self._view_count)
        vis_n = end - start
        if vis_n <= 0:
            p.end()
            return

        slot = w / vis_n
        bw = max(6.0, min(32.0, slot * 0.58))
        label_step = 1 if vis_n <= 14 else (2 if vis_n <= 20 else 3)
        last_step_idx = ((vis_n - 1) // label_step) * label_step

        for rel_i, orig_i in enumerate(range(start, end)):
            name = self.labels[orig_i]
            cx = left + slot * (rel_i + 0.5)
            is_hovered = orig_i == self._hovered_index

            if is_hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(245, 138, 46, 26))
                p.drawRoundedRect(QRectF(cx - slot / 2 + 2, top, slot - 4, h), 6, 6)

            for value, color, is_sales in (
                (self.purchases[orig_i], theme.ACCENT_SOFT, False),
                (self.sales[orig_i], theme.ACCENT, True),
            ):
                bh = min(h, max(0.0, h * float(value) / eff_y_max))
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

            show_last = rel_i == vis_n - 1 and (vis_n - 1 - last_step_idx) >= 2
            if rel_i % label_step == 0 or show_last or is_hovered:
                lbl_font = QFont(font)
                lbl_font.setBold(is_hovered)
                p.setFont(lbl_font)
                p.setPen(QColor(theme.NAVY if is_hovered else theme.MUTED))
                p.drawText(
                    QRectF(cx - max(slot, 38) / 2, top + h + 5, max(slot, 38), 16),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )
                p.setFont(font)

        # закрываем скруглённые «хвосты» столбцов под осью
        p.fillRect(QRectF(left, top + h, w, 6), QColor("white"))

        # Всплывающее окно сверху диаграммы при наведении на столбец
        if start <= self._hovered_index < end:
            self._draw_hover_popup(p, left, w, slot, self._hovered_index, self._hovered_index - start)
        else:
            hint_font = QFont(font)
            hint_font.setPointSizeF(8.3)
            p.setFont(hint_font)
            p.setPen(QColor(theme.MUTED))
            if self._timeline_mode:
                zoom_hint = "Tigir / + −: sagat ↔ gün ↔ hepde ↔ aý ↔ ýyl  •  Çekip süýşür"
            elif self._view_count < self._total_n:
                zoom_hint = "Syçanjyk tigiri: ýakynlaşdyr/uzaklaşdyr • Çekip süýşür"
            else:
                zoom_hint = "Syçanjygy eltiň (maglumat) • Tigir / + − (masştab)"
            p.drawText(
                QRectF(left, 4, w, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                zoom_hint,
            )

        p.end()

    def _draw_hover_popup(
        self,
        p: QPainter,
        left: int,
        w: int,
        slot: float,
        idx: int,
        rel_idx: int | None = None,
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
        popup_h = 60.0
        pos_slot = idx if rel_idx is None else rel_idx
        cx = left + slot * (pos_slot + 0.5)
        px = max(float(left), min(cx - popup_w / 2, float(left + w) - popup_w))
        py = 3.0

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


SEARCH_CARD_ROLE = Qt.ItemDataRole.UserRole + 21


class SearchResultDelegate(QStyledItemDelegate):
    """Отрисовывает аккуратные 2-строчные карточки результатов живого поиска
    с иконкой, категорией, статусом/остатком и себестоимостью."""

    ROW_HEIGHT = 56

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        meta = index.data(SEARCH_CARD_ROLE)
        if not isinstance(meta, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # Фон строки и разделитель
        if is_selected:
            bg = QColor(theme.ACCENT_BG)
        elif is_hovered:
            bg = QColor("#FFF8F1")
        elif index.row() % 2 == 1:
            bg = QColor("#FAFBFC")
        else:
            bg = QColor("#FFFFFF")

        painter.fillRect(rect, bg)

        if is_selected or is_hovered:
            accent_bar = QRectF(rect.left() + 2, rect.top() + 5, 3.5, rect.height() - 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT if is_selected else "#FDBA74"))
            painter.drawRoundedRect(accent_bar, 2, 2)

        painter.setPen(QPen(QColor("#EEF2F6"), 1))
        painter.drawLine(rect.left() + 12, rect.bottom(), rect.right() - 12, rect.bottom())

        # Левая векторная иконка-бейдж (без зависимости от emoji-шрифтов ОС)
        icon_kind = meta.get("icon_kind", "product")
        icon_styles = {
            "phone": ("#EFF6FF", "#BFDBFE", "#1D4ED8"),
            "imei": ("#EFF6FF", "#BFDBFE", "#1D4ED8"),
            "sale": ("#F1F5F9", "#CBD5E1", "#475569"),
            "product": ("#FFF3E6", "#FED7AA", "#C2410C"),
        }
        icon_bg, icon_border, icon_fg = icon_styles.get(icon_kind, icon_styles["product"])
        icon_rect = QRectF(rect.left() + 12, rect.top() + (rect.height() - 34) / 2, 34, 34)
        painter.setPen(QPen(QColor(icon_border), 1))
        painter.setBrush(QColor(icon_bg))
        painter.drawRoundedRect(icon_rect, 8, 8)

        cx = icon_rect.center().x()
        cy = icon_rect.center().y()
        painter.setPen(QPen(QColor(icon_fg), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if icon_kind in ("phone", "imei"):
            painter.drawRoundedRect(QRectF(cx - 6, cy - 9, 12, 18), 2.5, 2.5)
            painter.drawLine(int(cx - 2), int(cy + 6), int(cx + 2), int(cy + 6))
        elif icon_kind == "sale":
            painter.drawRoundedRect(QRectF(cx - 6.5, cy - 8.5, 13, 17), 2.0, 2.0)
            painter.drawLine(int(cx - 3.5), int(cy - 3), int(cx + 3.5), int(cy - 3))
            painter.drawLine(int(cx - 3.5), int(cy + 0.5), int(cx + 3.5), int(cy + 0.5))
            painter.drawLine(int(cx - 3.5), int(cy + 4), int(cx + 1.5), int(cy + 4))
        else:
            # Коробка товара
            painter.drawRoundedRect(QRectF(cx - 7.5, cy - 6.5, 15, 13), 2.0, 2.0)
            painter.drawLine(int(cx - 7.5), int(cy - 2), int(cx + 7.5), int(cy - 2))
            painter.drawLine(int(cx), int(cy - 6.5), int(cx), int(cy - 2))

        content_left = int(icon_rect.right()) + 10
        content_right = rect.right() - 12

        # Верхняя строка: справа бейдж статуса/остатка + бейдж категории
        right_cursor = content_right
        badge_text = (meta.get("badge_text") or "").strip()
        badge_tone = meta.get("badge_tone", "green")
        tone_map = {
            "green": ("#E7F6EC", "#BBF7D0", "#15803D"),
            "blue": ("#EFF6FF", "#BFDBFE", "#1D4ED8"),
            "orange": ("#FFEDD5", "#FDBA74", "#C2410C"),
            "red": ("#FDECEA", "#FECACA", "#B42318"),
            "muted": ("#F1F5F9", "#E2E8F0", "#475569"),
        }

        badge_font = QFont(option.font)
        badge_font.setPointSizeF(8.3)
        badge_font.setBold(True)
        badge_fm = QFontMetrics(badge_font)

        if badge_text:
            b_bg, b_bd, b_fg = tone_map.get(badge_tone, tone_map["green"])
            bw = badge_fm.horizontalAdvance(badge_text) + 16
            bh = 20
            b_rect = QRectF(right_cursor - bw, rect.top() + 7, bw, bh)
            painter.setPen(QPen(QColor(b_bd), 1))
            painter.setBrush(QColor(b_bg))
            painter.drawRoundedRect(b_rect, 6, 6)
            painter.setFont(badge_font)
            painter.setPen(QColor(b_fg))
            painter.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
            right_cursor = int(b_rect.left()) - 6

        cat_text = (meta.get("category") or "").strip()
        if cat_text and cat_text != "—":
            cw = min(160, badge_fm.horizontalAdvance(cat_text) + 16)
            ch = 20
            c_rect = QRectF(right_cursor - cw, rect.top() + 7, cw, ch)
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            painter.setBrush(QColor("#F8FAFC"))
            painter.drawRoundedRect(c_rect, 6, 6)
            painter.setFont(badge_font)
            painter.setPen(QColor("#334155"))
            elided_cat = badge_fm.elidedText(cat_text, Qt.TextElideMode.ElideRight, int(cw - 10))
            painter.drawText(c_rect, Qt.AlignmentFlag.AlignCenter, elided_cat)
            right_cursor = int(c_rect.left()) - 8

        # Верхняя строка: название товара (жирный NAVY)
        title_font = QFont(option.font)
        title_font.setPointSizeF(10.0)
        title_font.setBold(True)
        title_fm = QFontMetrics(title_font)
        title_w = max(40, right_cursor - content_left)
        title_str = title_fm.elidedText(
            str(meta.get("title") or ""),
            Qt.TextElideMode.ElideRight,
            title_w,
        )
        painter.setFont(title_font)
        painter.setPen(QColor(theme.NAVY))
        painter.drawText(
            QRectF(content_left, rect.top() + 6, title_w, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_str,
        )

        # Нижняя строка: справа себестоимость / сумма
        cost_text = (meta.get("cost_text") or "").strip()
        sub_right = content_right
        if cost_text and cost_text != "—":
            cost_font = QFont(option.font)
            cost_font.setPointSizeF(8.8)
            cost_font.setBold(True)
            cost_fm = QFontMetrics(cost_font)
            cost_w = cost_fm.horizontalAdvance(cost_text) + 6
            painter.setFont(cost_font)
            painter.setPen(QColor("#0F172A"))
            painter.drawText(
                QRectF(content_right - cost_w, rect.top() + 30, cost_w, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                cost_text,
            )
            sub_right = content_right - cost_w - 10

        # Нижняя строка: бренд / модель / IMEI (приглушённый)
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(8.7)
        sub_font.setBold(False)
        sub_fm = QFontMetrics(sub_font)
        sub_w = max(40, sub_right - content_left)
        sub_str = sub_fm.elidedText(
            str(meta.get("subtitle") or ""),
            Qt.TextElideMode.ElideRight,
            sub_w,
        )
        painter.setFont(sub_font)
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(
            QRectF(content_left, rect.top() + 30, sub_w, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            sub_str,
        )

        painter.restore()


class SearchResultPopup(QListWidget):
    """Стилизованный, прокручиваемый выпадающий список результатов живого поиска
    в виде встроенного оверлея поверх окна (без багов фокуса/скролла QToolTip)."""

    def __init__(self, host_window: QWidget | None = None) -> None:
        super().__init__(host_window)
        self._anchor: QWidget | None = None
        self._app_filter_installed = False
        self.setObjectName("searchResultPopup")
        self.setItemDelegate(SearchResultDelegate(self))
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet(f"""
            QListWidget#searchResultPopup {{
                background: {theme.WHITE};
                border: 1.5px solid #D0D5DD;
                border-radius: 12px;
                padding: 4px;
                outline: none;
            }}
            QListWidget#searchResultPopup::item {{
                border: none;
                padding: 0px;
            }}
            QScrollBar:vertical {{
                background: #F8FAFC;
                width: 9px;
                margin: 4px 2px 4px 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #CBD5E1;
                min-height: 28px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {theme.ACCENT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        shadow(self, blur=24, y=8, alpha=36)
        self.hide()

    def add_result_card(
        self,
        *,
        title: str,
        category: str,
        subtitle: str,
        cost_text: str,
        badge_text: str,
        badge_tone: str,
        icon_kind: str,
        payload: dict,
    ) -> QListWidgetItem:
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(0, SearchResultDelegate.ROW_HEIGHT))
        item.setData(Qt.ItemDataRole.UserRole, payload)
        item.setData(
            SEARCH_CARD_ROLE,
            {
                "title": title,
                "category": category,
                "subtitle": subtitle,
                "cost_text": cost_text,
                "badge_text": badge_text,
                "badge_tone": badge_tone,
                "icon_kind": icon_kind,
            },
        )
        self.addItem(item)
        return item

    def show_below(self, anchor: QWidget, min_width: int = 640, max_height: int = 420) -> None:
        if self.count() == 0:
            self.hide()
            return
        self._anchor = anchor
        host = anchor.window()
        if host is not None and self.parentWidget() is not host:
            self.setParent(host)
        if host is None:
            return

        top_left = anchor.mapTo(host, QPoint(0, anchor.height() + 4))
        w = min(max(min_width, anchor.width()), max(360, host.width() - 28))
        x = max(14, min(top_left.x(), host.width() - w - 14))
        avail_h = max(140, host.height() - top_left.y() - 18)
        desired_h = self.count() * SearchResultDelegate.ROW_HEIGHT + 12
        h = min(max_height, avail_h, desired_h)

        self.setGeometry(x, top_left.y(), w, h)
        self.raise_()
        self.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None and not self._app_filter_installed:
            app.installEventFilter(self)
            self._app_filter_installed = True

    def hideEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None and self._app_filter_installed:
            app.removeEventFilter(self)
            self._app_filter_installed = False
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if self.isVisible():
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and hasattr(event, "globalPosition"):
                gpos = event.globalPosition().toPoint()
                in_popup = self.rect().contains(self.mapFromGlobal(gpos))
                in_anchor = (
                    self._anchor is not None
                    and self._anchor.isVisible()
                    and self._anchor.rect().contains(self._anchor.mapFromGlobal(gpos))
                )
                if not in_popup and not in_anchor:
                    self.hide()
            elif et == QEvent.Type.WindowDeactivate and obj is self.window():
                self.hide()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide()
            if self._anchor is not None:
                self._anchor.setFocus()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cur = self.currentItem()
            if cur is not None:
                self.itemClicked.emit(cur)
                return
        super().keyPressEvent(event)

    def step_selection(self, delta: int) -> None:
        n = self.count()
        if n == 0:
            return
        cur = self.currentRow()
        if cur < 0:
            nxt = 0 if delta > 0 else n - 1
        else:
            nxt = max(0, min(n - 1, cur + delta))
        self.setCurrentRow(nxt)
        item = self.item(nxt)
        if item is not None:
            self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

    def is_interacting(self) -> bool:
        if not self.isVisible():
            return False
        fw = QApplication.focusWidget()
        if fw is self or (fw is not None and self.isAncestorOf(fw)):
            return True
        if self.underMouse():
            return True
        sb = self.verticalScrollBar()
        return bool(sb is not None and (sb.underMouse() or sb.isSliderDown()))
