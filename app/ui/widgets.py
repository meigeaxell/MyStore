"""Переиспользуемые виджеты: карточки, таблицы, кнопки, списки и график."""
import weakref
from decimal import Decimal, InvalidOperation
from typing import ClassVar

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
            "success": (theme.WHITE, theme.ACCENT, theme.ACCENT_HOVER, "check"),
            "info": (theme.WHITE, theme.ACCENT, theme.ACCENT_HOVER, "info"),
            "warning": (theme.WHITE, "#D97706", "#B45309", "warning"),
            "error": (theme.WHITE, theme.RED, "#C81E1E", "close"),
        }
        fg, bg, border, icon_key = palettes.get(kind, palettes["info"])

        self.setStyleSheet(
            f"QFrame#toastNotification {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 10px; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 18, 8)
        row.setSpacing(8)

        from app.ui.icons import make_icon

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon_lbl.setStyleSheet("background: transparent;")
        icon_lbl.setPixmap(make_icon(icon_key, fg, 16).pixmap(QSize(16, 16)))
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


_CONFIGURED_TABLES: list[tuple[weakref.ref, list[int] | None, int]] = []


def _get_active_table_preset() -> str:
    try:
        from sqlalchemy.exc import SQLAlchemyError

        from app.services.settings_service import SettingsService

        return SettingsService.get_table_layout_preset()
    except (ImportError, RuntimeError, ValueError, SQLAlchemyError):
        return "auto_fit"


def apply_table_preset(
    table: QTableWidget,
    stretch_cols: list[int] | None = None,
    base_row_height: int = 46,
    preset: str | None = None,
) -> None:
    """Применяет выбранный шаблон построения таблицы (auto_fit | wrap_full | compact | wide_scroll)."""
    mode = preset or _get_active_table_preset()
    header = table.horizontalHeader()
    vheader = table.verticalHeader()
    col_count = table.columnCount()
    stretch_set = set(stretch_cols or [])

    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    if mode == "wide_scroll":
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        header.setStretchLastSection(False)
        for col in range(col_count):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        vheader.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vheader.setDefaultSectionSize(max(38, min(base_row_height, 44)))
    elif mode == "wrap_full":
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        header.setStretchLastSection(False)
        for col in range(col_count):
            if col in stretch_set:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        vheader.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vheader.setMinimumSectionSize(max(36, base_row_height - 6))
        vheader.setDefaultSectionSize(base_row_height)
    elif mode == "compact":
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header.setStretchLastSection(False)
        for col in range(col_count):
            if col in stretch_set:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        vheader.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vheader.setDefaultSectionSize(theme.ROW_H_COMPACT)
    else:
        # auto_fit (по умолчанию): интерактивные колонки с умным авто-подбором и переносом длинных названий
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header.setStretchLastSection(False)
        for col in range(col_count):
            if col in stretch_set:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        vheader.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vheader.setMinimumSectionSize(max(38, base_row_height - 4))
        vheader.setDefaultSectionSize(base_row_height)

    QTimer.singleShot(0, lambda t=table, m=mode, ss=stretch_set: _fit_table_after_data(t, m, ss))


def _fit_table_after_data(table: QTableWidget, mode: str, stretch_set: set[int]) -> None:
    try:
        if table.columnCount() == 0:
            return
        if mode == "auto_fit":
            for col in range(table.columnCount()):
                if col in stretch_set or table.isColumnHidden(col):
                    continue
                table.resizeColumnToContents(col)
                w = table.columnWidth(col)
                table.setColumnWidth(col, max(54, min(w + 18, 280)))
            table.resizeRowsToContents()
        elif mode == "wrap_full":
            table.resizeRowsToContents()
    except RuntimeError:
        pass


def apply_table_layout_preset_all(preset: str | None = None) -> None:
    """Мгновенно применяет шаблон таблиц ко всем открытым таблицам приложения."""
    mode = preset or _get_active_table_preset()
    alive: list[tuple[weakref.ref, list[int] | None, int]] = []
    for ref, stretch_cols, base_h in _CONFIGURED_TABLES:
        tbl = ref()
        if tbl is not None:
            try:
                apply_table_preset(tbl, stretch_cols, base_h, preset=mode)
                alive.append((ref, stretch_cols, base_h))
            except RuntimeError:
                pass
    _CONFIGURED_TABLES[:] = alive


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
    cols: list[int] | None = None
    if stretch_col is not None:
        cols = [stretch_col] if isinstance(stretch_col, int) else list(stretch_col)
        cols = [c for c in cols if 0 <= c < table.columnCount()]

    apply_table_preset(table, cols, row_height)

    # Авто-подстройка при заполнении таблицы данными
    tbl_ref = weakref.ref(table)

    def _on_data_changed(*_args, _ref=tbl_ref, sc=cols) -> None:
        t = _ref()
        if t is None:
            return
        mode = _get_active_table_preset()
        if mode in ("auto_fit", "wrap_full"):
            QTimer.singleShot(0, lambda tt=t, m=mode, ss=set(sc or []): _fit_table_after_data(tt, m, ss))

    model = table.model()
    if model is not None:
        model.rowsInserted.connect(_on_data_changed)
        model.modelReset.connect(_on_data_changed)

    _CONFIGURED_TABLES.append((weakref.ref(table), cols, row_height))

    header = table.horizontalHeader()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.customContextMenuRequested.connect(
        lambda pos, tbl=table: _show_header_column_menu(tbl, pos)
    )


def _show_header_column_menu(table: QTableWidget, pos) -> None:
    """Контекстное меню заголовка таблицы для включения/скрытия колонок и автоподбора ширины."""
    menu = QMenu(table)
    fit_action = menu.addAction("Sütün giňliklerini awto-düz")
    fit_action.triggered.connect(lambda: table.resizeColumnsToContents())
    menu.addSeparator()
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

        from app.ui.icons import has_icon, make_icon

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.95); border-radius:9px; "
            f"color:{color}; font-size:14pt;"
        )
        if has_icon(glyph):
            icon.setPixmap(make_icon(glyph, color, 20).pixmap(QSize(20, 20)))
        else:
            icon.setText(glyph)
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
        from app.ui.icons import has_icon, make_icon

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        icon.setStyleSheet(f"background:{tint}; border-radius:10px; font-size:14pt;")
        if has_icon(glyph):
            icon.setPixmap(make_icon(glyph, theme.NAVY, 20).pixmap(QSize(20, 20)))
        else:
            icon.setText(glyph)
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)

        color = theme.GREEN if positive else theme.RED
        sign = "+" if positive else "−"
        d = QLabel(f"<span style='color:{color}; font-weight:600'>{sign}{delta}</span>"
                   f" <span style='color:{theme.MUTED}'>• häzirki görkeziji</span>")
        d.setStyleSheet("font-size:9pt;")
        self.body.addWidget(d)


class BarChart(QWidget):
    """Столбчатый график с плавным непрерывным 2D-зумом (по осям X и Y),
    инерционной 60fps-интерполяцией, плавным перетаскиванием (Pan по X/Y)
    и всплывающим окном продаж/прибыли при наведении."""

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
        self.base_y_max = self._nice_axis_max(max(float(y_max or 1), 1.0))
        self.y_max = self.base_y_max
        self.buckets_meta = buckets_meta or []
        self._hovered_index = -1
        self._timeline_mode = bool(timeline_mode)
        self._can_zoom_in = bool(can_zoom_in)
        self._can_zoom_out = bool(can_zoom_out)
        self._last_wheel_ts = 0.0

        # Непрерывное (float) окно по X и Y + целевые значения для плавной анимации
        self._total_n = len(labels)
        full_span = float(max(1, self._total_n))
        self._x_start = 0.0
        self._x_span = full_span
        self._y_min = 0.0
        self._y_max = self.base_y_max

        self._tx_start = self._x_start
        self._tx_span = self._x_span
        self._ty_min = self._y_min
        self._ty_max = self._y_max

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._step_smooth_zoom)

        self._dragging = False
        self._drag_last_x = 0.0
        self._drag_last_y = 0.0

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

    def _clamp_targets(self) -> None:
        full_x = float(max(1, self._total_n))
        min_x_span = min(full_x, 2.0)
        self._tx_span = max(min_x_span, min(full_x, self._tx_span))
        self._tx_start = max(0.0, min(full_x - self._tx_span, self._tx_start))

        min_y_span = max(1.0, self.base_y_max * 0.04)
        max_y_span = self.base_y_max * 2.5
        y_span = max(min_y_span, min(max_y_span, self._ty_max - self._ty_min))
        self._ty_min = max(0.0, min(self.base_y_max * 0.96, self._ty_min))
        self._ty_max = self._ty_min + y_span
        if self._ty_max > max_y_span:
            self._ty_max = max_y_span
            self._ty_min = max(0.0, self._ty_max - y_span)

    def _start_smooth_anim(self) -> None:
        self._clamp_targets()
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _step_smooth_zoom(self) -> None:
        k = 0.28
        self._x_start += (self._tx_start - self._x_start) * k
        self._x_span += (self._tx_span - self._x_span) * k
        self._y_min += (self._ty_min - self._y_min) * k
        self._y_max += (self._ty_max - self._y_max) * k

        done = (
            abs(self._tx_start - self._x_start) < 1e-3
            and abs(self._tx_span - self._x_span) < 1e-3
            and abs(self._ty_min - self._y_min) < 1e-2
            and abs(self._ty_max - self._y_max) < 1e-2
        )
        if done:
            self._x_start = self._tx_start
            self._x_span = self._tx_span
            self._y_min = self._ty_min
            self._y_max = self._ty_max
            self._anim_timer.stop()

        self.y_max = self._y_max
        self.zoomChanged.emit(self.zoom_percent_label())
        self.update()

    def _is_zoomed(self) -> bool:
        full_x = float(max(1, self._total_n))
        return (
            self._x_span < full_x - 0.05
            or abs(self._y_max - self.base_y_max) > self.base_y_max * 0.02
            or self._y_min > 0.5
        )

    def zoom_percent_label(self) -> str:
        if self._total_n <= 0:
            return "100%"
        x_ratio = self._total_n / max(0.5, self._x_span)
        y_ratio = self.base_y_max / max(1.0, self._y_max - self._y_min)
        pct = round(max(x_ratio, y_ratio) * 100)
        return f"{pct}%"

    def zoom_in(self, anchor_x: float = 0.5, anchor_y: float = 0.5, zoom_x: bool = True, zoom_y: bool = True) -> None:
        self._apply_zoom_factor(0.82, anchor_x, anchor_y, zoom_x=zoom_x, zoom_y=zoom_y)

    def zoom_out(self, anchor_x: float = 0.5, anchor_y: float = 0.5, zoom_x: bool = True, zoom_y: bool = True) -> None:
        self._apply_zoom_factor(1.0 / 0.82, anchor_x, anchor_y, zoom_x=zoom_x, zoom_y=zoom_y)

    def _apply_zoom_factor(
        self,
        factor: float,
        anchor_x: float,
        anchor_y: float,
        zoom_x: bool = True,
        zoom_y: bool = True,
    ) -> None:
        if self._total_n <= 0:
            return
        ax = max(0.0, min(1.0, anchor_x))
        ay = max(0.0, min(1.0, anchor_y))
        if zoom_x:
            anchor_data_x = self._tx_start + ax * self._tx_span
            new_span = self._tx_span * factor
            self._tx_span = new_span
            self._tx_start = anchor_data_x - ax * new_span
        if zoom_y:
            y_span = max(1.0, self._ty_max - self._ty_min)
            # ay=0 внизу оси Y (0), ay=1 вверху
            anchor_data_y = self._ty_min + ay * y_span
            new_y_span = y_span * factor
            self._ty_min = anchor_data_y - ay * new_y_span
            self._ty_max = self._ty_min + new_y_span
        self._start_smooth_anim()

    def reset_zoom(self) -> None:
        self._tx_start = 0.0
        self._tx_span = float(max(1, self._total_n))
        self._ty_min = 0.0
        self._ty_max = self.base_y_max
        self._hovered_index = -1
        self._start_smooth_anim()

    def _chart_geometry(self) -> tuple[int, int, int, int, int, int]:
        left, right, top, bottom = 58, 12, 68, 24
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

    def _bar_index_at_x(self, pos_x: float) -> int:
        left, _right, _top, _bottom, w, _h = self._chart_geometry()
        if self._total_n <= 0 or pos_x < left or pos_x > left + w:
            return -1
        data_x = self._x_start + ((pos_x - left) / w) * self._x_span
        idx = int(data_x)
        if 0 <= idx < self._total_n:
            return idx
        return -1

    def wheelEvent(self, event) -> None:
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            super().wheelEvent(event)
            return

        left, _right, top, _bottom, w, h = self._chart_geometry()
        pos = event.position()
        anchor_x = max(0.0, min(1.0, (pos.x() - left) / max(1, w)))
        anchor_y = max(0.0, min(1.0, 1.0 - (pos.y() - top) / max(1, h)))

        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            zx, zy = False, True
        elif mods & Qt.KeyboardModifier.ControlModifier:
            zx, zy = True, False
        else:
            zx, zy = True, True

        # Пропорциональный плавный коэффициент (учитывает и обычную мышь, и плавный тачпад)
        steps = delta_y / 120.0
        factor = 0.85 ** steps
        self._apply_zoom_factor(factor, anchor_x, anchor_y, zoom_x=zx, zoom_y=zy)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_zoomed():
            self._dragging = True
            self._drag_last_x = event.position().x()
            self._drag_last_y = event.position().y()
            self._anim_timer.stop()
            self._tx_start, self._tx_span = self._x_start, self._x_span
            self._ty_min, self._ty_max = self._y_min, self._y_max
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if self._is_zoomed() else Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        left, _right, top, _bottom, w, h = self._chart_geometry()
        pos = event.position()

        if self._dragging:
            dx = pos.x() - self._drag_last_x
            dy = pos.y() - self._drag_last_y
            self._drag_last_x = pos.x()
            self._drag_last_y = pos.y()

            self._tx_start -= (dx / max(1, w)) * self._tx_span
            y_span = max(1.0, self._ty_max - self._ty_min)
            shift_y = (dy / max(1, h)) * y_span
            self._ty_min += shift_y
            self._ty_max += shift_y
            self._clamp_targets()

            self._x_start = self._tx_start
            self._y_min = self._ty_min
            self._y_max = self._ty_max
            self._hovered_index = -1
            self.update()
            return

        new_hover = -1
        if self._total_n > 0 and left <= pos.x() <= left + w and 0 <= pos.y() <= top + h + 24:
            new_hover = self._bar_index_at_x(pos.x())
        if new_hover != self._hovered_index:
            self._hovered_index = new_hover
            if self._is_zoomed():
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

        y_min = self._y_min
        y_max = max(y_min + 1.0, self._y_max)
        y_span = y_max - y_min

        steps = 5
        for i in range(steps + 1):
            y = top + h - h * i / steps
            p.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine))
            p.drawLine(left, int(y), left + w, int(y))
            p.setPen(QColor(theme.MUTED))
            axis_label = self._format_axis_val(y_min + y_span * i / steps)
            p.drawText(
                QRectF(0, y - 8, left - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                axis_label,
            )

        if self._total_n == 0:
            p.end()
            return

        x_start = self._x_start
        x_span = max(0.5, self._x_span)
        slot = w / x_span
        bw = max(5.0, min(38.0, slot * 0.58))

        first_i = max(0, int(x_start) - 1)
        last_i = min(self._total_n, int(x_start + x_span) + 2)
        vis_approx = max(1, round(x_span))
        label_step = 1 if vis_approx <= 14 else (2 if vis_approx <= 22 else 3)

        # Клиппинг области столбцов для плавного скролла/зума без вылезания за оси
        p.save()
        p.setClipRect(QRectF(left, top, w, h))
        for orig_i in range(first_i, last_i):
            cx = left + (orig_i + 0.5 - x_start) * slot
            is_hovered = orig_i == self._hovered_index

            if is_hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(245, 138, 46, 26))
                p.drawRoundedRect(QRectF(cx - slot / 2 + 2, top, slot - 4, h), 6, 6)

            for value, color, is_sales in (
                (self.purchases[orig_i], theme.ACCENT_SOFT, False),
                (self.sales[orig_i], theme.ACCENT, True),
            ):
                val_f = float(value)
                if val_f <= y_min:
                    continue
                norm = (val_f - y_min) / y_span
                bh = max(3.0, h * norm)
                y_top = top + h - bh
                rect = QRectF(cx - bw / 2, y_top, bw, bh + 6)
                if is_hovered and is_sales:
                    p.setPen(QPen(QColor(theme.NAVY), 1.5))
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawRoundedRect(rect, 5, 5)
        p.restore()

        # Подписи оси X
        p.save()
        p.setClipRect(QRectF(left - 18, top + h, w + 36, 24))
        for orig_i in range(first_i, last_i):
            cx = left + (orig_i + 0.5 - x_start) * slot
            if cx < left - 12 or cx > left + w + 12:
                continue
            is_hovered = orig_i == self._hovered_index
            if orig_i % label_step == 0 or is_hovered:
                lbl_font = QFont(font)
                lbl_font.setBold(is_hovered)
                p.setFont(lbl_font)
                p.setPen(QColor(theme.NAVY if is_hovered else theme.MUTED))
                p.drawText(
                    QRectF(cx - max(slot, 38) / 2, top + h + 5, max(slot, 38), 16),
                    Qt.AlignmentFlag.AlignCenter,
                    self.labels[orig_i],
                )
                p.setFont(font)
        p.restore()

        # Всплывающее окно сверху диаграммы при наведении на столбец
        if 0 <= self._hovered_index < self._total_n and first_i <= self._hovered_index < last_i:
            self._draw_hover_popup(p, left, w, slot, self._hovered_index, self._hovered_index - x_start)
        else:
            hint_font = QFont(font)
            hint_font.setPointSizeF(8.2)
            p.setFont(hint_font)
            p.setPen(QColor(theme.MUTED))
            if self._is_zoomed():
                zoom_hint = (
                    f"Masştab {self.zoom_percent_label()} • Çekip süýşür (X/Y) • "
                    "Shift+Tigir (Y) • Ctrl+Tigir (X) • 2× bas: 100%"
                )
            else:
                zoom_hint = "Tigir: tekiz 2D zum (X+Y) • Shift+Tigir: Y • Ctrl+Tigir: X • 2× bas: 100%"
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
        rel_idx: float | None = None,
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


# ---------------------------------------------------------------------------
# Базовые компоненты дизайн-системы (шаг 2). Старые классы выше не изменены.
# ---------------------------------------------------------------------------

_ICON_COLORS = {
    "primary": theme.WHITE,
    "success": theme.WHITE,
    "dark": theme.WHITE,
    "danger": theme.RED,
    "ghost": theme.TEXT_NAV,
    "secondary": theme.NAVY,
    "link": theme.ACCENT,
}


def make_icon_button(
    text: str,
    icon_key: str,
    variant: str = "secondary",
    size: str = "md",
) -> QPushButton:
    """Кнопка с векторной иконкой вместо эмодзи. size: 'sm' | 'md' | 'lg'."""
    from app.ui.icons import icon_size as _icon_size
    from app.ui.icons import make_icon

    btn = make_button(text, "secondary" if variant == "ghost" else variant)
    if variant == "ghost":
        btn.setObjectName("ghostBtn")
    if size in ("sm", "lg"):
        btn.setProperty("btnSize", size)
    px = 14 if size == "sm" else 20 if size == "lg" else 17
    btn.setIcon(make_icon(icon_key, _ICON_COLORS.get(variant, theme.NAVY), px))
    btn.setIconSize(_icon_size(px))
    return btn


class StatusBadge(QLabel):
    """Компактный статус: tone = neutral | success | warning | danger | info | accent."""

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setObjectName("statusBadge")
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        style = self.style()
        style.unpolish(self)
        style.polish(self)


class InlineAlert(QFrame):
    """Встроенное предупреждение (не модальное). tone = info | warning | danger.

    Используется вместо QMessageBox для некритичных предупреждений:
    скрыто по умолчанию, `show_message()` показывает, `clear()` прячет.
    """

    _ICONS: ClassVar[dict[str, str]] = {"info": "info", "warning": "warning", "danger": "warning"}
    _COLORS: ClassVar[dict[str, str]] = {"info": "#1D4ED8", "warning": "#B45309", "danger": theme.DANGER_TEXT}

    def __init__(self, tone: str = "warning") -> None:
        super().__init__()
        self.setObjectName("inlineAlert")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        self._text = QLabel()
        self._text.setObjectName("inlineAlertText")
        self._text.setWordWrap(True)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._text, 1)
        self.set_tone(tone)
        self.hide()

    def set_tone(self, tone: str) -> None:
        from app.ui.icons import make_icon

        self._tone = tone
        self.setProperty("tone", tone)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        color = self._COLORS.get(tone, theme.MUTED)
        self._icon.setPixmap(make_icon(self._ICONS.get(tone, "info"), color, 18).pixmap(QSize(18, 18)))

    def show_message(self, message: str, tone: str | None = None) -> None:
        if tone and tone != self._tone:
            self.set_tone(tone)
        self._text.setText(message)
        self.setVisible(bool(message))

    def clear(self) -> None:
        self._text.clear()
        self.hide()


class StatCard(Card):
    """Единая карточка показателя: подпись, значение, необязательные подсказка и значок-иконка.

    Заменяет ColorStatCard / KpiCard / make_stat_card при миграции страниц.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str = "",
        subtitle: str = "",
        icon_key: str | None = None,
        color: str = theme.NAVY,
        clickable: bool = False,
    ) -> None:
        super().__init__(margins=(16, 12, 16, 12), spacing=4)
        self._clickable = clickable
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("mutedText")
        top.addWidget(self.title_label, 1)
        if icon_key:
            from app.ui.icons import make_icon

            icon_lbl = QLabel()
            icon_lbl.setPixmap(make_icon(icon_key, color, 18).pixmap(QSize(18, 18)))
            top.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: {theme.FS_KPI}pt; font-weight: 700;"
        )
        self.body.addWidget(self.value_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet(f"color: {theme.MUTED}; font-size: {theme.FS_CAPTION}pt;")
        self.subtitle_label.setVisible(bool(subtitle))
        self.body.addWidget(self.subtitle_label)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, value: str, subtitle: str | None = None) -> None:
        self.value_label.setText(value)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)
            self.subtitle_label.setVisible(bool(subtitle))

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


NUM_ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def align_numeric_columns(table: QTableWidget, cols: list[int] | tuple[int, ...]) -> None:
    """Выравнивает заголовки числовых/денежных колонок вправо (ячейки задаются через NUM_ALIGN)."""
    for col in cols:
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setTextAlignment(NUM_ALIGN)
