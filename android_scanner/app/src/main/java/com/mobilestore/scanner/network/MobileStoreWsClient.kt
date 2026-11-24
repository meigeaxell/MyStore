package com.mobilestore.scanner.network

import com.mobilestore.scanner.BuildConfig
import com.mobilestore.scanner.data.ConnectionSettings
import com.mobilestore.scanner.data.ServerConfig
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.put
import okhttp3.Dns
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.net.InetAddress
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.math.min

sealed interface ConnectionState {
    data object Disconnected : ConnectionState
    data object Connecting : ConnectionState
    data class Connected(
        val storeName: String,
        val defaultCurrency: String,
        val defaultExchangeRate: String,
        val serverUrl: String,
    ) : ConnectionState

    data class Error(val message: String) : ConnectionState
}

@Serializable
data class IncomingQueueCounts(
    val known: Int = 0,
    val unknown: Int = 0,
    @SerialName("phone_imei") val phoneImei: Int = 0,
    val total: Int = 0,
)

@Serializable
data class IncomingQueuedData(
    @SerialName("queue_id") val queueId: Int = 0,
    @SerialName("item_kind") val itemKind: String = "",
    val merged: Boolean = false,
    val quantity: Int = 1,
    @SerialName("product_name") val productName: String = "",
    val message: String = "",
    val counts: IncomingQueueCounts = IncomingQueueCounts(),
)

/**
 * Надёжный локальный WebSocket-клиент для MobileStore:
 * - авто-переподключение с экспоненциальной задержкой
 * - периодический heartbeat ping/pong
 * - строгая привязка ответов к request_id (UUID)
 * - никогда не считает операцию успешной без ok=true от сервера
 */
class MobileStoreWsClient(
    private val settings: ConnectionSettings,
    private val wifiManager: LocalWifiNetworkManager? = null,
) {
    val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = true
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val baseOkHttp = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    @Volatile
    private var webSocket: WebSocket? = null

    @Volatile
    private var shouldStayConnected: Boolean = false

    @Volatile
    private var activeConfig: ServerConfig = settings.load()

    private val pending = ConcurrentHashMap<String, CompletableDeferred<WsResponseEnvelope>>()
    private var reconnectJob: Job? = null
    private var heartbeatJob: Job? = null
    private var reconnectAttempts = 0

    init {
        // Как только появляется Wi-Fi (или хаб подключён), мгновенно переподключаемся к ПК без задержки!
        wifiManager?.setOnWifiChangedListener {
            if (shouldStayConnected && _state.value !is ConnectionState.Connected) {
                reconnectAttempts = 0
                reconnectJob?.cancel()
                scope.launch {
                    delay(250L)
                    if (shouldStayConnected && _state.value !is ConnectionState.Connected) {
                        openSocket()
                    }
                }
            }
        }
    }

    fun connect(config: ServerConfig = settings.load()) {
        activeConfig = config
        if (!config.isConfigured) {
            _state.value = ConnectionState.Error("Sazlamalarda kompýuteriň IP, port we PIN-kodyny giriziň")
            return
        }
        shouldStayConnected = true
        reconnectJob?.cancel()
        reconnectAttempts = 0
        openSocket()
    }

    fun disconnect() {
        shouldStayConnected = false
        reconnectJob?.cancel()
        heartbeatJob?.cancel()
        failAllPending("Baglanyşyk ulanyjy tarapyndan kesildi")
        webSocket?.close(1000, "Client disconnect")
        webSocket = null
        _state.value = ConnectionState.Disconnected
    }

    private fun openSocket() {
        val cfg = activeConfig
        webSocket?.cancel()
        _state.value = ConnectionState.Connecting

        val request = runCatching {
            Request.Builder()
                .url(cfg.wsUrl)
                .build()
        }.getOrElse { err ->
            shouldStayConnected = false
            _state.value = ConnectionState.Error(
                "Serwer salgysy nädogry (${cfg.wsUrl}): ${err.message ?: "IP we porty barlaň"}"
            )
            return
        }

        // Привязываем сокет строго к Wi-Fi (если он активен), чтобы работать параллельно с 4G!
        val wifiNet = wifiManager?.getActiveWifiNetwork()
        val client = if (wifiNet != null) {
            baseOkHttp.newBuilder()
                .socketFactory(wifiNet.socketFactory)
                .dns(object : Dns {
                    override fun lookup(hostname: String): List<InetAddress> {
                        return runCatching { wifiNet.getAllByName(hostname).toList() }
                            .getOrElse { Dns.SYSTEM.lookup(hostname) }
                    }
                })
                .build()
        } else {
            baseOkHttp
        }

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                reconnectAttempts = 0
                scope.launch {
                    authenticate(cfg)
                }
            }

            override fun onMessage(ws: WebSocket, text: String) {
                val env = runCatching { json.decodeFromString<WsResponseEnvelope>(text) }.getOrNull()
                    ?: return
                val waiter = pending.remove(env.requestId)
                waiter?.complete(env)
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                ws.close(1000, null)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                if (webSocket === ws) {
                    webSocket = null
                    heartbeatJob?.cancel()
                    failAllPending("Baglanyşyk kesildi")
                    if (shouldStayConnected) {
                        _state.value = ConnectionState.Error("Baglanyşyk ýapyldy. Täzeden baglanýar…")
                        scheduleReconnect()
                    } else {
                        _state.value = ConnectionState.Disconnected
                    }
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                if (webSocket === ws) {
                    webSocket = null
                    heartbeatJob?.cancel()
                    failAllPending("Kompýuter bilen aragatnaşyk kesildi")
                    if (shouldStayConnected) {
                        _state.value = ConnectionState.Error(
                            "${cfg.host}:${cfg.port} bilen baglanyşyk ýok. Täzeden synanyşýar…"
                        )
                        scheduleReconnect()
                    } else {
                        _state.value = ConnectionState.Error(t.message ?: "Tor ýalňyşlygy")
                    }
                }
            }
        })
    }

    private suspend fun authenticate(cfg: ServerConfig) {
        val resp = sendCommandRaw(
            type = "auth",
            payload = buildJsonObject {
                put("token", cfg.pinToken)
                put("device_id", cfg.deviceId)
                put("device_name", cfg.deviceName)
                put("app_version", BuildConfig.VERSION_NAME)
            },
            timeoutMs = 7_000L,
        )
        if (resp.ok && resp.data != null) {
            val auth = runCatching { json.decodeFromJsonElement<AuthOkData>(resp.data) }
                .getOrDefault(AuthOkData())
            _state.value = ConnectionState.Connected(
                storeName = auth.storeName,
                defaultCurrency = auth.defaultCurrency,
                defaultExchangeRate = auth.defaultExchangeRate,
                serverUrl = cfg.wsUrl,
            )
            startHeartbeat()
        } else {
            val msg = resp.error?.message ?: "Giriş ýalňyşlygy"
            _state.value = ConnectionState.Error(msg)
            // Неверный PIN — не спамим бесконечным переподключением
            if (resp.error?.code == "UNAUTHORIZED") {
                shouldStayConnected = false
                webSocket?.close(1000, "Unauthorized")
            } else {
                scheduleReconnect()
            }
        }
    }

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (isActive && shouldStayConnected && _state.value is ConnectionState.Connected) {
                delay(15_000L)
                val pong = sendCommandRaw(
                    type = "ping",
                    payload = buildJsonObject {},
                    timeoutMs = 5_000L,
                )
                if (!pong.ok) {
                    webSocket?.cancel()
                    break
                }
            }
        }
    }

    private fun scheduleReconnect() {
        if (!shouldStayConnected) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            reconnectAttempts += 1
            val backoffMs = min(15_000L, 1_500L * reconnectAttempts)
            delay(backoffMs)
            if (shouldStayConnected) {
                openSocket()
            }
        }
    }

    private fun failAllPending(reason: String) {
        val keys = pending.keys.toList()
        for (key in keys) {
            pending.remove(key)?.complete(
                WsResponseEnvelope(
                    type = "error",
                    requestId = key,
                    ok = false,
                    error = WsError(code = "OFFLINE", message = reason),
                )
            )
        }
    }

    suspend fun queueIncomingItem(
        mode: String,
        productId: Int? = null,
        barcode: String? = null,
        imei1: String? = null,
        imei2: String? = null,
        serialNumber: String? = null,
        condition: String = "new",
        modelHint: String? = null,
        ocrRawText: String? = null,
        quantity: Int = 1,
        unitCost: String? = null,
        currency: String = "USD",
        supplierName: String? = null,
        requestId: String = UUID.randomUUID().toString(),
    ): WsResponseEnvelope {
        val cleanCost = unitCost?.trim()?.replace(",", ".")?.takeIf { it.isNotBlank() }
        val payload = buildJsonObject {
            put("mode", mode)
            if (productId != null) put("product_id", productId) else put("product_id", JsonNull)
            if (!barcode.isNullOrBlank()) put("barcode", barcode.trim()) else put("barcode", JsonNull)
            if (!imei1.isNullOrBlank()) put("imei1", imei1.trim()) else put("imei1", JsonNull)
            if (!imei2.isNullOrBlank()) put("imei2", imei2.trim()) else put("imei2", JsonNull)
            if (!serialNumber.isNullOrBlank()) put("serial_number", serialNumber.trim()) else put("serial_number", JsonNull)
            put("condition", if (condition.equals("used", ignoreCase = true)) "used" else "new")
            if (!modelHint.isNullOrBlank()) put("model_hint", modelHint.trim()) else put("model_hint", JsonNull)
            if (!ocrRawText.isNullOrBlank()) put("ocr_raw_text", ocrRawText.trim()) else put("ocr_raw_text", JsonNull)
            put("quantity", quantity.coerceAtLeast(1))
            if (cleanCost != null) put("unit_cost", cleanCost) else put("unit_cost", JsonNull)
            put("currency", if (currency.equals("TMT", ignoreCase = true)) "TMT" else "USD")
            if (!supplierName.isNullOrBlank()) put("supplier_name", supplierName.trim()) else put("supplier_name", JsonNull)
            if (activeConfig.deviceName.isNotBlank()) put("device_name", activeConfig.deviceName)
        }
        return sendCommand(
            type = "queue_incoming_item",
            payload = payload,
            requestId = requestId,
            timeoutMs = 12_000L,
        )
    }

    suspend fun sendCommand(
        type: String,
        payload: JsonObject,
        requestId: String = UUID.randomUUID().toString(),
        timeoutMs: Long = 10_000L,
    ): WsResponseEnvelope {
        if (_state.value !is ConnectionState.Connected) {
            return WsResponseEnvelope(
                type = "error",
                requestId = requestId,
                ok = false,
                error = WsError("OFFLINE", "MobileStore kompýuterine baglanyşyk ýok."),
            )
        }
        return sendCommandRaw(type, payload, requestId, timeoutMs)
    }

    private suspend fun sendCommandRaw(
        type: String,
        payload: JsonObject,
        requestId: String = UUID.randomUUID().toString(),
        timeoutMs: Long = 10_000L,
    ): WsResponseEnvelope {
        val sock = webSocket ?: return WsResponseEnvelope(
            type = "error",
            requestId = requestId,
            ok = false,
            error = WsError("OFFLINE", "WebSocket baglanmady."),
        )
        val deferred = CompletableDeferred<WsResponseEnvelope>()
        pending[requestId] = deferred

        val envelope = WsRequestEnvelope(
            protocolVersion = PROTOCOL_VERSION,
            type = type,
            requestId = requestId,
            deviceId = activeConfig.deviceId,
            timestamp = Instant.now().toString(),
            payload = payload,
        )
        val rawText = json.encodeToString(envelope)
        val sent = sock.send(rawText)
        if (!sent) {
            pending.remove(requestId)
            return WsResponseEnvelope(
                type = "error",
                requestId = requestId,
                ok = false,
                error = WsError("SEND_FAILED", "Wi-Fi arkaly maglumat iberilmedi."),
            )
        }

        val response = withTimeoutOrNull(timeoutMs) { deferred.await() }
        if (response == null) {
            pending.remove(requestId)
            return WsResponseEnvelope(
                type = "error",
                requestId = requestId,
                ok = false,
                error = WsError("TIMEOUT", "Kompýuter wagtynda jogap bermedi. Täzeden synanyşyň."),
            )
        }
        return response
    }
}
