package com.mobilestore.scanner.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mobilestore.scanner.MobileStoreApp
import com.mobilestore.scanner.data.ReceivingDraftImei
import com.mobilestore.scanner.data.ReceivingDraftMeta
import com.mobilestore.scanner.data.ServerConfig
import com.mobilestore.scanner.network.CatalogListData
import com.mobilestore.scanner.network.CatalogProductItem
import com.mobilestore.scanner.network.CategoryItem
import com.mobilestore.scanner.network.CategoryListData
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.network.ImeiCheckResultData
import com.mobilestore.scanner.network.ProductCardData
import com.mobilestore.scanner.network.ProductDetailsData
import com.mobilestore.scanner.network.ScanMultipleData
import com.mobilestore.scanner.scanner.LuhnValidator
import com.mobilestore.scanner.scanner.ScanBundle
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
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
)

data class PendingReceivingDevice(
    val imei1: String = "",
    val imei2: String = "",
    val serialNumber: String = "",
    val productBarcode: String? = null,
    val source: String = "multi",
)

class ScannerViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as MobileStoreApp
    private val ws = app.wsClient
    private val draftDao = app.draftDb.draftDao()
    private val feedback = app.feedback

    val connectionState: StateFlow<ConnectionState> = ws.state

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

    private val _isSaleRequestInFlight = MutableStateFlow(false)
    val isSaleRequestInFlight: StateFlow<Boolean> = _isSaleRequestInFlight.asStateFlow()

    // Триггер принудительной паузы после закрытия/подтверждения карточки, чтобы не пересканировать коробку
    private val _scanCooldownTrigger = MutableStateFlow(0)
    val scanCooldownTrigger: StateFlow<Int> = _scanCooldownTrigger.asStateFlow()

    // Sticky request_id для идемпотентности при повторной отправке одной карточки
    private var currentSaleRequestId: String = UUID.randomUUID().toString()

    // --- Экран 2: Приёмка (Room-черновик) ---
    val receivingMeta: StateFlow<ReceivingDraftMeta?> = draftDao.observeMeta()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val receivingImeis: StateFlow<List<ReceivingDraftImei>> = draftDao.observeImeis()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _pendingReceivingDevice = MutableStateFlow<PendingReceivingDevice?>(null)
    val pendingReceivingDevice: StateFlow<PendingReceivingDevice?> = _pendingReceivingDevice.asStateFlow()

    private val _isReceivingBusy = MutableStateFlow(false)
    val isReceivingBusy: StateFlow<Boolean> = _isReceivingBusy.asStateFlow()

    // --- Экран 3: Каталог ---
    private val _catalogProducts = MutableStateFlow<List<CatalogProductItem>>(emptyList())
    val catalogProducts: StateFlow<List<CatalogProductItem>> = _catalogProducts.asStateFlow()

    private val _selectedProductDetails = MutableStateFlow<ProductDetailsData?>(null)
    val selectedProductDetails: StateFlow<ProductDetailsData?> = _selectedProductDetails.asStateFlow()

    private val _isCatalogLoading = MutableStateFlow(false)
    val isCatalogLoading: StateFlow<Boolean> = _isCatalogLoading.asStateFlow()

    // --- Экран 4: Категории ---
    private val _categories = MutableStateFlow<List<CategoryItem>>(emptyList())
    val categories: StateFlow<List<CategoryItem>> = _categories.asStateFlow()

    private val _isCategoriesLoading = MutableStateFlow(false)
    val isCategoriesLoading: StateFlow<Boolean> = _isCategoriesLoading.asStateFlow()

    init {
        if (_serverConfig.value.isConfigured) {
            ws.connect(_serverConfig.value)
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

    private fun showMessage(text: String, isError: Boolean = false) {
        _banner.value = BannerMessage(text = text, isError = isError)
        if (isError) feedback.onError() else feedback.onConfirmSuccess()
    }

    // ==================== НАСТРОЙКИ И ПОДКЛЮЧЕНИЕ ====================

    fun saveAndConnect(host: String, port: Int, pin: String, deviceName: String) {
        val updated = app.settings.save(host, port, pin, deviceName)
        _serverConfig.value = updated
        ws.connect(updated)
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
                },
            )
            _isSaleRequestInFlight.value = false

            if (resp.ok) {
                val msg = resp.data?.jsonObject?.get("message")?.jsonPrimitive?.content
                    ?: "Haryt kompýuterdäki satyşa goşuldy"
                _activeProductCard.value = null
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

    // ==================== ЭКРАН 2: ПРИЁМКА ТОВАРОВ (ROOM-ЧЕРНОВИК) ====================

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

    fun onReceivingBundleDetected(bundle: ScanBundle) {
        if (_pendingReceivingDevice.value != null || _isReceivingBusy.value) return
        feedback.onScanSuccess()

        // Если распознан ТОЛЬКО товарный штрихкод (аксессуар, без IMEI и S/N) —
        // добавляем/увеличиваем количество сразу БЕЗ контрольного окна!
        if (bundle.isOnlyProductBarcode) {
            handleAccessoryBarcodeInReceiving(bundle.productBarcode.orEmpty())
            return
        }

        // Если распознаны поля телефона (IMEI 1 / IMEI 2 / S/N) —
        // открываем контрольную карточку с предзаполненными полями и кнопкой «Добавить»
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

        // Резервный вариант (например, одиночный 14–16-значный неточный код)
        val fallback = bundle.allCodes.firstOrNull { it.filter(Char::isDigit).length >= 8 }
        if (!fallback.isNullOrBlank()) {
            _pendingReceivingDevice.value = PendingReceivingDevice(
                imei1 = fallback,
                productBarcode = bundle.productBarcode,
                source = bundle.source,
            )
        }
    }

    private fun handleAccessoryBarcodeInReceiving(barcode: String) {
        val clean = barcode.trim()
        if (clean.isEmpty()) return

        viewModelScope.launch {
            val meta = ensureDraftMetaExists()

            // Если товар уже выбран и включён количественный режим — мгновенно +1 шт. без окон
            if (meta.productId != null && !meta.useImeiMode) {
                val nextQty = meta.nonImeiQuantity + 1
                draftDao.upsertMeta(meta.copy(nonImeiQuantity = nextQty))
                showMessage("+1 sany (${meta.productName}, kod $clean) • Jemi: $nextQty sany", isError = false)
                return@launch
            }

            // Пытаемся автоматически найти товар по штрихкоду на ПК
            if (ws.state.value is ConnectionState.Connected) {
                _isReceivingBusy.value = true
                val resp = ws.sendCommand(
                    type = "scan_code",
                    payload = buildJsonObject {
                        put("code", clean)
                        put("barcode", clean)
                        put("source", "barcode")
                        put("mode", "receive")
                    },
                )
                _isReceivingBusy.value = false

                if (resp.ok && resp.type == "product_card" && resp.data != null) {
                    val card = runCatching {
                        ws.json.decodeFromJsonElement<ProductCardData>(resp.data)
                    }.getOrNull()
                    if (card != null) {
                        val sameProduct = meta.productId == card.productId && !meta.useImeiMode
                        val nextQty = if (sameProduct) meta.nonImeiQuantity + 1 else 1
                        draftDao.upsertMeta(
                            meta.copy(
                                productId = card.productId,
                                productName = card.name,
                                useImeiMode = false,
                                nonImeiQuantity = nextQty,
                                unitCost = meta.unitCost.ifBlank { card.unitCost },
                                currency = if (meta.unitCost.isBlank()) card.costCurrency else meta.currency,
                            )
                        )
                        showMessage("Ştrihkod: ${card.name} ($nextQty sany)", isError = false)
                        return@launch
                    }
                }
            }

            // Если товар уже выбран вручную, просто переключаем в количественный режим и добавляем +1
            if (meta.productId != null) {
                val nextQty = if (meta.useImeiMode) 1 else meta.nonImeiQuantity + 1
                draftDao.upsertMeta(meta.copy(useImeiMode = false, nonImeiQuantity = nextQty))
                showMessage("Aksessuar (${meta.productName}): $nextQty sany (kod $clean)", isError = false)
            } else {
                showMessage("$clean ştrihkody katalogda tapylmady. Haryt saýlaň ýa-da dörediň.", isError = true)
            }
        }
    }

    fun confirmPendingReceivingDevice(
        imei1: String,
        imei2: String,
        serialNumber: String,
        condition: String = "new",
    ) {
        val clean1 = imei1.trim()
        if (clean1.isEmpty()) {
            showMessage("Enjamyň IMEI 1 belgisini giriziň", isError = true)
            return
        }
        _pendingReceivingDevice.value = null
        _scanCooldownTrigger.value += 1
        addReceivingDevice(
            rawImei1 = clean1,
            rawImei2 = imei2.trim().ifBlank { null },
            rawSerial = serialNumber.trim().uppercase().ifBlank { null },
            condition = condition,
        )
    }

    fun dismissPendingReceivingDevice() {
        _pendingReceivingDevice.value = null
        _scanCooldownTrigger.value += 1
    }

    fun addReceivingImei(rawImei: String, condition: String = "new") {
        addReceivingDevice(rawImei1 = rawImei, rawImei2 = null, rawSerial = null, condition = condition)
    }

    fun addReceivingDevice(
        rawImei1: String,
        rawImei2: String? = null,
        rawSerial: String? = null,
        condition: String = "new",
    ) {
        val clean1 = rawImei1.trim()
        val clean2 = rawImei2?.trim()?.ifBlank { null }
        val cleanSn = rawSerial?.trim()?.ifBlank { null }
        if (clean1.isEmpty()) return
        if (clean2 != null && clean1 == clean2) {
            showMessage("IMEI 1 we IMEI 2 birmeňzeş bolup bilmez", isError = true)
            return
        }

        viewModelScope.launch {
            val existing = draftDao.getImeis()
            if (existing.any { it.imei1 == clean1 || it.imei2 == clean1 }) {
                showMessage("IMEI $clean1 şu kabul edişde eýýäm bar", isError = true)
                return@launch
            }
            if (clean2 != null && existing.any { it.imei1 == clean2 || it.imei2 == clean2 }) {
                showMessage("IMEI 2 ($clean2) şu kabul edişde eýýäm bar", isError = true)
                return@launch
            }

            val localLuhn = LuhnValidator.isValidImei(clean1)
            var serverVerified = false

            if (ws.state.value is ConnectionState.Connected) {
                _isReceivingBusy.value = true
                val resp = ws.sendCommand(
                    type = "check_imei",
                    payload = buildJsonObject {
                        put("imei1", clean1)
                        if (clean2 != null) put("imei2", clean2)
                    },
                )
                _isReceivingBusy.value = false

                if (resp.ok && resp.data != null) {
                    val check = runCatching {
                        ws.json.decodeFromJsonElement<ImeiCheckResultData>(resp.data)
                    }.getOrNull()
                    if (check != null && !check.canReceive) {
                        showMessage(check.message.ifBlank { "IMEI $clean1 bazada eýýäm bar" }, isError = true)
                        return@launch
                    }
                    serverVerified = true
                }
            }

            // Переводим мета-черновик в IMEI-режим, если ранее был количественный
            val meta = ensureDraftMetaExists()
            if (!meta.useImeiMode) {
                draftDao.upsertMeta(meta.copy(useImeiMode = true))
            }

            draftDao.insertImei(
                ReceivingDraftImei(
                    imei1 = clean1,
                    imei2 = clean2,
                    serialNumber = cleanSn,
                    condition = condition,
                    luhnValid = localLuhn,
                    serverVerified = serverVerified,
                )
            )
            val extras = buildList {
                if (clean2 != null) add("IMEI2")
                if (cleanSn != null) add("S/N")
            }
            val extraSuffix = if (extras.isNotEmpty()) " (+ ${extras.joinToString(", ")})" else ""
            val warn = if (!localLuhn) " — Luhn barlag sanlaryny barlaň!" else ""
            showMessage("IMEI $clean1 goşuldy$extraSuffix$warn", isError = false)
        }
    }

    fun removeReceivingImei(imei1: String) {
        viewModelScope.launch {
            draftDao.deleteImei(imei1)
        }
    }

    fun clearReceivingDraft() {
        viewModelScope.launch {
            draftDao.clearImeis()
            draftDao.clearMeta()
            ensureDraftMetaExists()
        }
    }

    fun submitReceivingDraft(
        supplierName: String? = null,
        unitCost: String? = null,
        currency: String? = null,
        exchangeRate: String? = null,
        nonImeiQuantity: Int? = null,
        onSuccess: () -> Unit = {},
    ) {
        viewModelScope.launch {
            var meta = ensureDraftMetaExists()
            meta = meta.copy(
                supplierName = supplierName ?: meta.supplierName,
                unitCost = unitCost ?: meta.unitCost,
                currency = currency ?: meta.currency,
                exchangeRate = exchangeRate ?: meta.exchangeRate,
                nonImeiQuantity = nonImeiQuantity ?: meta.nonImeiQuantity,
            )
            draftDao.upsertMeta(meta)
            val imeis = draftDao.getImeis()

            if (meta.productId == null) {
                showMessage("Kabul ediş üçin haryt saýlaň", isError = true)
                return@launch
            }
            val costNum = meta.unitCost.trim().replace(",", ".").toDoubleOrNull()
            if (costNum == null || costNum < 0.0) {
                showMessage("Dogry alyş bahasyny giriziň", isError = true)
                return@launch
            }
            val qty = if (meta.useImeiMode) imeis.size else meta.nonImeiQuantity
            if (qty <= 0) {
                showMessage(
                    if (meta.useImeiMode) "Iň bolmanda bir IMEI skan ediň" else "0-dan uly san giriziň",
                    isError = true,
                )
                return@launch
            }

            _isReceivingBusy.value = true
            val imeiArray: JsonArray = if (meta.useImeiMode) {
                buildJsonArray {
                    imeis.forEach { entry ->
                        add(
                            buildJsonObject {
                                put("imei1", entry.imei1)
                                if (!entry.imei2.isNullOrBlank()) put("imei2", entry.imei2)
                                if (!entry.serialNumber.isNullOrBlank()) put("serial_number", entry.serialNumber)
                                put("condition", entry.condition)
                            }
                        )
                    }
                }
            } else {
                buildJsonArray {}
            }

            val payload = buildJsonObject {
                put("supplier_name", meta.supplierName.trim())
                put("currency", meta.currency)
                put("exchange_rate", meta.exchangeRate.trim().ifBlank { "19.5000" })
                put("note", meta.note.trim().ifBlank { "Android skaner arkaly kabul ediş" })
                put(
                    "items",
                    buildJsonArray {
                        add(
                            buildJsonObject {
                                put("product_id", meta.productId)
                                put("quantity", qty)
                                put("unit_cost", meta.unitCost.trim().replace(",", "."))
                                put("imeis", imeiArray)
                            }
                        )
                    }
                )
            }

            val resp = ws.sendCommand(
                type = "receive_purchase",
                requestId = meta.requestId,
                payload = payload,
                timeoutMs = 15_000L,
            )
            _isReceivingBusy.value = false

            if (resp.ok) {
                val msg = resp.data?.jsonObject?.get("message")?.jsonPrimitive?.content
                    ?: "Kabul ediş üstünlikli ýerine ýetirildi"
                // Очищаем Room-черновик ТОЛЬКО после подтверждения сервера
                draftDao.clearImeis()
                draftDao.clearMeta()
                ensureDraftMetaExists()
                showMessage(msg, isError = false)
                loadCatalog()
                onSuccess()
            } else {
                showMessage(resp.error?.message ?: "Kabul ediş ýalňyşlygy. Garalama telefonda saklandy.", isError = true)
            }
        }
    }

    // ==================== ЭКРАН 3: КАТАЛОГ ТОВАРОВ ====================

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
                put("min_stock_quantity", minStock)
                val cleanCost = defaultCost.trim().replace(",", ".")
                if ((cleanCost.toDoubleOrNull() ?: 0.0) > 0.0) {
                    put("unit_cost", cleanCost)
                    put("cost_currency", costCurrency)
                }
                if (productId == null) put("allow_duplicate", allowDuplicate)
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

    // ==================== ЭКРАН 4: КАТЕГОРИИ ====================

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
