import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from app.services.backup_service import BackupService
from app.services.mobile_ws_server import MobileWebSocketServer
from app.services.settings_service import SettingsService
from app.services.update_service import UpdateService
from app.ui import theme
from app.ui.widgets import Card, configure_table, make_button, show_toast, style_combo


class SettingsPage(QWidget):
    """Модуль «Настройки, Резервное копирование и Мобильный сканер»."""

    def __init__(self, mobile_server: MobileWebSocketServer | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.mobile_server = mobile_server
        self.backups_list: list[dict] = []

        self._build_ui()
        if self.mobile_server is not None:
            self.mobile_server.devicesChanged.connect(self._update_mobile_devices_table)
            self.mobile_server.activityLogged.connect(self._append_mobile_log)
            self.mobile_server.serverStateChanged.connect(self._on_mobile_server_state_changed)
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Ulgam sazlamalary we ätiýaçlyk nusga")
        title.setObjectName("pageTitle")
        sub = QLabel(
            "Dükanyň profili, hasap we çek sazlamalary, maglumat bazasynyň ätiýaçlyk nusgalary"
        )
        sub.setObjectName("mutedText")
        col.addWidget(title)
        col.addWidget(sub)
        header.addLayout(col, 1)

        refresh_btn = make_button("↻  Täzele")
        refresh_btn.clicked.connect(self.refresh_data)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_general_settings_tab(), "Dükan we hasap sazlamalary")
        self.tabs.addTab(self._create_backup_tab(), "Ätiýaçlyk nusga we bazany dikeltmek")
        self.tabs.addTab(self._create_mobile_scanner_tab(), "📱 Mobil skaner (Android)")
        root.addWidget(self.tabs, 1)

    def _create_general_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(18)

        store_card = Card()
        sl = store_card.body
        st_title = QLabel("Dükan profili we çek sazlamalary")
        st_title.setObjectName("cardTitle")
        sl.addWidget(st_title)

        s_form = QFormLayout()
        s_form.setSpacing(12)

        self.store_name_input = QLineEdit()
        self.store_name_input.setMinimumHeight(36)
        self.store_phone_input = QLineEdit()
        self.store_phone_input.setMinimumHeight(36)
        self.store_address_input = QLineEdit()
        self.store_address_input.setMinimumHeight(36)
        self.receipt_footer_input = QLineEdit()
        self.receipt_footer_input.setMinimumHeight(36)

        s_form.addRow("Dükanyň ady:", self.store_name_input)
        s_form.addRow("Habarlaşmak telefony:", self.store_phone_input)
        s_form.addRow("Dükanyň salgysy:", self.store_address_input)
        s_form.addRow("Çekiň aşagyndaky ýazgy:", self.receipt_footer_input)
        sl.addLayout(s_form)
        sl.addStretch()

        acc_card = Card()
        al = acc_card.body
        ac_title = QLabel("Hasap, walýuta we sklad sazlamalary")
        ac_title.setObjectName("cardTitle")
        al.addWidget(ac_title)

        a_form = QFormLayout()
        a_form.setSpacing(12)

        self.default_curr_combo = style_combo(QComboBox())
        self.default_curr_combo.setMinimumHeight(36)
        self.default_curr_combo.addItems(["TMT", "USD"])

        self.default_rate_spin = QDoubleSpinBox()
        self.default_rate_spin.setMinimumHeight(36)
        self.default_rate_spin.setRange(0.0001, 100000)
        self.default_rate_spin.setDecimals(4)
        self.default_rate_spin.setValue(19.5)

        self.min_stock_spin = QSpinBox()
        self.min_stock_spin.setMinimumHeight(36)
        self.min_stock_spin.setRange(0, 10000)
        self.min_stock_spin.setValue(2)

        self.date_format_combo = style_combo(QComboBox())
        self.date_format_combo.setMinimumHeight(36)
        self.date_format_combo.addItem("GG.AA.ÝÝÝÝ SS:MM (19.11.2026 14:30)", "%d.%m.%Y %H:%M")
        self.date_format_combo.addItem("ÝÝÝÝ-AA-GG SS:MM (2026-11-19 14:30)", "%Y-%m-%d %H:%M")

        a_form.addRow("Esasy çek walýutasy:", self.default_curr_combo)
        a_form.addRow("Esasy kurs (1 USD = X TMT):", self.default_rate_spin)
        a_form.addRow("Esasy az galyndy çägi (sany):", self.min_stock_spin)
        a_form.addRow("Sene görkeziş formaty:", self.date_format_combo)
        al.addLayout(a_form)

        al.addStretch()
        save_btn = make_button("💾  Sazlamalary ýatda sakla", "primary")
        save_btn.setMinimumHeight(42)
        save_btn.clicked.connect(self._save_general_settings)
        al.addWidget(save_btn)

        layout.addWidget(store_card, 1)
        layout.addWidget(acc_card, 1)
        return widget

    def _create_backup_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        cfg_card = Card(margins=(18, 14, 18, 14), spacing=10)
        cl = cfg_card.body

        top_row = QHBoxLayout()
        t = QLabel("SQLite ätiýaçlyk nusga dolandyryşy")
        t.setObjectName("cardTitle")
        top_row.addWidget(t, 1)

        self.last_backup_label = QLabel("Soňky nusga: —")
        self.last_backup_label.setStyleSheet(f"font-weight: 600; color: {theme.TEAL};")
        top_row.addWidget(self.last_backup_label)
        cl.addLayout(top_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Nusga saklanýan bukja:"))
        self.backup_dir_input = QLineEdit()
        self.backup_dir_input.setMinimumHeight(36)
        dir_row.addWidget(self.backup_dir_input, 1)
        browse_dir_btn = make_button("Bukja saýla…")
        browse_dir_btn.setMinimumHeight(36)
        browse_dir_btn.clicked.connect(self._choose_backup_dir)
        dir_row.addWidget(browse_dir_btn)
        cl.addLayout(dir_row)

        policy_row = QHBoxLayout()
        self.auto_backup_chk = QCheckBox("Awtomatiki ätiýaçlyk nusgany aç")
        policy_row.addWidget(self.auto_backup_chk)

        policy_row.addWidget(QLabel("Ýygylyk:"))
        self.freq_combo = style_combo(QComboBox())
        self.freq_combo.setMinimumHeight(36)
        self.freq_combo.addItem("Her gün (günüň ilkinji açylyşynda)", "daily")
        self.freq_combo.addItem("Programma her açylanda", "on_startup")
        self.freq_combo.addItem("Diňe el bilen", "manual")
        policy_row.addWidget(self.freq_combo)

        policy_row.addWidget(QLabel("Soňky nusgalary sakla:"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setMinimumHeight(36)
        self.retention_spin.setRange(1, 200)
        self.retention_spin.setValue(15)
        policy_row.addWidget(self.retention_spin)

        save_policy_btn = make_button("Düzgüni ýatda sakla")
        save_policy_btn.setMinimumHeight(36)
        save_policy_btn.clicked.connect(self._save_backup_policy)
        policy_row.addWidget(save_policy_btn)
        cl.addLayout(policy_row)

        actions_row = QHBoxLayout()
        create_now_btn = make_button("➕ Häzir ätiýaçlyk nusga döret", "primary")
        create_now_btn.setMinimumHeight(40)
        create_now_btn.clicked.connect(self._create_manual_backup)
        actions_row.addWidget(create_now_btn)

        verify_btn = make_button("✔ Saýlanan nusgany barla")
        verify_btn.setMinimumHeight(40)
        verify_btn.clicked.connect(self._verify_selected_backup)
        actions_row.addWidget(verify_btn)

        restore_file_btn = make_button("📂 Daşarky faýldan dikelt…")
        restore_file_btn.setMinimumHeight(40)
        restore_file_btn.clicked.connect(self._restore_from_external_file)
        actions_row.addWidget(restore_file_btn)

        restore_selected_btn = make_button("⚠ Saýlanan nusgany dikelt", "danger")
        restore_selected_btn.setMinimumHeight(40)
        restore_selected_btn.clicked.connect(self._restore_selected_backup)
        actions_row.addWidget(restore_selected_btn)

        update_zip_btn = make_button("⬆ Programmany täzele (ZIP)")
        update_zip_btn.setMinimumHeight(40)
        update_zip_btn.setToolTip(
            "Täze Windows ZIP wersiýasyndan maglumat bazasyny we ätiýaçlyk nusgalary saklap täzelemek"
        )
        update_zip_btn.clicked.connect(self._update_from_zip)
        actions_row.addWidget(update_zip_btn)

        cl.addLayout(actions_row)
        layout.addWidget(cfg_card)

        self.backups_table = QTableWidget(0, 4)
        self.backups_table.setHorizontalHeaderLabels([
            "Ätiýaçlyk nusga faýlynyň ady",
            "Döredilen senesi",
            "Ölçegi (KB)",
            "Doly ýoly",
        ])
        configure_table(self.backups_table)
        self.backups_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.backups_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.backups_table, 1)

        return widget

    def _create_mobile_scanner_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        top_split = QHBoxLayout()
        top_split.setSpacing(16)

        cfg_card = Card(margins=(18, 14, 18, 14), spacing=10)
        cl = cfg_card.body

        title_row = QHBoxLayout()
        t = QLabel("Ýerli sinhronizasiýa serweri (Wi-Fi / LAN)")
        t.setObjectName("cardTitle")
        title_row.addWidget(t, 1)

        self.ws_status_label = QLabel("● Duruzyldy")
        self.ws_status_label.setStyleSheet(f"font-weight: 700; color: {theme.MUTED};")
        title_row.addWidget(self.ws_status_label)
        cl.addLayout(title_row)

        self.ws_urls_label = QLabel("Birikme salgysy: —")
        self.ws_urls_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ws_urls_label.setWordWrap(True)
        self.ws_urls_label.setStyleSheet(
            f"padding: 8px 10px; border-radius: 8px; background: #F1F5F9; "
            f"color: {theme.TEXT}; font-family: monospace; font-weight: 600;"
        )
        cl.addWidget(self.ws_urls_label)

        form = QFormLayout()
        form.setSpacing(10)

        self.ws_enabled_chk = QCheckBox("MobileStore açylanda serweri awtomatiki başlat")
        form.addRow("", self.ws_enabled_chk)

        self.ws_port_spin = QSpinBox()
        self.ws_port_spin.setMinimumHeight(36)
        self.ws_port_spin.setRange(1024, 65535)
        self.ws_port_spin.setValue(8765)
        form.addRow("WebSocket porty (TCP):", self.ws_port_spin)

        token_row = QHBoxLayout()
        self.ws_token_input = QLineEdit()
        self.ws_token_input.setMinimumHeight(36)
        self.ws_token_input.setPlaceholderText("6 sanly PIN / giriş kody")
        self.ws_token_input.setStyleSheet("font-family: monospace; font-weight: 700; font-size: 11pt;")
        token_row.addWidget(self.ws_token_input, 1)

        regen_btn = make_button("🔄 Täze PIN")
        regen_btn.setMinimumHeight(36)
        regen_btn.clicked.connect(self._regenerate_mobile_token)
        token_row.addWidget(regen_btn)
        form.addRow("Giriş PIN kody:", token_row)
        cl.addLayout(form)

        fw_hint = QLabel(
            "Maslahat: kompýuter we Android telefonlar bir Wi-Fi ulgamynda bolmaly. "
            "Internet gerek däl. Telefon birikmese, brandmauerdäki TCP portuna rugsat beriň."
        )
        fw_hint.setWordWrap(True)
        fw_hint.setObjectName("mutedText")
        cl.addWidget(fw_hint)

        btn_row = QHBoxLayout()
        save_ws_btn = make_button("💾 Ýatda sakla we täzeden başlat", "primary")
        save_ws_btn.setMinimumHeight(38)
        save_ws_btn.clicked.connect(self._save_and_restart_mobile_server)
        btn_row.addWidget(save_ws_btn)

        copy_url_btn = make_button("📋 Salgyny göçür")
        copy_url_btn.setMinimumHeight(38)
        copy_url_btn.clicked.connect(self._copy_mobile_url)
        btn_row.addWidget(copy_url_btn)

        stop_ws_btn = make_button("⏹ Duruz")
        stop_ws_btn.setMinimumHeight(38)
        stop_ws_btn.clicked.connect(self._stop_mobile_server)
        btn_row.addWidget(stop_ws_btn)

        disconnect_all_btn = make_button("✕ Ählisini aýyr", "danger")
        disconnect_all_btn.setMinimumHeight(38)
        disconnect_all_btn.clicked.connect(self._disconnect_all_mobile_devices)
        btn_row.addWidget(disconnect_all_btn)
        cl.addLayout(btn_row)

        top_split.addWidget(cfg_card, 3)

        log_card = Card(margins=(18, 14, 18, 14), spacing=8)
        ll = log_card.body
        log_hdr = QHBoxLayout()
        lt = QLabel("Birikmeler we skanirlemeler žurnaly")
        lt.setObjectName("cardTitle")
        log_hdr.addWidget(lt, 1)
        clear_log_btn = make_button("Arassala")
        clear_log_btn.clicked.connect(lambda: self.ws_log_view.clear())
        log_hdr.addWidget(clear_log_btn)
        ll.addLayout(log_hdr)

        self.ws_log_view = QPlainTextEdit()
        self.ws_log_view.setReadOnly(True)
        self.ws_log_view.setMaximumBlockCount(200)
        self.ws_log_view.setStyleSheet(
            "font-family: monospace; font-size: 9pt; background: #0F172A; color: #E2E8F0; "
            "border-radius: 8px; padding: 8px;"
        )
        ll.addWidget(self.ws_log_view, 1)

        top_split.addWidget(log_card, 2)
        layout.addLayout(top_split, 1)

        dev_card = Card(margins=(18, 12, 18, 12), spacing=8)
        dl = dev_card.body
        dt = QLabel("Birikdirilen telefonlar (bir wagtda birnäçe enjam goldanýar)")
        dt.setObjectName("cardTitle")
        dl.addWidget(dt)

        self.ws_devices_table = QTableWidget(0, 6)
        self.ws_devices_table.setHorizontalHeaderLabels([
            "Enjam",
            "IP-salgy",
            "Status",
            "Wersiýa",
            "Birikdi",
            "Soňky işjeňlik",
        ])
        configure_table(self.ws_devices_table, stretch_col=0, row_height=38)
        dl.addWidget(self.ws_devices_table)
        layout.addWidget(dev_card, 1)

        return widget

    def refresh_data(self) -> None:
        cfg = SettingsService.get_all()

        self.store_name_input.setText(cfg.get("store_name", ""))
        self.store_phone_input.setText(cfg.get("store_phone", ""))
        self.store_address_input.setText(cfg.get("store_address", ""))
        self.receipt_footer_input.setText(cfg.get("receipt_footer", ""))

        self.default_curr_combo.setCurrentText(cfg.get("default_currency", "TMT"))
        self.default_rate_spin.setValue(float(SettingsService.get_default_exchange_rate()))
        self.min_stock_spin.setValue(SettingsService.get_default_min_stock())

        df_idx = self.date_format_combo.findData(cfg.get("date_format", "%d.%m.%Y %H:%M"))
        if df_idx >= 0:
            self.date_format_combo.setCurrentIndex(df_idx)

        self.backup_dir_input.setText(cfg.get("backup_directory", ""))
        self.auto_backup_chk.setChecked(cfg.get("auto_backup_enabled", "1") == "1")

        fr_idx = self.freq_combo.findData(cfg.get("auto_backup_frequency", "daily"))
        if fr_idx >= 0:
            self.freq_combo.setCurrentIndex(fr_idx)

        try:
            self.retention_spin.setValue(max(1, int(cfg.get("backup_retention_count", "15"))))
        except ValueError:
            self.retention_spin.setValue(15)

        last_at = cfg.get("last_backup_at") or "entek döredilmedi"
        self.last_backup_label.setText(f"Soňky nusga: {last_at}")

        self._refresh_mobile_scanner_tab(cfg)
        self._reload_backups_table()

    def _refresh_mobile_scanner_tab(self, cfg: dict[str, str] | None = None) -> None:
        if cfg is None:
            cfg = SettingsService.get_all()
        self.ws_enabled_chk.setChecked(cfg.get("mobile_server_enabled", "1") == "1")
        self.ws_port_spin.setValue(SettingsService.get_mobile_server_port())
        self.ws_token_input.setText(SettingsService.get_or_create_mobile_token())

        port = self.mobile_server.port if self.mobile_server is not None else self.ws_port_spin.value()
        ips = MobileWebSocketServer.get_local_ips()
        urls_text = "   |   ".join(f"ws://{ip}:{port}" for ip in ips)
        self.ws_urls_label.setText(f"Ýerli Wi-Fi ulgamyndaky salgy:  {urls_text}")

        if self.mobile_server is not None:
            running = self.mobile_server.is_running()
            self._on_mobile_server_state_changed(
                running,
                f"Port {port}-de işleýär" if running else "Duruzyldy",
            )
            self._update_mobile_devices_table(self.mobile_server.get_connected_devices())
            recent = self.mobile_server.get_recent_logs()
            self.ws_log_view.setPlainText("\n".join(recent))
        else:
            self.ws_status_label.setText("● Başladylmady")

    def _on_mobile_server_state_changed(self, running: bool, _message: str) -> None:
        if running:
            port = self.mobile_server.port if self.mobile_server is not None else self.ws_port_spin.value()
            self.ws_status_label.setText(f"● Serwer işleýär (port {port})")
            self.ws_status_label.setStyleSheet(f"font-weight: 700; color: {theme.GREEN};")
            ips = MobileWebSocketServer.get_local_ips()
            urls_text = "   |   ".join(f"ws://{ip}:{port}" for ip in ips)
            self.ws_urls_label.setText(f"Ýerli Wi-Fi ulgamyndaky salgy:  {urls_text}")
        else:
            self.ws_status_label.setText("● Serwer duruzyldy")
            self.ws_status_label.setStyleSheet(f"font-weight: 700; color: {theme.RED};")

    def _update_mobile_devices_table(self, devices: list[dict]) -> None:
        self.ws_devices_table.setRowCount(len(devices))
        for i, dev in enumerate(devices):
            status_text = "✔ Tassyklandy" if dev.get("authenticated") else "⏳ PIN garaşylýar"
            vals = [
                dev.get("device_name") or "—",
                dev.get("ip") or "—",
                status_text,
                dev.get("app_version") or "—",
                dev.get("connected_at") or "—",
                dev.get("last_seen") or "—",
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (1, 2, 3, 4, 5):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.ws_devices_table.setItem(i, c, cell)

    def _append_mobile_log(self, line: str) -> None:
        current = self.ws_log_view.toPlainText()
        if current:
            self.ws_log_view.setPlainText(f"{line}\n{current}")
        else:
            self.ws_log_view.setPlainText(line)

    def _regenerate_mobile_token(self) -> None:
        new_pin = SettingsService.regenerate_mobile_token()
        self.ws_token_input.setText(new_pin)
        if self.mobile_server is not None:
            self.mobile_server.disconnect_all()
        show_toast(
            self,
            f"Täze PIN kod döredildi: {new_pin}. Telefonlarda täze PIN giriziň.",
            kind="success",
            duration_ms=4500,
        )

    def _save_and_restart_mobile_server(self) -> None:
        token = self.ws_token_input.text().strip()
        if len(token) < 4:
            QMessageBox.warning(
                self,
                "Gysga PIN kod",
                "Azyndan 4 simwoldan ybarat PIN kod giriziň.",
            )
            return
        port = self.ws_port_spin.value()
        enabled = self.ws_enabled_chk.isChecked()
        try:
            SettingsService.set_many({
                "mobile_server_enabled": "1" if enabled else "0",
                "mobile_server_port": str(port),
                "mobile_server_token": token,
            })
        except SQLAlchemyError as e:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Serwer sazlamalaryny ýatda saklap bolmady:\n{e}")
            return

        if self.mobile_server is None:
            show_toast(self, "Serwer sazlamalary ýatda saklandy.", kind="success")
            return
        if enabled:
            ok, msg = self.mobile_server.restart(port=port)
            if ok:
                show_toast(self, f"Serwer başlady: {msg}", kind="success")
            else:
                QMessageBox.warning(self, "Serwer başlatma ýalňyşlygy", msg)
        else:
            self.mobile_server.stop()
            show_toast(self, "Mobil skaneriň ýerli serweri öçürildi.", kind="info")
        self._refresh_mobile_scanner_tab()

    def _stop_mobile_server(self) -> None:
        if self.mobile_server is not None:
            self.mobile_server.stop()
            self._refresh_mobile_scanner_tab()
            show_toast(self, "Mobil skaner serweri duruzyldy.", kind="info")

    def _disconnect_all_mobile_devices(self) -> None:
        if self.mobile_server is not None:
            self.mobile_server.disconnect_all()
            show_toast(self, "Ähli birikdirilen enjamlar aýryldy.", kind="info")

    def _copy_mobile_url(self) -> None:
        port = self.mobile_server.port if self.mobile_server is not None else self.ws_port_spin.value()
        ips = MobileWebSocketServer.get_local_ips()
        url = f"ws://{ips[0]}:{port}"
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(url)
        show_toast(self, f"Salgy göçürildi: {url}", kind="success")

    def _reload_backups_table(self) -> None:
        b_dir = self.backup_dir_input.text().strip() or None
        self.backups_list = BackupService.list_backups(b_dir)
        self.backups_table.setRowCount(len(self.backups_list))

        for i, b in enumerate(self.backups_list):
            d_str = b["modified_at"].strftime("%d.%m.%Y %H:%M:%S")
            vals = [
                b["name"],
                d_str,
                f"{b['size_kb']:,.1f} KB",
                str(b["path"]),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c in (1, 2):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.backups_table.setItem(i, c, cell)

    def _save_general_settings(self) -> None:
        values = {
            "store_name": self.store_name_input.text().strip() or "MobileStore",
            "store_phone": self.store_phone_input.text().strip(),
            "store_address": self.store_address_input.text().strip(),
            "receipt_footer": self.receipt_footer_input.text().strip(),
            "default_currency": self.default_curr_combo.currentText(),
            "default_exchange_rate": f"{self.default_rate_spin.value():.4f}",
            "default_min_stock_quantity": str(self.min_stock_spin.value()),
            "date_format": self.date_format_combo.currentData(),
        }
        try:
            SettingsService.set_many(values)
            self.refresh_data()
            show_toast(self, "Dükan we hasap sazlamalary üstünlikli ýatda saklandy.", kind="success")
        except SQLAlchemyError as e:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Sazlamalary ýatda saklap bolmady:\n{e}")

    def _choose_backup_dir(self) -> None:
        cur_dir = self.backup_dir_input.text().strip() or str(BackupService.get_backup_directory())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Ätiýaçlyk nusgalar üçin bukja saýlaň",
            cur_dir,
        )
        if folder:
            self.backup_dir_input.setText(folder)
            self._save_backup_policy(silent=True)
            self._reload_backups_table()

    def _save_backup_policy(self, silent: bool = False) -> None:
        b_dir = self.backup_dir_input.text().strip() or str(BackupService.get_backup_directory())
        values = {
            "backup_directory": b_dir,
            "auto_backup_enabled": "1" if self.auto_backup_chk.isChecked() else "0",
            "auto_backup_frequency": self.freq_combo.currentData(),
            "backup_retention_count": str(self.retention_spin.value()),
        }
        try:
            SettingsService.set_many(values)
            BackupService.enforce_retention_policy(b_dir)
            self.refresh_data()
            if not silent:
                show_toast(self, "Ätiýaçlyk nusga düzgüni ýatda saklandy.", kind="success")
        except (OSError, SQLAlchemyError) as e:
            QMessageBox.critical(self, "Ýalňyşlyk", f"Düzgüni ýatda saklap bolmady:\n{e}")

    def _create_manual_backup(self) -> None:
        self._save_backup_policy(silent=True)
        b_dir = self.backup_dir_input.text().strip() or None
        try:
            created = BackupService.create_backup(target_dir=b_dir, apply_retention=True)
            self.refresh_data()
            show_toast(
                self,
                f"Ätiýaçlyk nusga döredildi: {Path(created).name}",
                kind="success",
                duration_ms=4000,
            )
        except (OSError, ValueError, sqlite3.Error) as e:
            QMessageBox.critical(self, "Nusga döretme ýalňyşlygy", str(e))

    def _verify_selected_backup(self) -> None:
        row = self.backups_table.currentRow()
        if not (0 <= row < len(self.backups_list)):
            show_toast(self, "Barlamak üçin tablisadan ätiýaçlyk nusgany saýlaň.", kind="info")
            return
        path = self.backups_list[row]["path"]
        ok, msg = BackupService.verify_backup(path)
        if ok:
            show_toast(
                self,
                f"Barlag üstünlikli ({path.name}): {msg}",
                kind="success",
                duration_ms=4000,
            )
        else:
            QMessageBox.warning(
                self,
                "Barlag ýalňyşlygy",
                f"Faýl: {path.name}\n{msg}",
            )

    def _restore_selected_backup(self) -> None:
        row = self.backups_table.currentRow()
        if not (0 <= row < len(self.backups_list)):
            show_toast(self, "Dikeltmek üçin tablisadan ätiýaçlyk nusgany saýlaň.", kind="info")
            return
        path = self.backups_list[row]["path"]
        self._confirm_and_restore(path)

    def _restore_from_external_file(self) -> None:
        cur_dir = self.backup_dir_input.text().strip() or str(BackupService.get_backup_directory())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "SQLite ätiýaçlyk nusga faýlyny saýlaň",
            cur_dir,
            "SQLite Database (*.db *.sqlite)",
        )
        if file_path:
            self._confirm_and_restore(Path(file_path))

    def _confirm_and_restore(self, backup_path: Path) -> None:
        ok, msg = BackupService.verify_backup(backup_path)
        if not ok:
            QMessageBox.critical(
                self,
                "Faýl zeperlenen ýa-da gabat gelmeýär",
                f"Saýlanan faýl barlagdan geçmedi:\n{msg}",
            )
            return

        confirm = QMessageBox.warning(
            self,
            "Maglumat bazasyny dikeltmegi tassyklamak",
            f"Häzirki işjeň bazany şu nusga bilen çalyşmak isleýärsiňiz:\n"
            f"«{backup_path.name}»\n\n"
            f"Faýl barlagy: {msg}\n\n"
            "Dikeltmezden öň häzirki bazanyň ätiýaçlyk nusgasy awtomatiki dörediler "
            "(pre_restore_safety_*.db).\n\n"
            "Dikeltmegi dowam etdirmelimi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            safety = BackupService.restore_backup(backup_path, create_safety_backup=True)
            self.refresh_data()
            safety_note = f" (gorag nusgasy: {Path(safety).name})" if safety else ""
            show_toast(
                self,
                f"Maglumat bazasy «{backup_path.name}» faýlyndan dikeldildi{safety_note}.",
                kind="success",
                duration_ms=4500,
            )
        except (OSError, ValueError, sqlite3.Error) as e:
            QMessageBox.critical(
                self,
                "Dikeltme ýalňyşlygy",
                f"Maglumat bazasyny dikeldip bolmady:\n{e}",
            )

    def _update_from_zip(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Täze MobileStore Windows ZIP arhiwini saýlaň",
            str(Path.home()),
            "ZIP Archive (*.zip)",
        )
        if not file_path:
            return

        ok, msg, _prefix = UpdateService.inspect_update_zip(file_path)
        if not ok:
            QMessageBox.warning(self, "Nädogry täzeleme arhiwi", msg)
            return

        confirm = QMessageBox.question(
            self,
            "Programmany täzelemek",
            f"Saýlanan arhiw: {Path(file_path).name}\n\n"
            "• Maglumat bazasy (data/) we ätiýaçlyk nusgalar (backups/) SAKLANAR.\n"
            "• Täzelemekden öň awtomatiki gorag nusgasy (pre_update_*.db) dörediler.\n"
            "• Täzeleme tamamlanandan soň programma awtomatiki täzeden açylar.\n\n"
            "Dowam etmelimi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        launched, result_msg = UpdateService.prepare_and_launch_update(file_path)
        if launched:
            QMessageBox.information(self, "Täzeleme başlady", result_msg)
            app = QApplication.instance()
            if app is not None:
                app.quit()
        else:
            QMessageBox.information(self, "Täzeleme maglumaty", result_msg)
            self.refresh_data()
