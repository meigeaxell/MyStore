package com.mobilestore.scanner.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.net.SocketFactory

data class LocalWifiStatus(
    val hasWifiNetwork: Boolean = false,
    val isDedicatedHub: Boolean = false,
    val isRequestingHub: Boolean = false,
    val label: String = "Wi-Fi gözlenýär…",
)

/**
 * Управляет привязкой сокетов к локальной Wi-Fi сети (даже без интернета и при включённом 4G/LTE!).
 *
 * Решает сразу 2 проблемы Android / Xiaomi (MIUI/HyperOS):
 * 1. Когда на Wi-Fi хабе нет интернета, Android маршрутизирует трафик в 4G.
 *    Мы явно отдаём OkHttpClient'у wifiNetwork.socketFactory, чтобы трафик к ПК шёл
 *    строго через Wi-Fi, пока 4G продолжает работать для остальных приложений.
 * 2. На Android 10+ (API 29+) позволяет подключиться к конкретному локальному Wi-Fi хабу
 *    прямо из приложения через WifiNetworkSpecifier без ручного похода в настройки Wi-Fi.
 */
class LocalWifiNetworkManager(
    context: Context,
) {
    private val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    @Volatile
    private var passiveWifiNetwork: Network? = null

    @Volatile
    private var dedicatedHubNetwork: Network? = null

    private var passiveCallback: ConnectivityManager.NetworkCallback? = null
    private var hubCallback: ConnectivityManager.NetworkCallback? = null
    private var onWifiChangedListener: (() -> Unit)? = null

    private val _status = MutableStateFlow(LocalWifiStatus())
    val status: StateFlow<LocalWifiStatus> = _status.asStateFlow()

    init {
        scanExistingWifiNetwork()
        startPassiveWifiMonitor()
    }

    fun setOnWifiChangedListener(listener: (() -> Unit)?) {
        onWifiChangedListener = listener
    }

    /**
     * Возвращает SocketFactory активного Wi-Fi (приоритет: выделенный хаб -> любой Wi-Fi),
     * либо null, если Wi-Fi нет (например, телефон сам раздаёт точку доступа / USB-модем).
     */
    fun getPreferredSocketFactory(): SocketFactory? {
        val dedicated = dedicatedHubNetwork
        if (dedicated != null && isNetworkAliveWifi(dedicated)) {
            return dedicated.socketFactory
        }
        val passive = passiveWifiNetwork
        if (passive != null && isNetworkAliveWifi(passive)) {
            return passive.socketFactory
        }
        scanExistingWifiNetwork()
        return passiveWifiNetwork?.takeIf { isNetworkAliveWifi(it) }?.socketFactory
    }

    fun getActiveWifiNetwork(): Network? {
        dedicatedHubNetwork?.takeIf { isNetworkAliveWifi(it) }?.let { return it }
        passiveWifiNetwork?.takeIf { isNetworkAliveWifi(it) }?.let { return it }
        scanExistingWifiNetwork()
        return passiveWifiNetwork?.takeIf { isNetworkAliveWifi(it) }
    }

    private fun isNetworkAliveWifi(network: Network): Boolean {
        val caps = runCatching { cm.getNetworkCapabilities(network) }.getOrNull() ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }

    @Suppress("DEPRECATION")
    private fun scanExistingWifiNetwork() {
        val networks = runCatching { cm.allNetworks }.getOrNull().orEmpty()
        val found = networks.firstOrNull { isNetworkAliveWifi(it) }
        passiveWifiNetwork = found
        updateStatus()
    }

    private fun startPassiveWifiMonitor() {
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            // КРИТИЧНО: убираем требование интернета, чтобы ловить локальный Wi-Fi хаб без интернета!
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                passiveWifiNetwork = network
                updateStatus()
                onWifiChangedListener?.invoke()
            }

            override fun onLost(network: Network) {
                if (passiveWifiNetwork == network) {
                    passiveWifiNetwork = null
                    scanExistingWifiNetwork()
                    onWifiChangedListener?.invoke()
                }
            }
        }
        passiveCallback = cb
        runCatching { cm.registerNetworkCallback(request, cb) }
    }

    /**
     * Принудительно запрашивает у Android (10+) подключение к локальному Wi-Fi хабу по SSID/паролю.
     * Работает параллельно с 4G (интернет на телефоне не пропадает).
     */
    fun connectToWifiHub(ssid: String, password: String): Pair<Boolean, String> {
        val cleanSsid = ssid.trim()
        if (cleanSsid.isEmpty()) {
            return false to "Wi-Fi habyň adyny (SSID) giriziň"
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return false to "Bu funksiýa Android 10 we ondan ýokary wersiýalarda işleýär"
        }

        releaseDedicatedHub()

        val specBuilder = WifiNetworkSpecifier.Builder().setSsid(cleanSsid)
        if (password.isNotEmpty()) {
            specBuilder.setWpa2Passphrase(password)
        }

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(specBuilder.build())
            .build()

        _status.value = _status.value.copy(
            isRequestingHub = true,
            label = "«$cleanSsid» Wi-Fi habyna baglanýar…",
        )

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                dedicatedHubNetwork = network
                _status.value = LocalWifiStatus(
                    hasWifiNetwork = true,
                    isDedicatedHub = true,
                    isRequestingHub = false,
                    label = "✔ «$cleanSsid» habyna baglandy (4G açyk bolsa-da işleýär)",
                )
                onWifiChangedListener?.invoke()
            }

            override fun onUnavailable() {
                dedicatedHubNetwork = null
                updateStatus(overrideMsg = "«$cleanSsid» Wi-Fi habyna baglanyp bolmady (ýa-da ýatyryldy)")
            }

            override fun onLost(network: Network) {
                if (dedicatedHubNetwork == network) {
                    dedicatedHubNetwork = null
                    updateStatus()
                    onWifiChangedListener?.invoke()
                }
            }
        }
        hubCallback = cb

        return runCatching {
            cm.requestNetwork(request, cb)
            true to "«$cleanSsid» baglanyşyk soragy iberildi"
        }.getOrElse { err ->
            hubCallback = null
            updateStatus(overrideMsg = "Wi-Fi hab ýalňyşlygy: ${err.message ?: "näbelli"}")
            false to (err.message ?: "Wi-Fi hab ýalňyşlygy")
        }
    }

    fun releaseDedicatedHub() {
        hubCallback?.let { cb ->
            runCatching { cm.unregisterNetworkCallback(cb) }
        }
        hubCallback = null
        dedicatedHubNetwork = null
        updateStatus()
    }

    private fun updateStatus(overrideMsg: String? = null) {
        val dedicated = dedicatedHubNetwork?.takeIf { isNetworkAliveWifi(it) }
        val passive = passiveWifiNetwork?.takeIf { isNetworkAliveWifi(it) }
        val label = when {
            overrideMsg != null -> overrideMsg
            dedicated != null -> "✔ Wi-Fi hab işjeň (4G bilen bile işleýär)"
            passive != null -> "✔ Wi-Fi tory işjeň (4G öçürmezden PK-a baglanýar)"
            else -> "Wi-Fi tapylmady (Hotspot / adaty tor ulanylýar)"
        }
        _status.value = LocalWifiStatus(
            hasWifiNetwork = dedicated != null || passive != null,
            isDedicatedHub = dedicated != null,
            isRequestingHub = false,
            label = label,
        )
    }
}
