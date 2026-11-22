package com.mobilestore.scanner.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.ListAlt
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.data.ReceivingDraftImei
import com.mobilestore.scanner.data.ReceivingDraftMeta
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.scanner.CameraPreviewView
import com.mobilestore.scanner.scanner.LuhnValidator
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TealAccent
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.ui.theme.TextPrimary
import com.mobilestore.scanner.viewmodel.ScannerViewModel

/**
 * Экран 2: Приёмка товара на склад.
 * - Полноэкранная камера с теми же размерами и HUD-панелью, что и на экране «Сканер»
 * - Телефоны (IMEI 1 + IMEI 2 + S/N) -> контрольная карточка с кнопкой «Добавить»
 * - Только товарный штрихкод (аксессуар) -> +1 шт. сразу без контрольного окна
 * - Данные закупки (поставщик, цена, валюта, курс, список IMEI) открываются в удобном Bottom Sheet
 * - Все поля ввода используют локальный Compose state (без блокировки удаления цифр и скачков курсора)
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReceivingScreen(
    vm: ScannerViewModel,
    hasCameraPermission: Boolean,
    onRequestCameraPermission: () -> Unit,
) {
    val connState by vm.connectionState.collectAsState()
    val config by vm.serverConfig.collectAsState()
    val draftMeta by vm.receivingMeta.collectAsState()
    val draftImeis by vm.receivingImeis.collectAsState()
    val pendingDevice by vm.pendingReceivingDevice.collectAsState()
    val isBusy by vm.isReceivingBusy.collectAsState()
    val catalog by vm.catalogProducts.collectAsState()
    val categories by vm.categories.collectAsState()
    val cooldownTrigger by vm.scanCooldownTrigger.collectAsState()
    val receivingOcrResult by vm.receivingOcrResult.collectAsState()
    val receivingOcrCatFilter by vm.receivingOcrCategoryFilter.collectAsState()

    var cameraStatus by remember { mutableStateOf("Işjeň") }
    var ocrEnabled by remember { mutableStateOf(true) }
    var showPurchaseSheet by remember { mutableStateOf(false) }
    var showProductPicker by remember { mutableStateOf(false) }
    var showCreateProduct by remember { mutableStateOf(false) }
    var createProductPrefill by remember { mutableStateOf<com.mobilestore.scanner.network.AccessoryDraftSuggestion?>(null) }
    var createProductOcrRawText by remember { mutableStateOf<String?>(null) }
    var showManualImeiDialog by remember { mutableStateOf(false) }
    var boxCaptureTrigger by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) {
        if (catalog.isEmpty()) vm.loadCatalog()
        if (categories.isEmpty()) vm.loadCategories()
    }

    val meta = draftMeta
    val useImeiMode = meta?.useImeiMode ?: true
    val batchCount = if (useImeiMode) draftImeis.size else (meta?.nonImeiQuantity ?: 0)
    val batchBadge = if (useImeiMode) "$batchCount IMEI" else "$batchCount sany"

    val isPaused = pendingDevice != null ||
        receivingOcrResult != null ||
        showPurchaseSheet ||
        showProductPicker ||
        showCreateProduct ||
        showManualImeiDialog ||
        isBusy

    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        if (hasCameraPermission) {
            CameraPreviewView(
                isPaused = isPaused,
                enableOcr = ocrEnabled,
                burstWindowMs = 800L,
                cooldownMs = config.scanCooldownMs,
                cooldownTriggerKey = cooldownTrigger,
                boxCaptureTriggerKey = boxCaptureTrigger,
                onDetected = { vm.onReceivingBundleDetected(it) },
                onBoxTextCaptured = { rawText -> vm.matchAccessoryForReceiving(rawText) },
                onCameraStatusChanged = { cameraStatus = it },
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(
                modifier = Modifier.fillMaxSize().padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Kabul edişde gutulary skan etmek üçin kamera rugsaty gerek",
                    color = Color.White,
                    fontSize = 16.sp,
                )
                Spacer(Modifier.height(14.dp))
                Button(
                    onClick = onRequestCameraPermission,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                ) {
                    Text("Kamera rugsat ber")
                }
            }
        }

        // Компактный светящийся индикатор подключения + короткий бейдж товара и партии
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp)
                .align(Alignment.TopCenter),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val prodTitle = meta?.productName?.ifBlank { null }
            val pillLabel = if (prodTitle != null) "$prodTitle • $batchBadge" else batchBadge
            ConnectionGlowPill(state = connState, trailingText = pillLabel)

            Surface(
                color = NavyDark.copy(alpha = 0.72f),
                shape = RoundedCornerShape(16.dp),
            ) {
                Text(
                    text = "Kabul ediş",
                    color = AccentOrange,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                )
            }
        }

        // Нижняя компактная панель действий поверх камеры (не перекрывает фонарик справа)
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 14.dp, end = 84.dp, bottom = 14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(
                    onClick = { boxCaptureTrigger += 1 },
                    enabled = !isBusy && hasCameraPermission,
                    border = BorderStroke(1.dp, AccentOrange),
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = NavyDark.copy(alpha = 0.86f),
                        contentColor = AccentOrange,
                    ),
                ) {
                    Icon(Icons.Default.DocumentScanner, contentDescription = null)
                    Spacer(Modifier.width(4.dp))
                    Text("Guty OCR", maxLines = 1, fontWeight = FontWeight.Bold)
                }
                OutlinedButton(
                    onClick = { showProductPicker = true },
                    border = BorderStroke(1.dp, BorderColor.copy(alpha = 0.5f)),
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = NavyDark.copy(alpha = 0.82f),
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Inventory2, contentDescription = null)
                    Spacer(Modifier.width(4.dp))
                    Text("Haryt", maxLines = 1)
                }
                OutlinedButton(
                    onClick = { showManualImeiDialog = true },
                    border = BorderStroke(1.dp, BorderColor.copy(alpha = 0.5f)),
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = NavyDark.copy(alpha = 0.82f),
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Keyboard, contentDescription = null)
                }
            }

            Button(
                onClick = { showPurchaseSheet = true },
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Icon(Icons.Default.ListAlt, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Alyş maglumaty we sanaw ($batchBadge)",
                    fontWeight = FontWeight.Bold,
                )
            }
        }

        if (isBusy) {
            Box(
                modifier = Modifier.fillMaxSize().background(Color(0x66000000)),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator(color = AccentOrange)
            }
        }
    }

    val recOcrRes = receivingOcrResult
    if (recOcrRes != null) {
        ModalBottomSheet(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) vm.dismissReceivingOcr() },
        ) {
            AccessoryOcrResultSheet(
                result = recOcrRes,
                isBusy = isBusy,
                selectedCategoryId = receivingOcrCatFilter,
                showCreateNewButton = true,
                onRequery = { editedText, catId -> vm.matchAccessoryForReceiving(editedText, catId) },
                onSelectProduct = { chosen ->
                    vm.selectAccessoryForReceiving(chosen)
                    showPurchaseSheet = true
                },
                onCreateNewFromDraft = { draft, rawText ->
                    vm.dismissReceivingOcr()
                    createProductPrefill = draft
                    createProductOcrRawText = rawText
                    showCreateProduct = true
                },
                onDismiss = { vm.dismissReceivingOcr() },
            )
        }
    }

    // Модальный лист (Bottom Sheet) с данными закупки и списком отсканированных IMEI
    if (showPurchaseSheet) {
        ModalBottomSheet(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) showPurchaseSheet = false },
        ) {
            ReceivingPurchaseSheet(
                meta = meta,
                imeis = draftImeis,
                isBusy = isBusy,
                onPickProduct = { showProductPicker = true },
                onCreateProduct = { showCreateProduct = true },
                onModeChanged = { imeiMode -> vm.updateReceivingMeta(useImeiMode = imeiMode) },
                onRemoveImei = { vm.removeReceivingImei(it) },
                onPersistFields = { sup, cost, curr, rate, qty ->
                    vm.updateReceivingMeta(
                        supplierName = sup,
                        unitCost = cost,
                        currency = curr,
                        exchangeRate = rate,
                        nonImeiQuantity = qty,
                    )
                },
                onClearDraft = {
                    vm.clearReceivingDraft()
                    showPurchaseSheet = false
                },
                onSubmit = { sup, cost, curr, rate, qty ->
                    vm.submitReceivingDraft(
                        supplierName = sup,
                        unitCost = cost,
                        currency = curr,
                        exchangeRate = rate,
                        nonImeiQuantity = qty,
                        onSuccess = { showPurchaseSheet = false },
                    )
                },
            )
        }
    }

    // Контрольное окно для смартфонов (когда считаны IMEI 1 / IMEI 2 / S/N)
    val dev = pendingDevice
    if (dev != null) {
        var editImei1 by remember(dev) { mutableStateOf(dev.imei1) }
        var editImei2 by remember(dev) { mutableStateOf(dev.imei2) }
        var editSerial by remember(dev) { mutableStateOf(dev.serialNumber) }
        val luhnOk = LuhnValidator.isValidImei(editImei1)

        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { vm.dismissPendingReceivingDevice() },
            title = { Text("Enjam maglumatlaryny barlaň", color = NavyDark) },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        DetectedFieldBadge("IMEI 1", editImei1.isNotBlank())
                        DetectedFieldBadge("IMEI 2", editImei2.isNotBlank())
                        DetectedFieldBadge("S/N", editSerial.isNotBlank())
                        if (!dev.productBarcode.isNullOrBlank()) {
                            DetectedFieldBadge("EAN", true)
                        }
                    }

                    OutlinedTextField(
                        value = editImei1,
                        onValueChange = { editImei1 = it },
                        label = { Text("IMEI 1 *") },
                        supportingText = {
                            Text(
                                text = if (luhnOk) "Luhn barlagy dogry" else "IMEI 1-iň 15 sanyny barlaň",
                                color = if (luhnOk) GreenSuccess else AccentOrange,
                            )
                        },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = editImei2,
                        onValueChange = { editImei2 = it },
                        label = { Text("IMEI 2 (2 SIM bolsa)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = editSerial,
                        onValueChange = { editSerial = it },
                        label = { Text("Seriýa belgisi (S/N)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (!dev.productBarcode.isNullOrBlank()) {
                        Text(
                            text = "Gutynyň ştrihkody: ${dev.productBarcode}",
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            color = TextMuted,
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    enabled = editImei1.isNotBlank(),
                    onClick = { vm.confirmPendingReceivingDevice(editImei1, editImei2, editSerial) },
                ) {
                    Text("Goş")
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.dismissPendingReceivingDevice() }) {
                    Text("Ýatyr")
                }
            },
        )
    }

    // Ручной ввод IMEI (если этикетка повреждена)
    if (showManualImeiDialog) {
        var manualImei1 by remember { mutableStateOf("") }
        var manualImei2 by remember { mutableStateOf("") }
        var manualSn by remember { mutableStateOf("") }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { showManualImeiDialog = false },
            title = { Text("IMEI el bilen goş", color = NavyDark) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = manualImei1,
                        onValueChange = { manualImei1 = it },
                        label = { Text("IMEI 1 (15 san) *") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = manualImei2,
                        onValueChange = { manualImei2 = it },
                        label = { Text("IMEI 2 (hökmany däl)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = manualSn,
                        onValueChange = { manualSn = it },
                        label = { Text("Seriýa belgisi S/N (hökmany däl)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    enabled = manualImei1.isNotBlank(),
                    onClick = {
                        vm.addReceivingDevice(manualImei1, manualImei2, manualSn)
                        showManualImeiDialog = false
                    },
                ) { Text("Goş") }
            },
            dismissButton = {
                TextButton(onClick = { showManualImeiDialog = false }) { Text("Ýatyr") }
            },
        )
    }

    if (showProductPicker) {
        var filter by remember { mutableStateOf("") }
        val filtered = remember(catalog, filter) {
            val q = filter.trim().lowercase()
            if (q.isEmpty()) catalog
            else catalog.filter {
                "${it.name} ${it.brand} ${it.model} ${it.specification} ${it.sku}".lowercase().contains(q)
            }
        }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { showProductPicker = false },
            title = {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Haryt saýlaň", color = NavyDark)
                    TextButton(onClick = {
                        showProductPicker = false
                        showCreateProduct = true
                    }) {
                        Text("+ Täze", color = AccentOrange)
                    }
                }
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = filter,
                        onValueChange = { filter = it },
                        label = { Text("Gözleg…") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    LazyColumn(modifier = Modifier.height(280.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(filtered, key = { it.id }) { prod ->
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        vm.updateReceivingMeta(productId = prod.id, productName = prod.name)
                                        showProductPicker = false
                                    },
                                colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                                border = BorderStroke(1.dp, BorderColor),
                            ) {
                                Column(modifier = Modifier.padding(10.dp)) {
                                    Text(prod.name, fontWeight = FontWeight.Bold, color = NavyDark)
                                    Text(
                                        "${prod.brand} ${prod.model} ${prod.specification}".trim(),
                                        fontSize = 12.sp,
                                        color = TextMuted,
                                    )
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showProductPicker = false }) { Text("Ýap") }
            },
        )
    }

    if (showCreateProduct) {
        val hadOcrPrefill = createProductPrefill != null
        ProductEditorDialog(
            categories = categories.filter { it.isActive },
            existing = null,
            prefill = createProductPrefill,
            onDismiss = {
                showCreateProduct = false
                createProductPrefill = null
                createProductOcrRawText = null
            },
            onSave = { name, catId, brand, model, mem, color, extra, minStock, cost, costCurr ->
                val rawAlias = createProductOcrRawText
                vm.saveProduct(
                    productId = null,
                    name = name,
                    categoryId = catId,
                    brand = brand,
                    model = model,
                    memory = mem,
                    color = color,
                    extraSpecs = extra,
                    minStock = minStock,
                    defaultCost = cost,
                    costCurrency = costCurr,
                    ocrRawText = rawAlias,
                ) { createdId, createdName ->
                    if (createdId != null) {
                        vm.updateReceivingMeta(
                            productId = createdId,
                            productName = createdName,
                            useImeiMode = if (hadOcrPrefill) false else null,
                            unitCost = cost.takeIf { it.isNotBlank() },
                            currency = costCurr.takeIf { it == "USD" || it == "TMT" },
                        )
                        if (hadOcrPrefill) {
                            showPurchaseSheet = true
                        }
                    }
                    showCreateProduct = false
                    createProductPrefill = null
                    createProductOcrRawText = null
                }
            },
        )
    }
}

@Composable
private fun ReceivingPurchaseSheet(
    meta: ReceivingDraftMeta?,
    imeis: List<ReceivingDraftImei>,
    isBusy: Boolean,
    onPickProduct: () -> Unit,
    onCreateProduct: () -> Unit,
    onModeChanged: (Boolean) -> Unit,
    onRemoveImei: (String) -> Unit,
    onPersistFields: (supplier: String, cost: String, currency: String, rate: String, qty: Int) -> Unit,
    onClearDraft: () -> Unit,
    onSubmit: (supplier: String, cost: String, currency: String, rate: String, qty: Int) -> Unit,
) {
    val useImeiMode = meta?.useImeiMode ?: true

    // Чистый локальный Compose state — удаление всех символов (включая первую цифру) работает мгновенно!
    var supplierText by remember(meta?.requestId) { mutableStateOf(meta?.supplierName ?: "") }
    var unitCostText by remember(meta?.requestId) {
        mutableStateOf(
            meta?.unitCost?.takeIf { it.isNotBlank() && it != "0.00" && it != "0" } ?: ""
        )
    }
    var currency by remember(meta?.requestId) { mutableStateOf(meta?.currency ?: "USD") }
    var rateText by remember(meta?.requestId) { mutableStateOf(meta?.exchangeRate ?: "19.5000") }
    var qtyText by remember(meta?.requestId) {
        mutableStateOf((meta?.nonImeiQuantity ?: 1).toString())
    }

    val chipColors = FilterChipDefaults.filterChipColors(
        selectedContainerColor = AccentBg,
        selectedLabelColor = AccentOrange,
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 18.dp)
            .padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Kabul edişi resmileşdirmek", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = NavyDark)

        // Товар
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceBg),
            border = BorderStroke(1.dp, BorderColor),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Haryt", fontSize = 11.sp, color = TextMuted)
                    Text(
                        text = meta?.productName?.ifBlank { "Saýlanmadyk" } ?: "Saýlanmadyk",
                        fontWeight = FontWeight.Bold,
                        color = NavyDark,
                        fontSize = 15.sp,
                    )
                }
                TextButton(onClick = onPickProduct) { Text("Saýla", color = AccentOrange) }
                TextButton(onClick = onCreateProduct) { Text("+ Täze", color = NavyDark) }
            }
        }

        // Режим приёмки
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = useImeiMode,
                onClick = { onModeChanged(true) },
                label = { Text("IMEI bilen (${imeis.size} sany)") },
                colors = chipColors,
            )
            FilterChip(
                selected = !useImeiMode,
                onClick = { onModeChanged(false) },
                label = { Text("Sany bilen") },
                colors = chipColors,
            )
        }

        // Поля закупки (полностью локальный state -> все цифры свободно стираются)
        OutlinedTextField(
            value = supplierText,
            onValueChange = {
                supplierText = it
                onPersistFields(it, unitCostText, currency, rateText, qtyText.toIntOrNull() ?: 1)
            },
            label = { Text("Üpjün ediji") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = unitCostText,
                onValueChange = {
                    unitCostText = it
                    onPersistFields(supplierText, it, currency, rateText, qtyText.toIntOrNull() ?: 1)
                },
                label = { Text("Alyş bahasy ($currency)") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                modifier = Modifier.weight(1.2f),
            )
            OutlinedTextField(
                value = rateText,
                onValueChange = {
                    rateText = it
                    onPersistFields(supplierText, unitCostText, currency, it, qtyText.toIntOrNull() ?: 1)
                },
                label = { Text("Kurs") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Alyş walýutasy:", fontSize = 13.sp, color = TextMuted)
            FilterChip(
                selected = currency == "USD",
                onClick = {
                    currency = "USD"
                    onPersistFields(supplierText, unitCostText, "USD", rateText, qtyText.toIntOrNull() ?: 1)
                },
                label = { Text("USD") },
                colors = chipColors,
            )
            FilterChip(
                selected = currency == "TMT",
                onClick = {
                    currency = "TMT"
                    onPersistFields(supplierText, unitCostText, "TMT", rateText, qtyText.toIntOrNull() ?: 1)
                },
                label = { Text("TMT") },
                colors = chipColors,
            )
        }

        HorizontalDivider(color = BorderColor)

        if (useImeiMode) {
            Text(
                text = "Skan edilen enjamlar (${imeis.size}):",
                fontWeight = FontWeight.Bold,
                color = NavyDark,
                fontSize = 14.sp,
            )
            if (imeis.isEmpty()) {
                Text(
                    text = "Häzirlikçe skan edilen IMEI ýok. Aýnany ýapyň we kamerany gutynyň etiketkasyna tutyň.",
                    fontSize = 12.sp,
                    color = TextMuted,
                )
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(imeis, key = { it.imei1 }) { entry ->
                        Card(
                            colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                            border = BorderStroke(1.dp, BorderColor),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(
                                    imageVector = if (entry.luhnValid) Icons.Default.CheckCircle else Icons.Default.Warning,
                                    contentDescription = null,
                                    tint = if (entry.luhnValid) GreenSuccess else AccentOrange,
                                )
                                Spacer(Modifier.width(8.dp))
                                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                    Text(
                                        text = "IMEI 1: ${entry.imei1}",
                                        fontFamily = FontFamily.Monospace,
                                        fontWeight = FontWeight.Bold,
                                        color = TextPrimary,
                                        fontSize = 13.sp,
                                    )
                                    if (!entry.imei2.isNullOrBlank()) {
                                        Text(
                                            text = "IMEI 2: ${entry.imei2}",
                                            fontFamily = FontFamily.Monospace,
                                            color = TextMuted,
                                            fontSize = 12.sp,
                                        )
                                    }
                                    if (!entry.serialNumber.isNullOrBlank()) {
                                        Text(
                                            text = "S/N:    ${entry.serialNumber}",
                                            fontFamily = FontFamily.Monospace,
                                            color = TealAccent,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.SemiBold,
                                        )
                                    }
                                }
                                IconButton(onClick = { onRemoveImei(entry.imei1) }) {
                                    Icon(Icons.Default.Delete, contentDescription = "Poz", tint = RedDanger)
                                }
                            }
                        }
                    }
                }
            }
        } else {
            OutlinedTextField(
                value = qtyText,
                onValueChange = { raw ->
                    val filtered = raw.filter(Char::isDigit)
                    qtyText = filtered
                    val parsed = filtered.toIntOrNull()
                    if (parsed != null && parsed > 0) {
                        onPersistFields(supplierText, unitCostText, currency, rateText, parsed)
                    }
                },
                label = { Text("Sany") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        Spacer(Modifier.height(4.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedButton(
                onClick = onClearDraft,
                enabled = !isBusy,
                border = BorderStroke(1.dp, BorderColor),
                modifier = Modifier.weight(1f).height(48.dp),
            ) {
                Text("Arassala")
            }
            Button(
                onClick = {
                    val qtyVal = qtyText.toIntOrNull() ?: 0
                    onSubmit(supplierText, unitCostText, currency, rateText, qtyVal)
                },
                enabled = !isBusy,
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                modifier = Modifier.weight(1.8f).height(48.dp),
            ) {
                val countLabel = if (useImeiMode) "${imeis.size} IMEI" else "${qtyText.toIntOrNull() ?: 0} sany"
                Text(if (isBusy) "Iberilýär…" else "Kabul et ($countLabel)")
            }
        }
    }
}

@Composable
private fun DetectedFieldBadge(label: String, detected: Boolean) {
    val bg = if (detected) GreenSuccess.copy(alpha = 0.14f) else SurfaceBg
    val fg = if (detected) GreenSuccess else TextMuted
    Surface(color = bg, shape = RoundedCornerShape(6.dp)) {
        Text(
            text = if (detected) "$label ✔" else "$label —",
            color = fg,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}
