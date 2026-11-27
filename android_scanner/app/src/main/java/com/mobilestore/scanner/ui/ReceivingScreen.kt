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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.ListAlt
import androidx.compose.material.icons.filled.MoveToInbox
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
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
import androidx.compose.runtime.mutableIntStateOf
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
import com.mobilestore.scanner.data.ReceivingDraftMeta
import com.mobilestore.scanner.network.IncomingQueueCounts
import com.mobilestore.scanner.scanner.CameraPreviewView
import com.mobilestore.scanner.scanner.LuhnValidator
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TealAccent
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.ui.theme.TextPrimary
import com.mobilestore.scanner.viewmodel.ScannerViewModel
import com.mobilestore.scanner.viewmodel.SessionQueuedEntry

/**
 * Экран 2: Kabul ediş (Лёгкая станция сканирования -> Буферная очередь ПК).
 * - Режим 1: «IMEI bilen» (Telefon) — сканирование IMEI/SN и мгновенная отправка в вкладку ПК «Telefonlar (IMEI)»
 *   без выбора товара или категории на телефоне.
 * - Режим 2: «Sany bilen» (Haryt / Aksessuar) — сканирование штрихкода (+1 сразу в «Belli» / «Näbelli»),
 *   Guty OCR (выбор известного или отправка как «Näbelli»), либо выбор существующего товара из каталога.
 * - Без создания новых товаров на телефоне и без прямой записи в складскую БД.
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
    val pendingDevice by vm.pendingReceivingDevice.collectAsState()
    val pendingBarcode by vm.pendingBarcodeScan.collectAsState()
    val isBusy by vm.isReceivingBusy.collectAsState()
    val catalog by vm.catalogProducts.collectAsState()
    val cooldownTrigger by vm.scanCooldownTrigger.collectAsState()
    val receivingOcrResult by vm.receivingOcrResult.collectAsState()
    val receivingOcrCatFilter by vm.receivingOcrCategoryFilter.collectAsState()
    val queueCounts by vm.incomingQueueCounts.collectAsState()
    val sessionEntries by vm.sessionQueuedEntries.collectAsState()

    var cameraStatus by remember { mutableStateOf("Işjeň") }
    var showQueueSheet by remember { mutableStateOf(false) }
    var showProductPicker by remember { mutableStateOf(false) }
    var openSheetAfterPicker by remember { mutableStateOf(false) }
    var showManualBarcodeDialog by remember { mutableStateOf(false) }
    var boxCaptureTrigger by remember { mutableIntStateOf(0) }

    val meta = draftMeta
    val useImeiMode = meta?.useImeiMode ?: true

    LaunchedEffect(useImeiMode) {
        if (!useImeiMode && catalog.isEmpty()) {
            vm.loadCatalog()
        }
    }

    val isPaused = pendingDevice != null ||
        pendingBarcode != null ||
        receivingOcrResult != null ||
        showQueueSheet ||
        showProductPicker ||
        showManualBarcodeDialog ||
        isBusy

    val queuePillLabel = if (queueCounts.total > 0) {
        "PK: ${queueCounts.phoneImei} tel • ${queueCounts.known} belli • ${queueCounts.unknown} näb"
    } else {
        "PK nobaty: 0"
    }

    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        if (hasCameraPermission) {
            CameraPreviewView(
                isPaused = isPaused,
                enableOcr = useImeiMode,
                burstWindowMs = if (useImeiMode) 800L else 350L,
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

        // Верхняя панель: индикатор ПК-очереди + переключатель режима (IMEI bilen / Sany bilen)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp)
                .align(Alignment.TopCenter),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ConnectionGlowPill(state = connState, trailingText = queuePillLabel)

                Surface(
                    color = NavyDark.copy(alpha = 0.78f),
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

            // Явный 2-позиционный переключатель режима прямо на экране камеры
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ReceivingModeTogglePill(
                    label = "IMEI bilen",
                    subtitle = "Telefon",
                    icon = Icons.Default.PhoneAndroid,
                    selected = useImeiMode,
                    onClick = { vm.updateReceivingMeta(useImeiMode = true) },
                    modifier = Modifier.weight(1f),
                )
                ReceivingModeTogglePill(
                    label = "Sany bilen",
                    subtitle = "Haryt / Aksessuar",
                    icon = Icons.Default.Inventory2,
                    selected = !useImeiMode,
                    onClick = {
                        vm.updateReceivingMeta(useImeiMode = false)
                        if (catalog.isEmpty()) vm.loadCatalog()
                    },
                    modifier = Modifier.weight(1f),
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
            if (useImeiMode) {
                // Режим 1: IMEI bilen (Telefon) — НИКАКИХ кнопок «Haryt» и «+ Täze»!
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = { vm.openManualPhoneDialog() },
                        enabled = !isBusy,
                        border = BorderStroke(1.dp, AccentOrange),
                        colors = ButtonDefaults.outlinedButtonColors(
                            containerColor = NavyDark.copy(alpha = 0.86f),
                            contentColor = AccentOrange,
                        ),
                    ) {
                        Icon(Icons.Default.Keyboard, contentDescription = null)
                        Spacer(Modifier.width(6.dp))
                        Text("El bilen IMEI", maxLines = 1, fontWeight = FontWeight.Bold)
                    }
                }
            } else {
                // Режим 2: Sany bilen (Haryt / Aksessuar) — «Guty OCR» + «Haryt» (read-only) + ручной штрихкод
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
                        onClick = {
                            if (catalog.isEmpty()) vm.loadCatalog()
                            openSheetAfterPicker = true
                            showProductPicker = true
                        },
                        enabled = !isBusy,
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
                        onClick = { showManualBarcodeDialog = true },
                        enabled = !isBusy,
                        border = BorderStroke(1.dp, BorderColor.copy(alpha = 0.5f)),
                        colors = ButtonDefaults.outlinedButtonColors(
                            containerColor = NavyDark.copy(alpha = 0.82f),
                            contentColor = Color.White,
                        ),
                    ) {
                        Icon(Icons.Default.Keyboard, contentDescription = null)
                    }
                }
            }

            Button(
                onClick = { showQueueSheet = true },
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Icon(Icons.Default.ListAlt, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                val btnText = if (useImeiMode) {
                    "PK nobaty we sazlama (${queueCounts.phoneImei} tel • ${sessionEntries.size})"
                } else {
                    val selName = meta?.productName?.takeIf { it.isNotBlank() }
                    if (selName != null) "PK nobatyna iber • $selName" else "PK nobatyna iber (${queueCounts.total})"
                }
                Text(
                    text = btnText,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
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

    // Лист результатов Guty OCR (ТОЛЬКО в режиме Sany bilen, БЕЗ создания товара на телефоне!)
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
                showCreateNewButton = false,
                onRequery = { editedText, catId -> vm.matchAccessoryForReceiving(editedText, catId) },
                onSelectProduct = { chosen ->
                    vm.queueOcrMatchedProductToPc(chosen, recOcrRes.rawText)
                },
                onDismiss = { vm.dismissReceivingOcr() },
            )
            OutlinedButton(
                onClick = {
                    vm.queueOcrUnknownToPc(
                        rawText = recOcrRes.rawText,
                        modelHint = recOcrRes.parsed.cleanedQuery,
                    )
                },
                enabled = !isBusy,
                border = BorderStroke(1.5.dp, AccentOrange),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = AccentOrange),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp)
                    .padding(bottom = 24.dp)
                    .height(48.dp),
            ) {
                Icon(Icons.Default.MoveToInbox, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(
                    text = "Näbelli hökmünde PK nobatyna iber",
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }

    // Нижний лист (Bottom Sheet): PK nobaty, настройки валюты/поставщика и ручная отправка количества
    if (showQueueSheet) {
        ModalBottomSheet(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) showQueueSheet = false },
        ) {
            ReceivingQueueBottomSheet(
                meta = meta,
                queueCounts = queueCounts,
                sessionEntries = sessionEntries,
                isBusy = isBusy,
                onModeChanged = { imeiMode ->
                    vm.updateReceivingMeta(useImeiMode = imeiMode)
                    if (!imeiMode && catalog.isEmpty()) vm.loadCatalog()
                },
                onPickProduct = {
                    if (catalog.isEmpty()) vm.loadCatalog()
                    openSheetAfterPicker = false
                    showProductPicker = true
                },
                onClearProduct = { vm.clearReceivingSelectedProduct() },
                onPersistDefaults = { sup, curr ->
                    vm.updateReceivingMeta(supplierName = sup, currency = curr)
                },
                onSendQuantityProduct = { qty, cost, curr, sup, note ->
                    vm.queueQuantityProductToPc(
                        productId = meta?.productId,
                        productName = meta?.productName.orEmpty(),
                        quantity = qty,
                        unitCost = cost,
                        currency = curr,
                        supplierName = sup,
                        modelHint = note,
                        onSuccess = { showQueueSheet = false },
                    )
                },
                onClearSession = { vm.clearSessionQueuedEntries() },
            )
        }
    }

    // Единое окно подтверждения телефона (как после скана камерой, так и при ручном вводе IMEI)
    val dev = pendingDevice
    if (dev != null) {
        var editImei1 by remember(dev) { mutableStateOf(dev.imei1) }
        var editImei2 by remember(dev) { mutableStateOf(dev.imei2) }
        var editSerial by remember(dev) { mutableStateOf(dev.serialNumber) }
        var condition by remember(dev) { mutableStateOf("new") }
        var modelHint by remember(dev) { mutableStateOf("") }
        var unitCost by remember(dev) { mutableStateOf("") }
        var currency by remember(dev) { mutableStateOf(meta?.currency?.ifBlank { "USD" } ?: "USD") }
        val luhnOk = LuhnValidator.isValidImei(editImei1)
        val chipColors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = AccentBg,
            selectedLabelColor = AccentOrange,
        )

        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) vm.dismissPendingReceivingDevice() },
            title = {
                Text(
                    text = if (dev.source == "manual") "Telefony PK nobatyna iber" else "Telefon maglumatlaryny barlaň",
                    color = NavyDark,
                )
            },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (dev.source != "manual") {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            DetectedFieldBadge("IMEI 1", editImei1.isNotBlank())
                            DetectedFieldBadge("IMEI 2", editImei2.isNotBlank())
                            DetectedFieldBadge("S/N", editSerial.isNotBlank())
                            if (!dev.productBarcode.isNullOrBlank()) {
                                DetectedFieldBadge("EAN", true)
                            }
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

                    // Быстрый переключатель Täze / B/U
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Ýagdaýy:", fontSize = 13.sp, color = TextMuted)
                        FilterChip(
                            selected = condition == "new",
                            onClick = { condition = "new" },
                            label = { Text("Täze") },
                            colors = chipColors,
                        )
                        FilterChip(
                            selected = condition == "used",
                            onClick = { condition = "used" },
                            label = { Text("B/U") },
                            colors = chipColors,
                        )
                    }

                    OutlinedTextField(
                        value = modelHint,
                        onValueChange = { modelHint = it },
                        label = { Text("Model / bellik (hökmany däl)") },
                        placeholder = { Text("Mysal: 15pm 256 blk") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        OutlinedTextField(
                            value = unitCost,
                            onValueChange = { unitCost = it },
                            label = { Text("Alyş bahasy (hökm. däl)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        FilterChip(
                            selected = currency == "USD",
                            onClick = { currency = "USD" },
                            label = { Text("USD", fontSize = 12.sp) },
                            colors = chipColors,
                        )
                        FilterChip(
                            selected = currency == "TMT",
                            onClick = { currency = "TMT" },
                            label = { Text("TMT", fontSize = 12.sp) },
                            colors = chipColors,
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    enabled = !isBusy && editImei1.isNotBlank(),
                    onClick = {
                        vm.queuePhoneToPc(
                            imei1 = editImei1,
                            imei2 = editImei2,
                            serialNumber = editSerial,
                            condition = condition,
                            modelHint = modelHint,
                            unitCost = unitCost,
                            currency = currency,
                            productBarcode = dev.productBarcode,
                            requestId = dev.requestId,
                        )
                    },
                ) {
                    Text(if (isBusy) "Iberilýär…" else "PK nobatyna iber")
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !isBusy,
                    onClick = { vm.dismissPendingReceivingDevice() },
                ) {
                    Text("Ýatyr")
                }
            },
        )
    }

    // Окно подтверждения отсканированного штрихкода в режиме Sany bilen (с полем примечания)
    val pb = pendingBarcode
    if (pb != null) {
        var scanQty by remember(pb) { mutableStateOf("1") }
        var scanNote by remember(pb) { mutableStateOf("") }
        var scanCost by remember(pb) { mutableStateOf("") }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) vm.dismissPendingBarcodeScan() },
            title = { Text("Harydy PK nobatyna iber", color = NavyDark) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Surface(
                        color = SurfaceBg,
                        shape = RoundedCornerShape(8.dp),
                        border = BorderStroke(1.dp, BorderColor),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
                            Text("Ştrihkod", fontSize = 11.sp, color = TextMuted)
                            Text(
                                text = pb.barcode,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                color = NavyDark,
                                fontSize = 14.sp,
                            )
                        }
                    }
                    OutlinedTextField(
                        value = scanNote,
                        onValueChange = { scanNote = it },
                        label = { Text("Bellik (ady, reňki, modeli…)") },
                        placeholder = { Text("Mysal: Nauşnik gara / Çehol 15PM") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = scanQty,
                            onValueChange = { scanQty = it.filter(Char::isDigit) },
                            label = { Text("Sany") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = scanCost,
                            onValueChange = { scanCost = it },
                            label = { Text("Alyş bahasy") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            singleLine = true,
                            modifier = Modifier.weight(1.3f),
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    enabled = !isBusy,
                    onClick = {
                        val qtyVal = (scanQty.toIntOrNull() ?: 1).coerceAtLeast(1)
                        vm.queueBarcodeQuantityToPc(
                            barcode = pb.barcode,
                            quantity = qtyVal,
                            unitCost = scanCost,
                            modelHint = scanNote,
                        )
                    },
                ) {
                    Text(if (isBusy) "Iberilýär…" else "PK nobatyna iber")
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !isBusy,
                    onClick = { vm.dismissPendingBarcodeScan() },
                ) {
                    Text("Ýatyr")
                }
            },
        )
    }

    // Ручной ввод штрихкода в режиме Sany bilen
    if (showManualBarcodeDialog) {
        var manualCode by remember { mutableStateOf("") }
        var manualQty by remember { mutableStateOf("1") }
        var manualNote by remember { mutableStateOf("") }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) showManualBarcodeDialog = false },
            title = { Text("Ştrihkody PK nobatyna iber", color = NavyDark) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = manualCode,
                        onValueChange = { manualCode = it },
                        label = { Text("Ştrihkod / SKU *") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = manualNote,
                        onValueChange = { manualNote = it },
                        label = { Text("Bellik (ady, reňki, modeli…)") },
                        placeholder = { Text("Mysal: Nauşnik gara") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = manualQty,
                        onValueChange = { manualQty = it.filter(Char::isDigit) },
                        label = { Text("Sany") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    enabled = !isBusy && manualCode.isNotBlank(),
                    onClick = {
                        val qtyVal = (manualQty.toIntOrNull() ?: 1).coerceAtLeast(1)
                        vm.queueBarcodeQuantityToPc(
                            barcode = manualCode,
                            quantity = qtyVal,
                            modelHint = manualNote,
                            onSuccess = { showManualBarcodeDialog = false },
                        )
                    },
                ) {
                    Text(if (isBusy) "Iberilýär…" else "PK nobatyna iber")
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !isBusy,
                    onClick = { showManualBarcodeDialog = false },
                ) {
                    Text("Ýatyr")
                }
            },
        )
    }

    // Read-only выбор существующего товара из каталога (ТОЛЬКО для режима Sany bilen, БЕЗ «+ Täze»)
    if (showProductPicker) {
        var filter by remember { mutableStateOf("") }
        LaunchedEffect(filter) {
            kotlinx.coroutines.delay(220L)
            vm.loadCatalog(query = filter.trim())
        }
        val filtered = catalog
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
                    IconButton(onClick = { vm.loadCatalog() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Täzele", tint = NavyDark)
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
                    if (filtered.isEmpty()) {
                        Text(
                            text = "Gabat gelýän haryt tapylmady. Täze harytlar PK nobatyndan goşulýar.",
                            fontSize = 12.sp,
                            color = TextMuted,
                        )
                    } else {
                        LazyColumn(
                            modifier = Modifier.height(280.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            items(filtered, key = { it.id }) { prod ->
                                Card(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            vm.updateReceivingMeta(
                                                productId = prod.id,
                                                productName = prod.name,
                                                useImeiMode = false,
                                            )
                                            showProductPicker = false
                                            if (openSheetAfterPicker) {
                                                openSheetAfterPicker = false
                                                showQueueSheet = true
                                            }
                                        },
                                    colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                                    border = BorderStroke(1.dp, BorderColor),
                                ) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Text(prod.name, fontWeight = FontWeight.Bold, color = NavyDark)
                                        val sub = listOf(prod.brand, prod.model, prod.specification)
                                            .filter { it.isNotBlank() }
                                            .joinToString(" • ")
                                        if (sub.isNotBlank()) {
                                            Text(sub, fontSize = 12.sp, color = TextMuted)
                                        }
                                        Text(
                                            text = "Galyndy: ${prod.stockQuantity} sany • SKU: ${prod.sku}",
                                            fontSize = 11.sp,
                                            color = TealAccent,
                                        )
                                    }
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
}

@Composable
private fun ReceivingModeTogglePill(
    label: String,
    subtitle: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val bg = if (selected) AccentOrange else NavyDark.copy(alpha = 0.78f)
    val fg = Color.White
    val subColor = if (selected) Color.White.copy(alpha = 0.9f) else Color.White.copy(alpha = 0.65f)
    Surface(
        color = bg,
        shape = RoundedCornerShape(12.dp),
        border = if (selected) null else BorderStroke(1.dp, Color.White.copy(alpha = 0.22f)),
        modifier = modifier.clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Column {
                Text(label, color = fg, fontSize = 12.5.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(subtitle, color = subColor, fontSize = 10.sp, maxLines = 1)
            }
        }
    }
}

@Composable
private fun ReceivingQueueBottomSheet(
    meta: ReceivingDraftMeta?,
    queueCounts: IncomingQueueCounts,
    sessionEntries: List<SessionQueuedEntry>,
    isBusy: Boolean,
    onModeChanged: (Boolean) -> Unit,
    onPickProduct: () -> Unit,
    onClearProduct: () -> Unit,
    onPersistDefaults: (supplier: String, currency: String) -> Unit,
    onSendQuantityProduct: (qty: Int, cost: String, currency: String, supplier: String, note: String) -> Unit,
    onClearSession: () -> Unit,
) {
    val useImeiMode = meta?.useImeiMode ?: true

    var supplierText by remember(meta?.requestId) { mutableStateOf(meta?.supplierName ?: "") }
    var unitCostText by remember(meta?.requestId) {
        mutableStateOf(
            meta?.unitCost?.takeIf { it.isNotBlank() && it != "0.00" && it != "0" } ?: ""
        )
    }
    var currency by remember(meta?.requestId) { mutableStateOf(meta?.currency ?: "USD") }
    var qtyText by remember(meta?.requestId, meta?.productId) {
        mutableStateOf((meta?.nonImeiQuantity ?: 1).coerceAtLeast(1).toString())
    }
    var noteText by remember(meta?.requestId, meta?.productId) { mutableStateOf("") }

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
        Text("PK kabul ediş nobaty", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = NavyDark)

        // Сводка живой очереди на ПК
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceBg),
            border = BorderStroke(1.dp, BorderColor),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.SpaceAround,
            ) {
                QueueCountStat("Telefon (IMEI)", queueCounts.phoneImei, TealAccent)
                QueueCountStat("Belli", queueCounts.known, GreenSuccess)
                QueueCountStat("Näbelli", queueCounts.unknown, AccentOrange)
                QueueCountStat("Jemi", queueCounts.total, NavyDark)
            }
        }

        // Переключатель режима
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = useImeiMode,
                onClick = { onModeChanged(true) },
                label = { Text("IMEI bilen (Telefon)") },
                colors = chipColors,
            )
            FilterChip(
                selected = !useImeiMode,
                onClick = { onModeChanged(false) },
                label = { Text("Sany bilen (Haryt)") },
                colors = chipColors,
            )
        }

        if (useImeiMode) {
            // В режиме IMEI НЕТ выбора товара и НЕТ «+ Täze»!
            Card(
                colors = CardDefaults.cardColors(containerColor = AccentBg),
                border = BorderStroke(1.dp, AccentOrange.copy(alpha = 0.4f)),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = "Telefon IMEI skan edilende göni PK-däki «Telefonlar (IMEI)» nobatyna düşýär. " +
                        "Haryt ýa-da kategoriýa saýlamak gerek däl.",
                    fontSize = 12.5.sp,
                    color = NavyDark,
                    modifier = Modifier.padding(12.dp),
                )
            }
        } else {
            // В режиме Sany bilen: выбор существующего товара (БЕЗ «+ Täze») + количество + отправка в PK nobaty
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
                        Text("Haryt (katalogdan)", fontSize = 11.sp, color = TextMuted)
                        Text(
                            text = meta?.productName?.ifBlank { "Saýlanmadyk" } ?: "Saýlanmadyk",
                            fontWeight = FontWeight.Bold,
                            color = NavyDark,
                            fontSize = 15.sp,
                        )
                    }
                    if (meta?.productId != null) {
                        IconButton(onClick = onClearProduct) {
                            Icon(Icons.Default.Close, contentDescription = "Arassala", tint = TextMuted)
                        }
                    }
                    TextButton(onClick = onPickProduct) {
                        Text("Saýla", color = AccentOrange, fontWeight = FontWeight.Bold)
                    }
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = qtyText,
                    onValueChange = { qtyText = it.filter(Char::isDigit) },
                    label = { Text("Sany *") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = unitCostText,
                    onValueChange = { unitCostText = it },
                    label = { Text("Alyş bahasy (hökm. däl)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    modifier = Modifier.weight(1.3f),
                )
            }
            OutlinedTextField(
                value = noteText,
                onValueChange = { noteText = it },
                label = { Text("Bellik (hökmany däl)") },
                placeholder = { Text("Mysal: Reňki, tapgyr ýa-da bellik…") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // Общие необязательные поля по умолчанию: Walýuta и Üpjün ediji
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Walýuta:", fontSize = 13.sp, color = TextMuted)
            FilterChip(
                selected = currency == "USD",
                onClick = {
                    currency = "USD"
                    onPersistDefaults(supplierText, "USD")
                },
                label = { Text("USD") },
                colors = chipColors,
            )
            FilterChip(
                selected = currency == "TMT",
                onClick = {
                    currency = "TMT"
                    onPersistDefaults(supplierText, "TMT")
                },
                label = { Text("TMT") },
                colors = chipColors,
            )
        }

        OutlinedTextField(
            value = supplierText,
            onValueChange = {
                supplierText = it
                onPersistDefaults(it, currency)
            },
            label = { Text("Üpjün ediji (hökmany däl)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        if (!useImeiMode) {
            Button(
                onClick = {
                    val qtyVal = qtyText.toIntOrNull() ?: 0
                    onSendQuantityProduct(qtyVal, unitCostText, currency, supplierText, noteText)
                },
                enabled = !isBusy && meta?.productId != null && (qtyText.toIntOrNull() ?: 0) > 0,
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Icon(Icons.Default.Send, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                val qLabel = qtyText.toIntOrNull() ?: 0
                Text(
                    text = if (isBusy) "Iberilýär…" else "PK nobatyna iber ($qLabel sany)",
                    fontWeight = FontWeight.Bold,
                )
            }
        }

        HorizontalDivider(color = BorderColor)

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "Şu sessiýada iberilenler (${sessionEntries.size}):",
                fontWeight = FontWeight.Bold,
                color = NavyDark,
                fontSize = 14.sp,
            )
            if (sessionEntries.isNotEmpty()) {
                TextButton(onClick = onClearSession) {
                    Text("Arassala", color = TextMuted, fontSize = 12.sp)
                }
            }
        }

        if (sessionEntries.isEmpty()) {
            Text(
                text = if (useImeiMode) {
                    "Aýnany ýapyň we telefonyň IMEI etiketkasyny skan ediň — göni PK nobatyna düşer."
                } else {
                    "Aýnany ýapyň we harydyň ştrihkodyny skan ediň ýa-da «Guty OCR» basyň."
                },
                fontSize = 12.sp,
                color = TextMuted,
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(sessionEntries) { item ->
                    val (badgeText, badgeColor) = when (item.itemKind) {
                        "phone_imei" -> "Telefon" to TealAccent
                        "known" -> "Belli" to GreenSuccess
                        else -> "Näbelli" to AccentOrange
                    }
                    Card(
                        colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                        border = BorderStroke(1.dp, BorderColor),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Surface(
                                color = badgeColor.copy(alpha = 0.14f),
                                shape = RoundedCornerShape(6.dp),
                            ) {
                                Text(
                                    text = badgeText,
                                    color = badgeColor,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                                )
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = item.title,
                                    fontWeight = FontWeight.Bold,
                                    color = TextPrimary,
                                    fontSize = 13.sp,
                                    maxLines = 1,
                                )
                                Text(
                                    text = item.detail,
                                    color = TextMuted,
                                    fontSize = 11.5.sp,
                                    maxLines = 2,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun QueueCountStat(label: String, count: Int, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = count.toString(),
            fontSize = 18.sp,
            fontWeight = FontWeight.ExtraBold,
            color = color,
        )
        Text(
            text = label,
            fontSize = 11.sp,
            color = TextMuted,
        )
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
