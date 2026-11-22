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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.network.ProductCardData
import com.mobilestore.scanner.scanner.CameraPreviewView
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
 * Экран 1: Сканирование / Продажи.
 * - Постоянная камера без кнопки «Сканировать»
 * - Мульти-скан всей наклейки коробки (IMEI 1 + IMEI 2 + S/N + штрихкод)
 * - Нечёткое совпадение по большинству цифр с обязательным подтверждением пользователя
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SaleScanScreen(
    vm: ScannerViewModel,
    hasCameraPermission: Boolean,
    onRequestCameraPermission: () -> Unit,
) {
    val connState by vm.connectionState.collectAsState()
    val config by vm.serverConfig.collectAsState()
    val activeCard by vm.activeProductCard.collectAsState()
    val scanSource by vm.activeScanSource.collectAsState()
    val multiMatches by vm.multipleMatches.collectAsState()
    val saleOcrResult by vm.saleOcrResult.collectAsState()
    val saleOcrCatFilter by vm.saleOcrCategoryFilter.collectAsState()
    val isBusy by vm.isSaleRequestInFlight.collectAsState()
    val cooldownTrigger by vm.scanCooldownTrigger.collectAsState()

    var ocrEnabled by remember { mutableStateOf(true) }
    var showManualDialog by remember { mutableStateOf(false) }
    var boxCaptureTrigger by remember { mutableIntStateOf(0) }

    val isPaused = activeCard != null || multiMatches.isNotEmpty() || saleOcrResult != null || isBusy || showManualDialog

    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        if (hasCameraPermission) {
            CameraPreviewView(
                isPaused = isPaused,
                enableOcr = ocrEnabled,
                burstWindowMs = 550L,
                cooldownMs = config.scanCooldownMs,
                cooldownTriggerKey = cooldownTrigger,
                boxCaptureTriggerKey = boxCaptureTrigger,
                onDetected = { bundle -> vm.onSaleBundleDetected(bundle) },
                onBoxTextCaptured = { rawText -> vm.matchAccessoryForSale(rawText) },
                onCameraStatusChanged = { vm.updateCameraStatus(it) },
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(
                modifier = Modifier.fillMaxSize().padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Ştrihkod we IMEI skan etmek üçin kamera rugsaty gerek",
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

        // Компактный светящийся индикатор подключения (зелёный / красный) в верхнем углу
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp)
                .align(Alignment.TopCenter),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ConnectionGlowPill(state = connState)
            Surface(
                color = NavyDark.copy(alpha = 0.72f),
                shape = RoundedCornerShape(16.dp),
            ) {
                Text(
                    text = "Satyş",
                    color = AccentOrange,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                )
            }
        }

        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 14.dp, end = 84.dp, bottom = 14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = { boxCaptureTrigger += 1 },
                enabled = !isBusy && hasCameraPermission,
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.height(44.dp),
            ) {
                Icon(Icons.Default.DocumentScanner, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text("Aksessuar OCR (guty)", fontWeight = FontWeight.Bold)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = ocrEnabled,
                    onClick = { ocrEnabled = !ocrEnabled },
                    label = { Text("OCR IMEI") },
                    colors = FilterChipDefaults.filterChipColors(
                        containerColor = NavyDark.copy(alpha = 0.80f),
                        labelColor = Color.White,
                        selectedContainerColor = AccentOrange,
                        selectedLabelColor = Color.White,
                    ),
                )
                OutlinedButton(
                    onClick = { showManualDialog = true },
                    border = BorderStroke(1.dp, BorderColor.copy(alpha = 0.5f)),
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = NavyDark.copy(alpha = 0.82f),
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Keyboard, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Kod ýaz")
                }
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

    val ocrRes = saleOcrResult
    if (ocrRes != null) {
        ModalBottomSheet(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) vm.dismissSaleOcr() },
        ) {
            AccessoryOcrResultSheet(
                result = ocrRes,
                isBusy = isBusy,
                selectedCategoryId = saleOcrCatFilter,
                showCreateNewButton = false,
                onRequery = { editedText, catId -> vm.matchAccessoryForSale(editedText, catId) },
                onSelectProduct = { chosen -> vm.selectAccessoryForSale(chosen) },
                onDismiss = { vm.dismissSaleOcr() },
            )
        }
    }

    val card = activeCard
    if (card != null) {
        ModalBottomSheet(
            containerColor = SurfaceWhite,
            onDismissRequest = { if (!isBusy) vm.cancelSaleCard() },
        ) {
            SaleProductCardSheet(
                card = card,
                scanSource = scanSource,
                isSubmitting = isBusy,
                onConfirm = { price, currency, qty ->
                    vm.confirmAddToSale(card, price, currency, qty)
                },
                onCancel = { vm.cancelSaleCard() },
            )
        }
    }

    if (multiMatches.isNotEmpty()) {
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { vm.dismissMultipleMatches() },
            title = { Text("Takyk harydy saýlaň", color = NavyDark) },
            text = {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(multiMatches) { item ->
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { vm.selectFromMultipleMatches(item) },
                            colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                            border = BorderStroke(1.dp, BorderColor),
                        ) {
                            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text(item.name, fontWeight = FontWeight.Bold, color = NavyDark)
                                val details = listOf(item.brand, item.model, item.specification)
                                    .filter { it.isNotBlank() }
                                    .joinToString(" • ")
                                if (details.isNotBlank()) {
                                    Text(details, fontSize = 12.sp, color = TextMuted)
                                }
                                if (!item.imei.isNullOrBlank()) {
                                    Text(
                                        "IMEI: ${item.imei}",
                                        fontFamily = FontFamily.Monospace,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = TextPrimary,
                                    )
                                }
                                if (item.matchDetail.isNotBlank()) {
                                    Text(
                                        item.matchDetail,
                                        fontSize = 11.sp,
                                        color = AccentOrange,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                } else {
                                    Text(
                                        "Galyndy: ${item.stockQuantity} sany • SKU: ${item.sku}",
                                        fontSize = 12.sp,
                                        color = AccentOrange,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.dismissMultipleMatches() }) {
                    Text("Ýatyr")
                }
            },
        )
    }

    if (showManualDialog) {
        var manualText by remember { mutableStateOf("") }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { showManualDialog = false },
            title = { Text("IMEI / SKU / kod bilen gözleg", color = NavyDark) },
            text = {
                OutlinedTextField(
                    value = manualText,
                    onValueChange = { manualText = it },
                    label = { Text("IMEI, S/N, SKU ýa-da ady") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    onClick = {
                        showManualDialog = false
                        vm.manualLookupForSale(manualText)
                    },
                ) {
                    Text("Tap")
                }
            },
            dismissButton = {
                TextButton(onClick = { showManualDialog = false }) {
                    Text("Ýatyr")
                }
            },
        )
    }
}

@Composable
private fun SaleProductCardSheet(
    card: ProductCardData,
    scanSource: String,
    isSubmitting: Boolean,
    onConfirm: (price: String, currency: String, quantity: Int) -> Unit,
    onCancel: () -> Unit,
) {
    var priceText by remember(card.productId, card.imei) {
        mutableStateOf(
            card.lastSalePrice?.takeIf { it.isNotBlank() && it != "0.00" && it != "0" } ?: ""
        )
    }
    var selectedCurrency by remember(card.productId, card.imei) {
        mutableStateOf(
            card.lastSaleCurrency?.takeIf { it == "USD" || it == "TMT" }
                ?: card.defaultCurrency.ifBlank { "TMT" }
        )
    }
    var quantity by remember(card.productId, card.imei) { mutableIntStateOf(1) }

    val needsFuzzyVerify = card.requiresConfirmation || card.matchType == "fuzzy"
    var userConfirmedMatch by remember(card.productId, card.imei, card.scannedCode) {
        mutableStateOf(!needsFuzzyVerify)
    }

    val canSell = card.availabilityStatus == "available"
    val statusColor = when (card.availabilityStatus) {
        "available" -> GreenSuccess
        "in_cart" -> AccentOrange
        else -> RedDanger
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp)
            .padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                color = statusColor.copy(alpha = 0.14f),
                shape = RoundedCornerShape(8.dp),
            ) {
                Text(
                    text = card.availabilityMessage.ifBlank { card.availabilityStatus },
                    color = statusColor,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
            Text(
                text = when (scanSource) {
                    "multi" -> "Multi-skan"
                    "ocr" -> "OCR"
                    "qr" -> "QR-kod"
                    "manual" -> "El bilen"
                    else -> "Ştrihkod"
                },
                color = TextMuted,
                fontSize = 12.sp,
            )
        }

        // Блок обязательной проверки при неточном совпадении (по большинству цифр)
        if (needsFuzzyVerify) {
            Card(
                colors = CardDefaults.cardColors(containerColor = AccentBg),
                border = BorderStroke(1.5.dp, AccentOrange),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Warning, contentDescription = null, tint = AccentOrange)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = "Doly gabat gelmedi — harydy barlaň!",
                            fontWeight = FontWeight.Bold,
                            color = NavyDark,
                            fontSize = 14.sp,
                        )
                    }
                    if (card.matchDetail.isNotBlank()) {
                        Text(
                            text = "${card.matchDetail} (${card.matchScore}%)",
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = AccentOrange,
                        )
                    }
                    val scanned = card.scannedCode.orEmpty()
                    val matched = card.matchedCode.orEmpty()
                    if (scanned.isNotBlank() && matched.isNotBlank()) {
                        Text(
                            text = buildHighlightedDiff("Okaldy: ", scanned, matched),
                            fontFamily = FontFamily.Monospace,
                            fontSize = 13.sp,
                        )
                        Text(
                            text = buildHighlightedDiff("Bazada: ", matched, scanned),
                            fontFamily = FontFamily.Monospace,
                            fontSize = 13.sp,
                        )
                    }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { userConfirmedMatch = !userConfirmedMatch },
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = userConfirmedMatch,
                            onCheckedChange = { userConfirmedMatch = it },
                            colors = CheckboxDefaults.colors(checkedColor = AccentOrange),
                        )
                        Text(
                            text = "Hawa, takyk şu haryt (gutydan barladym)",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            color = NavyDark,
                        )
                    }
                }
            }
        }

        Text(
            text = card.name,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
            color = NavyDark,
        )

        val subtitle = listOf(card.brand, card.model, card.specification)
            .filter { it.isNotBlank() }
            .joinToString(" • ")
        if (subtitle.isNotBlank()) {
            Text(subtitle, fontSize = 14.sp, color = TextMuted)
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceBg),
            border = BorderStroke(1.dp, BorderColor),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (!card.imei.isNullOrBlank()) {
                    Text(
                        text = "IMEI 1: ${card.imei}",
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp,
                        color = TextPrimary,
                    )
                }
                if (!card.imei2.isNullOrBlank()) {
                    Text(
                        text = "IMEI 2: ${card.imei2}",
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                        color = TextMuted,
                    )
                }
                if (!card.serialNumber.isNullOrBlank()) {
                    Text(
                        text = "S/N:    ${card.serialNumber}",
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                        color = TextMuted,
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("Kategoriýa: ${card.categoryName}", fontSize = 13.sp, color = TextMuted)
                    Text(
                        "Galyndy: ${card.stockQuantity} sany",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = TextPrimary,
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = "Öz bahasy: ${card.unitCost} ${card.costCurrency}",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = TealAccent,
                    )
                    Text(
                        text = "Kurs: ${card.exchangeRate}",
                        fontSize = 12.sp,
                        color = TextMuted,
                    )
                }
            }
        }

        HorizontalDivider(color = BorderColor)

        if (canSell) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = priceText,
                    onValueChange = { priceText = it },
                    label = { Text("Satyş bahasy ($selectedCurrency)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    FilterChip(
                        selected = selectedCurrency == "TMT",
                        onClick = { selectedCurrency = "TMT" },
                        label = { Text("TMT") },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = AccentBg,
                            selectedLabelColor = AccentOrange,
                        ),
                    )
                    FilterChip(
                        selected = selectedCurrency == "USD",
                        onClick = { selectedCurrency = "USD" },
                        label = { Text("USD") },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = AccentBg,
                            selectedLabelColor = AccentOrange,
                        ),
                    )
                }
            }

            if (card.imei.isNullOrBlank() && card.stockQuantity > 1) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("Sany:", fontWeight = FontWeight.Medium, color = TextPrimary)
                    OutlinedButton(
                        onClick = { if (quantity > 1) quantity -= 1 },
                        enabled = quantity > 1,
                    ) { Text("−") }
                    Text("$quantity sany", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = NavyDark)
                    OutlinedButton(
                        onClick = { if (quantity < card.stockQuantity) quantity += 1 },
                        enabled = quantity < card.stockQuantity,
                    ) { Text("+") }
                }
            }
        }

        Spacer(Modifier.height(4.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedButton(
                onClick = onCancel,
                enabled = !isSubmitting,
                border = BorderStroke(1.dp, BorderColor),
                modifier = Modifier.weight(1f).height(50.dp),
            ) {
                Icon(Icons.Default.Close, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text("Ýatyr")
            }

            Button(
                onClick = { onConfirm(priceText, selectedCurrency, quantity) },
                enabled = canSell && !isSubmitting && userConfirmedMatch,
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                modifier = Modifier.weight(1.4f).height(50.dp),
            ) {
                Icon(Icons.Default.Check, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(if (isSubmitting) "Iberilýär…" else "Bolýar • Satyşa")
            }
        }
    }
}

private fun buildHighlightedDiff(prefix: String, primary: String, reference: String) = buildAnnotatedString {
    withStyle(SpanStyle(color = TextMuted)) { append(prefix) }
    for (i in primary.indices) {
        val ch = primary[i]
        val differs = i >= reference.length || reference[i] != ch
        if (differs) {
            withStyle(SpanStyle(color = RedDanger, fontWeight = FontWeight.ExtraBold)) {
                append(ch)
            }
        } else {
            withStyle(SpanStyle(color = TextPrimary, fontWeight = FontWeight.SemiBold)) {
                append(ch)
            }
        }
    }
}
