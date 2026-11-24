package com.mobilestore.scanner.data

import android.content.Context
import android.os.Build
import java.util.UUID

data class ServerConfig(
    val host: String,
    val port: Int,
    val pinToken: String,
    val deviceId: String,
    val deviceName: String,
    val scanCooldownMs: Long = DEFAULT_SCAN_COOLDOWN_MS,
    val wifiSsid: String = "",
    val wifiPassword: String = "",
    val autoConnectWifiHub: Boolean = false,
) {
    val wsUrl: String
        get() {
            val (cleanHost, cleanPort) = normalizeHostAndPort(host, port)
            return "ws://$cleanHost:$cleanPort"
        }

    val isConfigured: Boolean
        get() {
            val (cleanHost, cleanPort) = normalizeHostAndPort(host, port)
            return cleanHost.isNotBlank() &&
                !cleanHost.contains(' ') &&
                !cleanHost.contains(':') &&
                cleanPort in 1024..65535 &&
                pinToken.length >= 4
        }

    companion object {
        const val DEFAULT_SCAN_COOLDOWN_MS = 2_500L

        /**
         * Очищает ввод пользователя: допускает как чистый IP ("192.168.1.15"),
         * так и вставленный целиком адрес ("ws://192.168.1.15:8765" или "192.168.1.15:8080").
         */
        fun normalizeHostAndPort(rawHost: String, fallbackPort: Int): Pair<String, Int> {
            var cleaned = rawHost.trim()
                .removePrefix("ws://")
                .removePrefix("wss://")
                .removePrefix("http://")
                .removePrefix("https://")
                .substringBefore('/')
                .trim()

            var resolvedPort = fallbackPort.coerceIn(1024, 65535)
            val colonIdx = cleaned.indexOf(':')
            if (colonIdx >= 0) {
                val hostPart = cleaned.substring(0, colonIdx).trim()
                val portPart = cleaned.substring(colonIdx + 1).substringBefore(':').trim()
                val parsedPort = portPart.toIntOrNull()
                if (parsedPort != null && parsedPort in 1024..65535) {
                    resolvedPort = parsedPort
                }
                cleaned = hostPart
            }
            return cleaned to resolvedPort
        }
    }
}

class ConnectionSettings(context: Context) {
    private val prefs = context.getSharedPreferences("mobilestore_scanner_prefs", Context.MODE_PRIVATE)

    fun load(): ServerConfig {
        var devId = prefs.getString(KEY_DEVICE_ID, null)
        if (devId.isNullOrBlank()) {
            devId = "android-" + UUID.randomUUID().toString()
            prefs.edit().putString(KEY_DEVICE_ID, devId).apply()
        }
        val defaultName = "${Build.MANUFACTURER} ${Build.MODEL}".trim().ifBlank { "Android Scanner" }
        val rawHost = prefs.getString(KEY_HOST, "") ?: ""
        val rawPort = prefs.getInt(KEY_PORT, 8765)
        val (cleanHost, cleanPort) = ServerConfig.normalizeHostAndPort(rawHost, rawPort)
        // Автоисправление ранее сохранённых некорректных значений (например "IP:8080")
        if (cleanHost != rawHost || cleanPort != rawPort) {
            prefs.edit()
                .putString(KEY_HOST, cleanHost)
                .putInt(KEY_PORT, cleanPort)
                .apply()
        }
        val cooldown = prefs.getLong(KEY_SCAN_COOLDOWN_MS, ServerConfig.DEFAULT_SCAN_COOLDOWN_MS)
            .coerceIn(1_000L, 6_000L)
        return ServerConfig(
            host = cleanHost,
            port = cleanPort,
            pinToken = prefs.getString(KEY_TOKEN, "") ?: "",
            deviceId = devId,
            deviceName = prefs.getString(KEY_DEVICE_NAME, defaultName) ?: defaultName,
            scanCooldownMs = cooldown,
            wifiSsid = prefs.getString(KEY_WIFI_SSID, "") ?: "",
            wifiPassword = prefs.getString(KEY_WIFI_PASSWORD, "") ?: "",
            autoConnectWifiHub = prefs.getBoolean(KEY_AUTO_CONNECT_HUB, false),
        )
    }

    fun save(host: String, port: Int, pinToken: String, deviceName: String): ServerConfig {
        val current = load()
        val (cleanHost, cleanPort) = ServerConfig.normalizeHostAndPort(host, port)
        prefs.edit()
            .putString(KEY_HOST, cleanHost)
            .putInt(KEY_PORT, cleanPort)
            .putString(KEY_TOKEN, pinToken.trim())
            .putString(KEY_DEVICE_NAME, deviceName.trim().ifBlank { current.deviceName })
            .apply()
        return load()
    }

    fun saveWifiHub(ssid: String, password: String, autoConnect: Boolean): ServerConfig {
        prefs.edit()
            .putString(KEY_WIFI_SSID, ssid.trim())
            .putString(KEY_WIFI_PASSWORD, password)
            .putBoolean(KEY_AUTO_CONNECT_HUB, autoConnect)
            .apply()
        return load()
    }

    fun saveScanCooldown(cooldownMs: Long): ServerConfig {
        val clamped = cooldownMs.coerceIn(1_000L, 6_000L)
        prefs.edit().putLong(KEY_SCAN_COOLDOWN_MS, clamped).apply()
        return load()
    }

    companion object {
        private const val KEY_HOST = "server_host"
        private const val KEY_PORT = "server_port"
        private const val KEY_TOKEN = "server_pin_token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val KEY_SCAN_COOLDOWN_MS = "scan_cooldown_ms"
        private const val KEY_WIFI_SSID = "wifi_hub_ssid"
        private const val KEY_WIFI_PASSWORD = "wifi_hub_password"
        private const val KEY_AUTO_CONNECT_HUB = "wifi_hub_auto_connect"
    }
}
