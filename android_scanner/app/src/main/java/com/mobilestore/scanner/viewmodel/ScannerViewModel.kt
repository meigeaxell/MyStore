package com.mobilestore.scanner.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mobilestore.scanner.MobileStoreApp
import com.mobilestore.scanner.data.ReceivingDraftMeta
import com.mobilestore.scanner.data.ServerConfig
import com.mobilestore.scanner.network.AccessoryOcrMatchResponse
import com.mobilestore.scanner.network.CatalogListData
import com.mobilestore.scanner.network.CatalogProductItem
import com.mobilestore.scanner.network.CategoryItem
import com.mobilestore.scanner.network.CategoryListData
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.network.IncomingQueueCounts
import com.mobilestore.scanner.network.IncomingQueuedData
import com.mobilestore.scanner.network.LocalWifiStatus
import com.mobilestore.scanner.network.ProductCardData
import com.mobilestore.scanner.network.ProductDetailsData
import com.mobilestore.scanner.network.ScanMultipleData
import com.mobilestore.scanner.scanner.ScanBundle
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.util.UUID

data class BannerMessage(
    val text: String,
    val isError: Boolean = false,
    val isWarning: Boolean = false,
)

data class PendingReceivingDevice(
    val imei1: String = "",
    val imei2: String = "",
    val serialNumber: String = "",
    val productBarcode: String? = null,
    val source: String = "multi",
    val requestId: String = UUID.randomUUID().toString(),
)

data class SessionQueuedEntry(
    val queueId: Int,
    val itemKind: String, // "phone_imei" | "known" | "unknown"
    val title: String,
    val detail: String,
    val quantity: Int,
    val merged: Boolean,
)

class ScannerViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as MobileStoreApp
    private val ws = app.wsClient
    private val draftDao = app.draftDb.draftDao()
    private val feedback = app.feedback

    val connectionState: StateFlow<ConnectionState> = ws.state
    val wifiStatus: StateFlow<LocalWifiStatus> = app.wifiManager.status

    private val _serverConfig = MutableStateFlow(app.settings.load())
    val serverConfig: StateFlow<ServerConfig> = _serverConfig.asStateFlow()

    private val _cameraStatus = MutableStateFlow("Başlaýar…")
    val cameraStatus: StateFlow<String> = _cameraStatus.asStateFlow()

    private val _lastScanInfo = MutableStateFlow("Kamerany ştrihkoda, QR ýa-da IMEI tutyň")
    val lastScanInfo: StateFlow<String> = _lastScanInfo.asStateFlow()

    private val _banner = MutableStateFlow<BannerMessage?>(null)
    val banner: StateFlow<BannerMessage?> = _banner.asStateFlow()

    // --- Экран 1: Продажи / Сканер ---
    private val _activeProductCard = MutableStateFlow<ProductCardData?>(null)
    val activeProductCard: StateFlow<ProductCardData?> = _activeProductCard.asStateFlow()

    private val _activeScanSource = MutableStateFlow("barcode")
    val activeScanSource: StateFlow<String> = _activeScanSource.asStateFlow()

    private val _multipleMatches = MutableStateFlow<List<ProductCardData>>(emptyList())
    val multipleMatches: StateFlow<List<ProductCardData>> = _multipleMatches.asStateFlow()

    private val _saleOcrResult = MutableStateFlow<AccessoryOcrMatchResponse?>(null)
    val saleOcrResult: StateFlow<AccessoryOcrMatchResponse?> = _saleOcrResult.asStateFlow()

    private val _saleOcrCategoryFilter = MutableStateFlow<Int?>(null)
    val saleOcrCategoryFilter: StateFlow<Int?> = _saleOcrCategoryFilter.asStateFlow()

    private val _activeSaleOcrRawText = MutableStateFlow<String?>(null)

    private val _receivingOcrResult = MutableStateFlow<AccessoryOcrMatchResponse?>(null)
    val receivingOcrResult: StateFlow<AccessoryOcrMatchResponse?> = _receivingOcrResult.asStateFlow()

    private val _receivingOcrCategoryFilter = MutableStateFlow<Int?>(null)
    val receivingOcrCategoryFilter: StateFlow<Int?> = _receivingOcrCategoryFilter.asStateFlow()

    private val _isSaleRequestInFlight = MutableStateFlow(false)
    val isSaleRequestInFlight: StateFlow<Boolean> = _isSaleRequestInFlight.asStateFlow()

    // Триггер принудительной паузы после закрытия/подтверждения карточки, чтобы не пересканировать коробку
    private val _scanCooldownTrigger = MutableStateFlow(0)
    val scanCooldownTrigger: StateFlow<Int> = _scanCooldownTrigger.asStateFlow()

    // Sticky request_id для идемпотентности при повторной отправке одной карточки
    private var currentSaleRequestId: String = UUID.randomUUID().toString()

    // --- Экран 2: Приёмка -> Буферная очередь ПК (Incoming Queue) ---
    val receivingMeta: StateFlow<ReceivingDraftMeta?> = draftDao.observeMeta()
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    private val _pendingReceivingDevice = MutableStateFlow<PendingReceivingDevice?>(null)
    val pendingReceivingDevice: StateFlow<PendingReceivingDevice?> = _pendingReceivingDevice.asStateFlow()

    private val _isReceivingBusy = MutableStateFlow(false)
    val isReceivingBusy: StateFlow<Boolean> = _isReceivingBusy.asStateFlow()

    private val _incomingQueueCounts = MutableStateFlow(IncomingQueueCounts())
    val incomingQueueCounts: StateFlow<IncomingQueueCounts> = _incomingQueueCounts.asStateFlow()

    private val _lastQueuedStatus = MutableStateFlow<String?>(null)
    val lastQueuedStatus: StateFlow<String?> = _lastQueuedStatus.asStateFlow()

    private val _sessionQueuedEntries = MutableStateFlow<List<SessionQueuedEntry>>(emptyList())
    val sessionQueuedEntries: StateFlow<List<SessionQueuedEntry>> = _sessionQueuedEntries.asStateFlow()

    // --- Read-only каталог (для выбора существующего товара в режиме «Sany bilen») ---
    private val _catalogProducts = MutableStateFlow<List<CatalogProductItem>>(emptyList())
    val catalogProducts: StateFlow<List<CatalogProductItem>> = _catalogProducts.asStateFlow()

    private val _selectedProductDetails = MutableStateFlow<ProductDetailsData?>(null)
    val selectedProductDetails: StateFlow<ProductDetailsData?> = _selectedProductDetails.asStateFlow()

    private val _isCatalogLoading = MutableStateFlow(false)
    val isCatalogLoading: StateFlow<Boolean> = _isCatalogLoading.asStateFlow()

    private val _categories = MutableStateFlow<List<CategoryItem>>(emptyList())
    val categories: StateFlow<List<CategoryItem>> = _categories.asStateFlow()

    private val _isCategoriesLoading = MutableStateFlow(false)
    val isCategoriesLoading: StateFlow<Boolean> = _isCategoriesLoading.asStateFlow()

    init {
        val cfg = _serverConfig.value
        if (cfg.autoConnectWifiHub && cfg.wifiSsid.isNotBlank() && !app.wifiManager.status.value.hasWifiNetwork) {
            app.wifiManager.connectToWifiHub(cfg.wifiSsid, cfg.wifiPassword)
        }
        if (cfg.isConfigured) {
            ws.connect(cfg)
        }
        viewModelScope.launch {
            ensureDraftMetaExists()
        }
    }

    fun updateCameraStatus(status: String) {
        _cameraStatus.value = status
    }

    fun clearBanner() {
        _banner.value = null
    }

    private fun showMessage(text: String, isError: Boolean = false, isWarning: Boolean = false) {
        _banner.value = BannerMessage(text = text, isError = isError, isWarning = isWarning)
        if (isError) feedback.onError() else feedback.onConfirmSuccess()
    }

    // ==================== НАСТРОЙКИ И ПОДКЛЮЧЕНИЕ ====================

    fun saveAndConnect(host: String, port: Int, pin: String, deviceName: String) {
        val updated = app.settings.save(host, port, pin, deviceName)
        _serverConfig.value = updated
        ws.connect(updated)
    }

    fun saveWifiHub(ssid: String, password: String, autoConnect: Boolean) {
        _serverConfig.value = app.settings.saveWifiHub(ssid, password, autoConnect)
    }

    fun connectToWifiHub(ssid: String, password: String, autoConnect: Boolean) {
        val updated = app.settings.saveWifiHub(ssid, password, autoConnect)
        _serverConfig.value = updated
        val (ok, msg) = app.wifiManager.connectToWifiHub(updated.wifiSsid, updated.wifiPassword)
        if (!ok) {
            showMessage(msg, isError = true)
        }
    }

    fun releaseWifiHub() {
        app.wifiManager.releaseDedicatedHub()
    }

    fun updateScanCooldown(cooldownMs: Long) {
        _serverConfig.value = app.settings.saveScanCooldown(cooldownMs)
    }

    fun reconnect() {
        ws.connect(_serverConfig.value)
    }

    fun disconnect() {
        ws.disconnect()
    }

    // ==================== ЭКРАН 1: СКАНИРОВАНИЕ / ПРОДАЖИ ====================

    fun onSaleBundleDetected(bundle: ScanBundle) {
        if (_isSaleRequestInFlight.value || _activeProductCard.value != null || _multipleMatches.value.isNotEmpty()) {
            return
        }
        feedback.onScanSuccess()
        _lastScanInfo.value = bundle.summaryLabel()
        _activeScanSource.value = bundle.source
        queryScanBundle(bundle)
    }

    fun manualLookupForSale(code: String) {
        val clean = code.trim()
        if (clean.isEmpty()) return
        _lastScanInfo.value = "[El bilen] $clean"
        _activeScanSource.value = "manual"
        queryScanBundle(
            ScanBundle(
                imei1 = if (clean.length == 15 && clean.all { it.isDigit() }) clean else null,
                productBarcode = clean,
                allCodes = listOf(clean),
                source = "manual",
            )
        )
    }

    private fun queryScanBundle(bundle: ScanBundle) {
        val primary = bundle.primaryCode
        if (primary.isBlank()) return
        viewModelScope.launch {
            _isSaleRequestInFlight.value = true
            val resp = ws.sendCommand(
                type = "scan_code",
                payload = buildJsonObject {
                    put("code", primary)
                    if (bundle.allCodes.isNotEmpty()) {
                        put(
                            "codes",
                            buildJsonArray {
                                bundle.allCodes.forEach { add(it) }
                            }
                        )
                    }
                    if (!bundle.imei1.isNullOrBlank()) put("imei1", bundle.imei1)
                    if (!bundle.imei2.isNullOrBlank()) put("imei2", bundle.imei2)
                    if (!bundle.serialNumber.isNullOrBlank()) put("serial_number", bundle.serialNumber)
                    if (!bundle.productBarcode.isNullOrBlank()) put("barcode", bundle.productBarcode)
                    put("source", bundle.source)
                    put("mode", "sale")
                },
            )
            _isSaleRequestInFlight.value = false

            if (!resp.ok) {
                showMessage(resp.error?.message ?: "Haryt tapylmady", isError = true)
                return@launch
            }
            when (resp.type) {
                "product_card" -> {
                    val card = resp.data?.let {
                        runCatching { ws.json.decodeFromJsonElement<ProductCardData>(it) }.getOrNull()
                    }
                    if (card != null) {
                        currentSaleRequestId = UUID.randomUUID().toString()
                        _activeProductCard.value = card
                        if (card.availabilityStatus != "available" || card.requiresConfirmation) {
                            feedback.onError()
                        }
                    }
                }
                "scan_multiple" -> {
                    val multi = resp.data?.let {
                        runCatching { ws.json.decodeFromJsonElement<ScanMultipleData>(it) }.getOrNull()
                    }
                    _multipleMatches.value = multi?.items.orEmpty()
                }
                else -> {
                    showMessage("Serwerden garaşylmadyk jogap: ${resp.type}", isError = true)
                }
            }
        }
    }

    fun selectFromMultipleMatches(card: ProductCardData) {
        _multipleMatches.value = emptyList()
        currentSaleRequestId = UUID.randomUUID().toString()
        _activeProductCard.value = card
    }

    fun dismissMultipleMatches() {
        _multipleMatches.value = emptyList()
    }

    fun matchAccessoryForSale(rawText: String, categoryId: Int? = null) {
        val clean = rawText.trim()
        if (clean.isEmpty()) {
            showMessage("Gutyda okaljak tekst tapylmady. Ýagtylygy ýa-da burçy üýtgediň.", isError = true)
            return
        }
        feedback.onScanSuccess()
        _saleOcrCategoryFilter.value = categoryId
        viewModelScope.launch {
            _isSaleRequestInFlight.value = true
            val resp = ws.sendCommand(
                type = "match_accessory_ocr",
                payload = buildJsonObject {
                    put("raw_text", clean)
                    if (categoryId != null) put("category_id", categoryId)
                    put("limit", 6)
                },
            )
            _isSaleRequestInFlight.value = false
            if (!resp.ok || resp.data == null) {
                showMessage(resp.error?.message ?: "Guty tekstini işläp bolmady", isError = true)
                return@launch
            }
            val parsed = runCatching {
                ws.json.decodeFromJsonElement<AccessoryOcrMatchResponse>(resp.data)
            }.getOrNull()
            if (parsed != null) {
                _saleOcrResult.value = parsed
            } else {
                showMessage("Serweriň jogabyny okap bolmady", isError = true)
            }
        }
    }

    fun selectAccessoryForSale(card: ProductCardData) {
        val raw = _saleOcrResult.value?.rawText?.trim().takeIf { !it.isNullOrBlank() }
        _activeSaleOcrRawText.value = raw
        _saleOcrResult.value = null
        _saleOcrCategoryFilter.value = null
        _activeScanSource.value = "ocr_box"
        currentSaleRequestId = UUID.randomUUID().toString()
        _activeProductCard.value = card
    }

    fun dismissSaleOcr() {
        _saleOcrResult.value = null
        _saleOcrCategoryFilter.value = null
        _scanCooldownTrigger.value += 1
    }

    fun matchAccessoryForReceiving(rawText: String, categoryId: Int? = null) {
        val clean = rawText.trim()
        if (clean.isEmpty()) {
            showMessage("Gutyda okaljak tekst tapylmady. Ýagtylygy ýa-da burçy üýtgediň.", isError = true)
            return
        }
        feedback.onScanSuccess()
        _receivingOcrCategoryFilter.value = categoryId
        viewModelScope.launch {
            _isReceivingBusy.value = true
            val resp = ws.sendCommand(
                type = "match_accessory_ocr",
                payload = buildJsonObject {
                    put("raw_text", clean)
                    if (categoryId != null) put("category_id", categoryId)
                    put("limit", 6)
                },
            )
            _isReceivingBusy.value = false
            if (!resp.ok || resp.data == null) {
                showMessage(resp.error?.message ?: "Guty tekstini işläp bolmady", isError = true)
                return@launch
            }
            val parsed = runCatching {
                ws.json.decodeFromJsonElement<AccessoryOcrMatchResponse>(resp.data)
            }.getOrNull()
            if (parsed != null) {
                _receivingOcrResult.value = parsed
            } else {
                showMessage("Serweriň jogabyny okap bolmady", isError = true)
            }
        }
    }

    fun dismissReceivingOcr() {
        _receivingOcrResult.value = null
        _receivingOcrCategoryFilter.value = null
        _scanCooldownTrigger.value += 1
    }

    fun confirmOcrAlias(productId: Int, rawText: String) {
        val clean = rawText.trim()
        if (clean.isBlank()) return
        viewModelScope.launch {
            if (ws.state.value is ConnectionState.Connected) {
                ws.sendCommand(
                    type = "confirm_ocr_alias",
                    payload = buildJsonObject {
                        put("product_id", productId)
                        put("raw_text", clean)
                    },
                    timeoutMs = 4_000L,
                )
            }
        }
    }

    fun confirmAddToSale(
        card: ProductCardData,
        negotiatedPrice: String,
        currency: String,
        quantity: Int,
    ) {
        val cleanPrice = negotiatedPrice.trim().replace(",", ".")
        val parsed = cleanPrice.toDoubleOrNull()
        if (parsed == null || parsed <= 0.0) {
            showMessage("0-dan uly dogry satyş bahasyny giriziň", isError = true)
            return
        }
        val ocrRaw = _activeSaleOcrRawText.value
        viewModelScope.launch {
            _isSaleRequestInFlight.value = true
            val resp = ws.sendCommand(
                type = "add_to_sale",
                requestId = currentSaleRequestId,
                payload = buildJsonObject {
                    put("product_id", card.productId)
                    if (card.stockItemId != null) put("stock_item_id", card.stockItemId)
                    if (!card.imei.isNullOrBlank()) put("imei", card.imei)
                    put("quantity", if (card.imei != null) 1 else quantity.coerceAtLeast(1))
                    put("unit_price", cleanPrice)
                    put("currency", currency)
                    if (!ocrRaw.isNullOrBlank()) put("ocr_raw_text", ocrRaw)
                },
            )
            _isSaleRequestInFlight.value = false

            if (resp.ok) {
                val msg = resp.data?.jsonObject?.get("message")?.jsonPrimitive?.content
                    ?: "Haryt kompýuterdäki satyşa goşuldy"
                _activeProductCard.value = null
                _activeSaleOcrRawText.value = null
                currentSaleRequestId = UUID.randomUUID().toString()
                _scanCooldownTrigger.value += 1
                showMessage(msg, isError = false)
            } else {
                // НЕ закрываем карточку при обрыве/ошибке, чтобы сотрудник мог повторить с тем же request_id
                showMessage(resp.error?.message ?: "Harydy satyşa goşup bolmady", isError = true)
            }
        }
    }

    fun cancelSaleCard() {
        val reqId = currentSaleRequestId
        _activeProductCard.value = null
        _activeSaleOcrRawText.value = null
        currentSaleRequestId = UUID.randomUUID().toString()
        _scanCooldownTrigger.value += 1
        viewModelScope.launch {
            if (ws.state.value is ConnectionState.Connected) {
                ws.sendCommand(
                    type = "cancel_operation",
                    payload = buildJsonObject {
                        put("target_request_id", reqId)
                        put("reason", "user_cancelled")
                    },
                    timeoutMs = 3_000L,
                )
            }
        }
    }

    // ==================== ЭКРАН 2: ПРИЁМКА -> БУФЕРНАЯ ОЧЕРЕДЬ ПК ====================

    private suspend fun ensureDraftMetaExists(): ReceivingDraftMeta {
        val existing = draftDao.getMeta()
        if (existing != null) return existing
        val conn = ws.state.value as? ConnectionState.Connected
        val fresh = ReceivingDraftMeta(
            requestId = UUID.randomUUID().toString(),
            currency = "USD",
            exchangeRate = conn?.defaultExchangeRate ?: "19.5000",
        )
        draftDao.upsertMeta(fresh)
        return fresh
    }

    fun updateReceivingMeta(
        productId: Int? = null,
        productName: String? = null,
        supplierName: String? = null,
        unitCost: String? = null,
        currency: String? = null,
        exchangeRate: String? = null,
        note: String? = null,
        nonImeiQuantity: Int? = null,
        useImeiMode: Boolean? = null,
    ) {
        viewModelScope.launch {
            val cur = ensureDraftMetaExists()
            draftDao.upsertMeta(
                cur.copy(
                    productId = productId ?: cur.productId,
                    productName = productName ?: cur.productName,
                    supplierName = supplierName ?: cur.supplierName,
                    unitCost = unitCost ?: cur.unitCost,
                    currency = currency ?: cur.currency,
                    exchangeRate = exchangeRate ?: cur.exchangeRate,
                    note = note ?: cur.note,
                    nonImeiQuantity = nonImeiQuantity ?: cur.nonImeiQuantity,
                    useImeiMode = useImeiMode ?: cur.useImeiMode,
                )
            )
        }
    }

    fun clearReceivingSelectedProduct() {
        viewModelScope.launch {
            val cur = ensureDraftMetaExists()
            draftDao.upsertMeta(cur.copy(productId = null, productName = "", nonImeiQuantity = 1))
        }
    }

    fun clearSessionQueuedEntries() {
        _sessionQueuedEntries.value = emptyList()
    }

    fun openManualPhoneDialog() {
        _pendingReceivingDevice.value = PendingReceivingDevice(source = "manual")
    }

    fun dismissPendingReceivingDevice() {
        _pendingReceivingDevice.value = null
        _scanCooldownTrigger.value += 1
    }

    fun onReceivingBundleDetected(bundle: ScanBundle) {
        if (_pendingReceivingDevice.value != null || _isReceivingBusy.value) return
        feedback.onScanSuccess()

        val useImeiMode = receivingMeta.value?.useImeiMode ?: true

        if (useImeiMode) {
            // Режим 1: IMEI bilen (Telefon) -> открываем короткое подтверждение и отправляем в PK nobaty
            if (bundle.hasDeviceIdentity) {
                _pendingReceivingDevice.value = PendingReceivingDevice(
                    imei1 = bundle.imei1.orEmpty(),
                    imei2 = bundle.imei2.orEmpty(),
                    serialNumber = bundle.serialNumber.orEmpty(),
                    productBarcode = bundle.productBarcode,
                    source = bundle.source,
                )
                return
            }
            val fallbackImei = bundle.allCodes.firstOrNull { it.filter(Char::isDigit).length >= 14 }
            if (!fallbackImei.isNullOrBlank()) {
                _pendingReceivingDevice.value = PendingReceivingDevice(
                    imei1 = fallbackImei,
                    productBarcode = bundle.productBarcode,
                    source = bundle.source,
                )
                return
            }
            if (bundle.isOnlyProductBarcode) {
                _scanCooldownTrigger.value += 1
                showMessage(
                    "Telefon rejiminde IMEI skan ediň (aksessuar üçin «Sany bilen» geçiň)",
                    isError = false,
                    isWarning = true,
                )
            }
            return
        }

        // Режим 2: Sany bilen (Haryt / Aksessuar) -> сразу отправляем штрихкод в PK nobaty (+1)
        val scannedCode = (bundle.productBarcode ?: bundle.primaryCode).trim()
        if (scannedCode.isNotEmpty()) {
            queueBarcodeQuantityToPc(barcode = scannedCode, quantity = 1)
        }
    }

    private fun handleIncomingQueuedSuccess(
        data: IncomingQueuedData,
        fallbackDetail: String,
    ) {
        _incomingQueueCounts.value = data.counts
        _lastQueuedStatus.value = data.message.ifBlank { fallbackDetail }

        val entry = SessionQueuedEntry(
            queueId = data.queueId,
            itemKind = data.itemKind,
            title = data.productName.ifBlank { fallbackDetail },
            detail = data.message.ifBlank { fallbackDetail },
            quantity = data.quantity,
            merged = data.merged,
        )
        _sessionQueuedEntries.value = (listOf(entry) + _sessionQueuedEntries.value).take(30)

        val isUnknown = data.itemKind == "unknown"
        val bannerText = when {
            data.message.isNotBlank() -> data.message
            data.itemKind == "phone_imei" -> "Telefon PK nobatyna goşuldy"
            isUnknown -> "Näbelli harytlar nobatyna goşuldy (${data.quantity} sany)"
            else -> "Belli harytlar nobatyna goşuldy (${data.quantity} sany)"
        }
        showMessage(bannerText, isError = false, isWarning = isUnknown)
    }

    fun queuePhoneToPc(
        imei1: String,
        imei2: String = "",
        serialNumber: String = "",
        condition: String = "new",
        modelHint: String = "",
        unitCost: String = "",
        currency: String = "USD",
        supplierName: String? = null,
        productBarcode: String? = null,
        requestId: String = UUID.randomUUID().toString(),
        onSuccess: () -> Unit = {},
    ) {
        val clean1 = imei1.trim()
        val clean2 = imei2.trim().ifBlank { null }
        val cleanSn = serialNumber.trim().uppercase().ifBlank { null }
        val cleanHint = modelHint.trim().ifBlank { null }
        val cleanCost = unitCost.trim().replace(",", ".").ifBlank { null }

        if (clean1.isEmpty()) {
            showMessage("Enjamyň IMEI 1 belgisini giriziň", isError = true)
            return
        }
        if (clean2 != null && clean1 == clean2) {
            showMessage("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez", isError = true)
            return
        }
        if (cleanCost != null) {
            val parsedCost = cleanCost.toDoubleOrNull()
            if (parsedCost == null || parsedCost < 0.0) {
                showMessage("Alyş bahasy nädogry", isError = true)
                return
            }
        }

        viewModelScope.launch {
            val meta = ensureDraftMetaExists()
            val effCurrency = if (currency.equals("TMT", ignoreCase = true)) "TMT" else "USD"
            val effSupplier = (supplierName ?: meta.supplierName).trim().ifBlank { null }

            _isReceivingBusy.value = true
            val resp = ws.queueIncomingItem(
                mode = "imei",
                barcode = productBarcode,
                imei1 = clean1,
                imei2 = clean2,
                serialNumber = cleanSn,
                condition = condition,
                modelHint = cleanHint,
                quantity = 1,
                unitCost = cleanCost,
                currency = effCurrency,
                supplierName = effSupplier,
                requestId = requestId,
            )
            _isReceivingBusy.value = false

            if (resp.ok && resp.data != null) {
                val parsed = runCatching {
                    ws.json.decodeFromJsonElement<IncomingQueuedData>(resp.data)
                }.getOrDefault(
                    IncomingQueuedData(
                        itemKind = "phone_imei",
                        productName = cleanHint ?: "IMEI $clean1",
                        message = "Telefon (IMEI $clean1) PK nobatyna goşuldy",
                    )
                )
                // Сохраняем валюту по умолчанию для следующих сканов
                if (meta.currency != effCurrency) {
                    draftDao.upsertMeta(meta.copy(currency = effCurrency))
                }
                _pendingReceivingDevice.value = null
                _scanCooldownTrigger.value += 1
                handleIncomingQueuedSuccess(parsed, "IMEI $clean1")
                onSuccess()
            } else {
                showMessage(resp.error?.message ?: "Telefony PK nobatyna iberip bolmady", isError = true)
            }
        }
    }

    fun queueBarcodeQuantityToPc(
        barcode: String,
        quantity: Int = 1,
        unitCost: String? = null,
        currency: String? = null,
        supplierName: String? = null,
        onSuccess: () -> Unit = {},
    ) {
        val clean = barcode.trim()
        if (clean.isEmpty()) {
            showMessage("Ştrihkody giriziň", isError = true)
            return
        }
        val safeQty = quantity.coerceAtLeast(1)

        viewModelScope.launch {
            val meta = ensureDraftMetaExists()
            val effCurrency = (currency ?: meta.currency).ifBlank { "USD" }
            val effSupplier = (supplierName ?: meta.supplierName).trim().ifBlank { null }

            _isReceivingBusy.value = true
            val resp = ws.queueIncomingItem(
                mode = "quantity",
                productId = null,
                barcode = clean,
                quantity = safeQty,
                unitCost = unitCost,
                currency = effCurrency,
                supplierName = effSupplier,
            )
            _isReceivingBusy.value = false

            if (resp.ok && resp.data != null) {
                val parsed = runCatching {
                    ws.json.decodeFromJsonElement<IncomingQueuedData>(resp.data)
                }.getOrDefault(
                    IncomingQueuedData(
                        itemKind = "unknown",
                        quantity = safeQty,
                        productName = clean,
                        message = "«$clean» PK nobatyna goşuldy ($safeQty sany)",
                    )
                )
                _scanCooldownTrigger.value += 1
                handleIncomingQueuedSuccess(parsed, clean)
                onSuccess()
            } else {
                _scanCooldownTrigger.value += 1
                showMessage(resp.error?.message ?: "Ştrihkody PK nobatyna iberip bolmady", isError = true)
            }
        }
    }

    fun queueQuantityProductToPc(
        productId: Int?,
        productName: String,
        quantity: Int,
        unitCost: String? = null,
        currency: String = "USD",
        supplierName: String? = null,
        onSuccess: () -> Unit = {},
    ) {
        if (productId == null) {
            showMessage("Haryt saýlaň ýa-da kameradan ştrihkod skan ediň", isError = true)
            return
        }
        if (quantity <= 0) {
            showMessage("Sany 0-dan uly bolmaly", isError = true)
            return
        }
        val cleanCost = unitCost?.trim()?.replace(",", ".")?.ifBlank { null }
        if (cleanCost != null) {
            val parsedCost = cleanCost.toDoubleOrNull()
            if (parsedCost == null || parsedCost < 0.0) {
                showMessage("Alyş bahasy nädogry", isError = true)
                return
            }
        }

        viewModelScope.launch {
            val meta = ensureDraftMetaExists()
            val effCurrency = if (currency.equals("TMT", ignoreCase = true)) "TMT" else "USD"
            val effSupplier = supplierName?.trim()?.ifBlank { null }
            draftDao.upsertMeta(
                meta.copy(
                    currency = effCurrency,
                    supplierName = effSupplier.orEmpty(),
                    unitCost = cleanCost.orEmpty(),
                    nonImeiQuantity = quantity,
                )
            )

            _isReceivingBusy.value = true
            val resp = ws.queueIncomingItem(
                mode = "quantity",
                productId = productId,
                quantity = quantity,
                unitCost = cleanCost,
                currency = effCurrency,
                supplierName = effSupplier,
            )
            _isReceivingBusy.value = false

            if (resp.ok && resp.data != null) {
                val parsed = runCatching {
                    ws.json.decodeFromJsonElement<IncomingQueuedData>(resp.data)
                }.getOrDefault(
                    IncomingQueuedData(
                        itemKind = "known",
                        quantity = quantity,
                        productName = productName,
                        message = "«$productName» belli harytlar nobatyna goşuldy ($quantity sany)",
                    )
                )
                draftDao.upsertMeta(meta.copy(currency = effCurrency, supplierName = effSupplier.orEmpty(), nonImeiQuantity = 1))
                _scanCooldownTrigger.value += 1
                handleIncomingQueuedSuccess(parsed, productName)
                onSuccess()
            } else {
                showMessage(resp.error?.message ?: "Harydy PK nobatyna iberip bolmady", isError = true)
            }
        }
    }

    fun queueOcrMatchedProductToPc(card: ProductCardData, rawText: String) {
        val cleanRaw = rawText.trim().ifBlank { null }
        viewModelScope.launch {
            val meta = ensureDraftMetaExists()
            val effCurrency = meta.currency.ifBlank { "USD" }
            val effSupplier = meta.supplierName.trim().ifBlank { null }

            _isReceivingBusy.value = true
            val resp = ws.queueIncomingItem(
                mode = "quantity",
                productId = card.productId,
                ocrRawText = cleanRaw,
                quantity = 1,
                currency = effCurrency,
                supplierName = effSupplier,
            )
            _isReceivingBusy.value = false

            if (resp.ok && resp.data != null) {
                val parsed = runCatching {
                    ws.json.decodeFromJsonElement<IncomingQueuedData>(resp.data)
                }.getOrDefault(
                    IncomingQueuedData(
                        itemKind = "known",
                        quantity = 1,
                        productName = card.name,
                        message = "«${card.name}» belli harytlar nobatyna goşuldy",
                    )
                )
                _receivingOcrResult.value = null
                _receivingOcrCategoryFilter.value = null
                _scanCooldownTrigger.value += 1
                handleIncomingQueuedSuccess(parsed, card.name)
            } else {
                showMessage(resp.error?.message ?: "OCR harydyny PK nobatyna iberip bolmady", isError = true)
            }
        }
    }

    fun queueOcrUnknownToPc(rawText: String, modelHint: String = "") {
        val cleanRaw = rawText.trim()
        val cleanHint = modelHint.trim().ifBlank { cleanRaw.take(60) }
        if (cleanRaw.isEmpty() && cleanHint.isEmpty()) {
            showMessage("Guty teksti boş", isError = true)
            return
        }
        viewModelScope.launch {
            val meta = ensureDraftMetaExists()
            val effCurrency = meta.currency.ifBlank { "USD" }
            val effSupplier = meta.supplierName.trim().ifBlank { null }

            _isReceivingBusy.value = true
            val resp = ws.queueIncomingItem(
                mode = "quantity",
                productId = null,
                barcode = null,
                modelHint = cleanHint,
                ocrRawText = cleanRaw.ifBlank { cleanHint },
                quantity = 1,
                currency = effCurrency,
                supplierName = effSupplier,
            )
            _isReceivingBusy.value = false

            if (resp.ok && resp.data != null) {
                val parsed = runCatching {
                    ws.json.decodeFromJsonElement<IncomingQueuedData>(resp.data)
                }.getOrDefault(
                    IncomingQueuedData(
                        itemKind = "unknown",
                        quantity = 1,
                        productName = cleanHint,
                        message = "«$cleanHint» näbelli harytlar nobatyna goşuldy",
                    )
                )
                _receivingOcrResult.value = null
                _receivingOcrCategoryFilter.value = null
                _scanCooldownTrigger.value += 1
                handleIncomingQueuedSuccess(parsed, cleanHint)
            } else {
                showMessage(resp.error?.message ?: "Näbelli harydy PK nobatyna iberip bolmady", isError = true)
            }
        }
    }

    // ==================== КАТАЛОГ (READ-ONLY ДЛЯ ВЫБОРА В «SANY BILEN») ====================

    fun loadCatalog(query: String = "", categoryId: Int? = null) {
        viewModelScope.launch {
            _isCatalogLoading.value = true
            val resp = ws.sendCommand(
                type = "catalog_list",
                payload = buildJsonObject {
                    put("query", query.trim())
                    if (categoryId != null) put("category_id", categoryId)
                    put("limit", 200)
                },
            )
            _isCatalogLoading.value = false
            if (resp.ok && resp.data != null) {
                val parsed = runCatching { ws.json.decodeFromJsonElement<CatalogListData>(resp.data) }.getOrNull()
                _catalogProducts.value = parsed?.products.orEmpty()
            } else if (!resp.ok) {
                showMessage(resp.error?.message ?: "Katalog ýüklenmedi", isError = true)
            }
        }
    }

    fun loadProductDetails(productId: Int) {
        viewModelScope.launch {
            val resp = ws.sendCommand(
                type = "product_details",
                payload = buildJsonObject { put("product_id", productId) },
            )
            if (resp.ok && resp.data != null) {
                _selectedProductDetails.value = runCatching {
                    ws.json.decodeFromJsonElement<ProductDetailsData>(resp.data)
                }.getOrNull()
            } else {
                showMessage(resp.error?.message ?: "Haryt maglumatlary ýüklenmedi", isError = true)
            }
        }
    }

    fun dismissProductDetails() {
        _selectedProductDetails.value = null
    }

    fun saveProduct(
        productId: Int?,
        name: String,
        categoryId: Int?,
        brand: String,
        model: String,
        memory: String,
        color: String,
        extraSpecs: String,
        minStock: Int,
        defaultCost: String,
        costCurrency: String,
        allowDuplicate: Boolean = false,
        ocrRawText: String? = null,
        barcode: String = "",
        onSuccess: (createdId: Int?, createdName: String) -> Unit = { _, _ -> },
    ) {
        val specParts = listOf(memory.trim(), color.trim(), extraSpecs.trim()).filter { it.isNotEmpty() }
        val composedSpec = specParts.joinToString(" / ")
        viewModelScope.launch {
            val type = if (productId == null) "product_create" else "product_update"
            val payload = buildJsonObject {
                if (productId != null) put("product_id", productId)
                put("name", name.trim())
                if (categoryId != null) put("category_id", categoryId)
                put("brand", brand.trim())
                put("model", model.trim())
                put("specification", composedSpec)
                if (barcode.trim().isNotEmpty()) put("barcode", barcode.trim())
                put("min_stock_quantity", minStock)
                val cleanCost = defaultCost.trim().replace(",", ".")
                if ((cleanCost.toDoubleOrNull() ?: 0.0) > 0.0) {
                    put("unit_cost", cleanCost)
                    put("cost_currency", costCurrency)
                }
                if (productId == null) put("allow_duplicate", allowDuplicate)
                if (!ocrRawText.isNullOrBlank()) put("ocr_raw_text", ocrRawText.trim())
            }

            val resp = ws.sendCommand(type = type, payload = payload)
            if (resp.ok) {
                val obj = resp.data?.jsonObject
                val msg = obj?.get("message")?.jsonPrimitive?.content ?: "Haryt ýatda saklandy"
                val savedId = obj?.get("product")?.jsonObject?.get("id")?.jsonPrimitive?.content?.toIntOrNull()
                showMessage(msg, isError = false)
                loadCatalog()
                onSuccess(savedId, name.trim())
            } else {
                showMessage(resp.error?.message ?: "Harydy saklamakda ýalňyşlyk", isError = true)
            }
        }
    }

    fun loadCategories() {
        viewModelScope.launch {
            _isCategoriesLoading.value = true
            val resp = ws.sendCommand(
                type = "category_list",
                payload = buildJsonObject { put("active_only", false) },
            )
            _isCategoriesLoading.value = false
            if (resp.ok && resp.data != null) {
                val parsed = runCatching { ws.json.decodeFromJsonElement<CategoryListData>(resp.data) }.getOrNull()
                _categories.value = parsed?.categories.orEmpty()
            } else if (!resp.ok) {
                showMessage(resp.error?.message ?: "Kategoriýalar ýüklenmedi", isError = true)
            }
        }
    }

    fun createCategory(name: String, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            val resp = ws.sendCommand(
                type = "category_create",
                payload = buildJsonObject { put("name", name.trim()) },
            )
            if (resp.ok) {
                showMessage("«${name.trim()}» kategoriýasy döredildi", isError = false)
                loadCategories()
                onDone()
            } else {
                showMessage(resp.error?.message ?: "Kategoriýa döretmekde ýalňyşlyk", isError = true)
            }
        }
    }

    fun renameCategory(categoryId: Int, newName: String, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            val resp = ws.sendCommand(
                type = "category_update",
                payload = buildJsonObject {
                    put("category_id", categoryId)
                    put("name", newName.trim())
                },
            )
            if (resp.ok) {
                showMessage("Kategoriýanyň ady üýtgedildi", isError = false)
                loadCategories()
                onDone()
            } else {
                showMessage(resp.error?.message ?: "Adyny üýtgetmekde ýalňyşlyk", isError = true)
            }
        }
    }

    fun deactivateCategory(categoryId: Int, force: Boolean = false) {
        viewModelScope.launch {
            val resp = ws.sendCommand(
                type = "category_deactivate",
                payload = buildJsonObject {
                    put("category_id", categoryId)
                    put("force", force)
                },
            )
            if (resp.ok) {
                showMessage("Kategoriýa öçürildi", isError = false)
                loadCategories()
            } else {
                showMessage(resp.error?.message ?: "Kategoriýany öçürip bolmady", isError = true)
            }
        }
    }
}
