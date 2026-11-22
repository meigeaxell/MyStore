package com.mobilestore.scanner.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.network.AccessoryDraftSuggestion
import com.mobilestore.scanner.network.AccessoryOcrMatchResponse
import com.mobilestore.scanner.network.ProductCardData
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.TealAccent
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.ui.theme.TextPrimary

/**
 * Общий лист результатов OCR-распознавания коробки аксессуара.
 * Используется и в Продажах (выбор товара для отправки в кассу),
 * и в Приёмке (выбор существующего товара или быстрое создание нового из OCR-черновика).
 */
@Composable
fun AccessoryOcrResultSheet(
    result: AccessoryOcrMatchResponse,
    isBusy: Boolean,
    selectedCategoryId: Int?,
    showCreateNewButton: Boolean,
    onRequery: (editedText: String, categoryId: Int?) -> Unit,
    onSelectProduct: (ProductCardData) -> Unit,
    onCreateNewFromDraft: ((AccessoryDraftSuggestion, String) -> Unit)? = null,
    onDismiss: () -> Unit,
) {
    var queryText by remember(result.rawText) {
        mutableStateOf(result.parsed.cleanedQuery.ifBlank { result.rawText.replace("\n", " ").trim() })
    }

    val chipColors = FilterChipDefaults.filterChipColors(
        selectedContainerColor = AccentBg,
        selectedLabelColor = AccentOrange,
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp)
            .padding(bottom = 26.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "Guty OCR netijesi",
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
                color = NavyDark,
            )
            TextButton(onClick = onDismiss) {
                Text("Ýap", color = TextMuted)
            }
        }

        // Редактируемое поле распознанного текста — если OCR ошибся в 1 цифре (15/16), правится за секунду
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = queryText,
                onValueChange = { queryText = it },
                label = { Text("Okalan tekst (düzedip bolýar)") },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Button(
                onClick = { onRequery(queryText, selectedCategoryId) },
                enabled = !isBusy && queryText.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.height(52.dp),
            ) {
                if (isBusy) {
                    CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Default.Search, contentDescription = "Gözle")
                }
            }
        }

        // Распознанные сигналы с коробки (Тип / Бренд / Модель / Фичи)
        val badges = buildList {
            if (result.parsed.accessoryTypeLabel.isNotBlank()) add(result.parsed.accessoryTypeLabel to TealAccent)
            if (result.parsed.brand.isNotBlank()) add(result.parsed.brand to NavyDark)
            if (result.parsed.model.isNotBlank()) add(result.parsed.model to AccentOrange)
            result.parsed.features.take(2).forEach { add(it to TextPrimary) }
        }
        if (badges.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                badges.forEach { (label, color) ->
                    Surface(
                        color = color.copy(alpha = 0.12f),
                        shape = RoundedCornerShape(8.dp),
                    ) {
                        Text(
                            text = label,
                            color = color,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                        )
                    }
                }
            }
        }

        // Фильтры по категориям (удобно, если на коробке только модель телефона без типа аксессуара)
        if (result.categories.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                FilterChip(
                    selected = selectedCategoryId == null,
                    onClick = { onRequery(queryText, null) },
                    label = { Text("Ählisi", fontSize = 12.sp) },
                    colors = chipColors,
                )
                result.categories.forEach { cat ->
                    FilterChip(
                        selected = selectedCategoryId == cat.id,
                        onClick = { onRequery(queryText, cat.id) },
                        label = { Text(cat.name, fontSize = 12.sp) },
                        colors = chipColors,
                    )
                }
            }
        }

        HorizontalDivider(color = BorderColor)

        if (result.items.isEmpty()) {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                border = BorderStroke(1.dp, BorderColor),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = "Bazada gabat gelýän haryt tapylmady",
                        fontWeight = FontWeight.Bold,
                        color = NavyDark,
                        fontSize = 14.sp,
                    )
                    Text(
                        text = "Ýokardaky teksti düzedip täzeden gözläň ýa-da täze haryt dörediň.",
                        fontSize = 12.sp,
                        color = TextMuted,
                    )
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 310.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(result.items, key = { it.productId }) { item ->
                    val inStock = item.stockQuantity > 0
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelectProduct(item) },
                        colors = CardDefaults.cardColors(containerColor = SurfaceBg),
                        border = BorderStroke(1.dp, if (inStock) BorderColor else RedDanger.copy(alpha = 0.4f)),
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = item.name,
                                    fontWeight = FontWeight.Bold,
                                    color = NavyDark,
                                    fontSize = 14.sp,
                                    modifier = Modifier.weight(1f),
                                )
                                Spacer(Modifier.width(8.dp))
                                Surface(
                                    color = AccentOrange.copy(alpha = 0.14f),
                                    shape = RoundedCornerShape(6.dp),
                                ) {
                                    Text(
                                        text = "${item.matchScore}%",
                                        color = AccentOrange,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                                    )
                                }
                            }

                            val meta = listOf(item.categoryName, item.brand, item.model)
                                .filter { it.isNotBlank() }
                                .joinToString(" • ")
                            if (meta.isNotBlank()) {
                                Text(meta, fontSize = 12.sp, color = TextMuted)
                            }

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    text = "Galyndy: ${item.stockQuantity} sany",
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = if (inStock) GreenSuccess else RedDanger,
                                )
                                val priceInfo = buildList {
                                    if (item.unitCost != "0.00") add("Öz: ${item.unitCost} ${item.costCurrency}")
                                    if (!item.lastSalePrice.isNullOrBlank()) {
                                        add("Öňki: ${item.lastSalePrice} ${item.lastSaleCurrency ?: item.defaultCurrency}")
                                    }
                                }.joinToString("  |  ")
                                if (priceInfo.isNotBlank()) {
                                    Text(
                                        text = priceInfo,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = TextPrimary,
                                    )
                                }
                            }

                            if (item.matchDetail.isNotBlank()) {
                                Text(
                                    text = item.matchDetail,
                                    fontSize = 11.sp,
                                    color = TealAccent,
                                )
                            }
                        }
                    }
                }
            }
        }

        if (showCreateNewButton && onCreateNewFromDraft != null) {
            OutlinedButton(
                onClick = { onCreateNewFromDraft(result.draftSuggestion, result.rawText.ifBlank { queryText }) },
                border = BorderStroke(1.5.dp, AccentOrange),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = AccentOrange),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
            ) {
                Icon(Icons.Default.Add, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(
                    text = "Täze haryt döret (OCR-dan doldur)",
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}
