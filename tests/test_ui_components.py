"""Смоук-тест базовых компонентов дизайн-системы (offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui import icons, theme
from app.ui.widgets import InlineAlert, StatCard, StatusBadge, make_icon_button


def _app():
    return QApplication.instance() or QApplication([])


def test_all_icons_render_non_empty():
    _app()
    keys = list(icons._SHAPES) + sorted(icons.NAV_KEYS)
    for key in keys:
        pm = icons.make_icon(key, theme.NAVY, 18).pixmap(18, 18)
        assert not pm.isNull(), key
        img = pm.toImage()
        assert any(
            img.pixelColor(x, y).alpha() > 0 for x in range(img.width()) for y in range(img.height())
        ), key


def test_icon_button_variants():
    _app()
    for variant in ("primary", "secondary", "danger", "success", "dark", "ghost", "link"):
        btn = make_icon_button("Test", "plus", variant)
        assert not btn.icon().isNull()
    assert make_icon_button("x", "plus", "primary", "sm").property("btnSize") == "sm"


def test_badge_alert_statcard():
    _app()
    badge = StatusBadge("ok", "success")
    badge.set_tone("danger")
    assert badge.property("tone") == "danger"

    alert = InlineAlert()
    alert.show_message("Bahasy pes", "warning")
    assert not alert.isHidden()
    alert.clear()
    assert alert.isHidden()

    card = StatCard("Satyş", "10", "sub", icon_key="sales", clickable=True)
    card.set_value("20", "")
    assert card.value_label.text() == "20"
    assert card.subtitle_label.isHidden()


def test_barchart_smooth_2d_zoom_and_reset():
    _app()
    from app.ui.widgets import BarChart

    chart = BarChart(
        labels=[f"D{i}" for i in range(12)],
        purchases=[10.0 * i for i in range(12)],
        sales=[20.0 * i for i in range(12)],
        y_max=240.0,
    )
    orig_x_span = chart._tx_span
    orig_y_span = chart._ty_max - chart._ty_min

    # Одновременный 2D зум по обеим осям
    chart.zoom_in(anchor_x=0.5, anchor_y=0.5, zoom_x=True, zoom_y=True)
    assert chart._tx_span < orig_x_span
    assert (chart._ty_max - chart._ty_min) < orig_y_span

    # Сброс к 100%
    chart.reset_zoom()
    assert chart._tx_span == orig_x_span
    assert chart._ty_min == 0.0
    assert chart._ty_max == chart.base_y_max


def test_table_layout_presets():
    _app()
    from PySide6.QtWidgets import QTableWidget

    from app.ui.widgets import apply_table_preset, configure_table

    tbl = QTableWidget(1, 3)
    tbl.setHorizontalHeaderLabels(["ID", "Ady", "Jemi"])
    configure_table(tbl, stretch_col=1)
    for mode in ("auto_fit", "wrap_full", "compact", "wide_scroll"):
        apply_table_preset(tbl, [1], 46, preset=mode)
    assert tbl.columnCount() == 3
