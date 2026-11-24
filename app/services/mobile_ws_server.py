"""Локальный WebSocket-сервер MobileStore на базе PySide6.QtWebSockets (без внешних зависимостей)."""
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer

from app.services.mobile_protocol import MobileProtocolProcessor, make_error
from app.services.settings_service import SettingsService

logger = logging.getLogger("mobilestore.mobile_ws_server")

DATA_MUTATING_TYPES = {
    "product_create",
    "product_update",
    "category_create",
    "category_update",
    "category_deactivate",
    "receive_purchase",
    "queue_incoming_item",
}


class MobileWebSocketServer(QObject):
    """Встроенный WebSocket-сервер для подключения Android-смартфонов в локальной Wi-Fi сети."""

    devicesChanged = Signal(list)
    activityLogged = Signal(str)
    dataMutated = Signal(str)
    incomingQueued = Signal(dict)
    serverStateChanged = Signal(bool, str)

    def __init__(
        self,
        add_to_sale_callback: Callable[[dict[str, Any]], tuple[bool, str, dict[str, Any] | None]] | None = None,
        is_imei_in_cart_callback: Callable[[str], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.processor = MobileProtocolProcessor(
            add_to_sale_callback=add_to_sale_callback,
            is_imei_in_cart_callback=is_imei_in_cart_callback,
        )
        self._server = QWebSocketServer(
            "MobileStoreSyncServer",
            QWebSocketServer.SslMode.NonSecureMode,
            self,
        )
        self._server.newConnection.connect(self._on_new_connection)

        self._clients: dict[QWebSocket, dict[str, Any]] = {}
        self._recent_logs: list[str] = []
        self._port: int = SettingsService.get_mobile_server_port()

    @property
    def port(self) -> int:
        return self._port

    def is_running(self) -> bool:
        return self._server.isListening()

    def get_recent_logs(self) -> list[str]:
        return list(self._recent_logs)

    @staticmethod
    def get_local_ips() -> list[str]:
        """Возвращает локальные IPv4-адреса компьютера в Wi-Fi / LAN сети."""
        ips: list[str] = []
        for iface in QNetworkInterface.allInterfaces():
            flags = iface.flags()
            if not (flags & QNetworkInterface.InterfaceFlag.IsUp):
                continue
            if not (flags & QNetworkInterface.InterfaceFlag.IsRunning):
                continue
            if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
                continue
            for entry in iface.addressEntries():
                addr = entry.ip()
                if addr.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                    continue
                ip_str = addr.toString()
                if ip_str.startswith(("169.254.", "127.")):
                    continue
                if ip_str not in ips:
                    ips.append(ip_str)
        return ips or ["127.0.0.1"]

    def start(self, port: int | None = None) -> tuple[bool, str]:
        if self._server.isListening():
            self.stop()

        target_port = port if port is not None else SettingsService.get_mobile_server_port()
        SettingsService.get_or_create_mobile_token()

        ok = self._server.listen(QHostAddress.SpecialAddress.AnyIPv4, target_port)
        if not ok:
            err = self._server.errorString() or f"{target_port} portuny açyp bolmady"
            self._log(f"{target_port} portunda WebSocket serweri başlatma ýalňyşlygy: {err}")
            self.serverStateChanged.emit(False, err)
            return False, err

        self._port = self._server.serverPort()
        ips = ", ".join(f"ws://{ip}:{self._port}" for ip in self.get_local_ips())
        msg = f"Serwer başlady: {ips}"
        self._log(msg)
        self.serverStateChanged.emit(True, msg)
        return True, msg

    def stop(self) -> None:
        self.disconnect_all()
        if self._server.isListening():
            self._server.close()
            self._log("WebSocket serweri duruzyldy")
            self.serverStateChanged.emit(False, "Serwer duruzyldy")

    def restart(self, port: int | None = None) -> tuple[bool, str]:
        self.stop()
        return self.start(port)

    def disconnect_all(self) -> None:
        for sock in list(self._clients.keys()):
            try:
                sock.disconnected.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                sock.close()
            except RuntimeError:
                pass
        self._clients.clear()
        try:
            self.devicesChanged.emit([])
        except RuntimeError:
            pass

    def get_connected_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "device_id": info["device_id"],
                "device_name": info["device_name"],
                "ip": info["ip"],
                "connected_at": info["connected_at"],
                "last_seen": info["last_seen"],
                "app_version": info["app_version"],
                "authenticated": info["authenticated"],
            }
            for info in self._clients.values()
        ]

    def _log(self, text: str) -> None:
        if not text:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        self._recent_logs.insert(0, line)
        if len(self._recent_logs) > 200:
            self._recent_logs = self._recent_logs[:200]
        logger.info(text)
        try:
            self.activityLogged.emit(line)
        except RuntimeError:
            pass

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            if client is None:
                continue
            peer_ip = client.peerAddress().toString().removeprefix("::ffff:")

            now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            self._clients[client] = {
                "device_id": "",
                "device_name": "Tassyklama garaşylýar…",
                "ip": peer_ip,
                "connected_at": now_str,
                "last_seen": now_str,
                "app_version": "—",
                "authenticated": False,
            }
            client.textMessageReceived.connect(
                lambda msg, sock=client: self._on_text_message(sock, msg)
            )
            client.disconnected.connect(lambda sock=client: self._on_disconnected(sock))
            self._log(f"{peer_ip} salgydan täze birikme")
            self.devicesChanged.emit(self.get_connected_devices())

    def _on_disconnected(self, client: QWebSocket) -> None:
        info = self._clients.pop(client, None)
        try:
            client.deleteLater()
        except RuntimeError:
            pass
        if info:
            self._log(f"«{info['device_name']}» ({info['ip']}) telefony aýryldy")
        try:
            self.devicesChanged.emit(self.get_connected_devices())
        except RuntimeError:
            pass

    def _on_text_message(self, client: QWebSocket, raw_message: str) -> None:
        info = self._clients.get(client)
        if info is None:
            return

        info["last_seen"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        try:
            parsed = json.loads(raw_message)
        except json.JSONDecodeError:
            resp = make_error("", "INVALID_JSON", "Nädogry JSON paketi.")
            client.sendTextMessage(json.dumps(resp, ensure_ascii=False))
            self._log(f"{info['ip']} salgydan nädogry JSON")
            return

        msg_type = str(parsed.get("type") or "")
        if msg_type == "queue_incoming_item" and isinstance(parsed.get("payload"), dict):
            parsed["payload"].setdefault("device_name", info["device_name"])

        auth_count = sum(1 for c in self._clients.values() if c["authenticated"])
        response, log_line = self.processor.handle_message(
            message=parsed,
            is_authenticated=bool(info["authenticated"]),
            connected_count=auth_count + (0 if info["authenticated"] else 1),
        )
        if msg_type == "auth" and response.get("ok"):
            payload = parsed.get("payload") or {}
            dev_id = str(payload.get("device_id") or parsed.get("device_id") or "").strip()
            dev_name = str(payload.get("device_name") or "Android Scanner").strip()
            app_ver = str(payload.get("app_version") or "1.0").strip()

            # Закрываем устаревший сокет с тем же device_id при переподключении
            for other_sock, other_info in list(self._clients.items()):
                if other_sock is not client and other_info.get("device_id") == dev_id:
                    other_sock.close()

            info["device_id"] = dev_id
            info["device_name"] = dev_name
            info["app_version"] = app_ver
            info["authenticated"] = True
            self.devicesChanged.emit(self.get_connected_devices())

        client.sendTextMessage(json.dumps(response, ensure_ascii=False))

        if log_line:
            prefix = f"[{info['device_name']}] " if info["authenticated"] else f"[{info['ip']}] "
            self._log(prefix + log_line)

        if response.get("ok") and msg_type == "queue_incoming_item":
            self.incomingQueued.emit(response.get("data") or {})

        if response.get("ok") and msg_type in DATA_MUTATING_TYPES:
            self.dataMutated.emit(msg_type)
