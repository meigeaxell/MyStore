package com.mobilestore.scanner.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
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
import com.mobilestore.scanner.network.CategoryItem
import com.mobilestore.scanner.network.ProductDetailInfo
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.ui.theme.TextPrimary
import com.mobilestore.scanner.viewmodel.ScannerViewModel

/**
 * Экран 3: Каталог товаров — просмотр, поиск (по названию, SKU, IMEI),
 * просмотр серийных устройств и создание/редактирование карточки товара.
 */
@Composable
fun CatalogScreen(vm: ScannerViewModel) {
    val products by vm.catalogProducts.collectAsState()
    val categories by vm.categories.collectAsState()
    val isLoading by vm.isCatalogLoading.collectAsState()
    val selectedDetails by vm.selectedProductDetails.collectAsState()

    var query by remember { mutableStateOf("") }
    var showCreateDialog by remember { mutableStateOf(false) }
    var editingProduct by remember { mutableStateOf<ProductDetailInfo?>(null) }

    LaunchedEffect(Unit) {
        vm.loadCatalog()
        vm.loadCategories()
    }

    Scaffold(
        containerColor = SurfaceBg,
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showCreateDialog = true },
                containerColor = AccentOrange,
                contentColor = Color.White,
            ) {
                Icon(Icons.Default.Add, contentDescription = "Täze haryt")
            }
        },
    ) { innerPad ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPad)
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = query,
                    onValueChange = {
                        query = it
                        vm.loadCatalog(query = it)
                    },
                    label = { Text("Ady, model, SKU, IMEI bilen gözleg") },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = { vm.loadCatalog(query = query) }) {
                    Icon(Icons.Default.Refresh, contentDescription = "Täzele", tint = NavyDark)
                }
            }

            if (isLoading) {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    color = AccentOrange,
                    trackColor = AccentBg,
                )
            }

            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(products, key = { it.id }) { prod ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { vm.loadProductDetails(prod.id) },
                        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
                        border = BorderStroke(1.dp, BorderColor),
                    ) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(prod.name, fontWeight = FontWeight.Bold, color = NavyDark)
                                Text(
                                    text = "${prod.stockQuantity} sany",
                                    fontWeight = FontWeight.Bold,
                                    color = if (prod.stockQuantity > 0) GreenSuccess else RedDanger,
                                )
                            }
                            val sub = listOf(prod.brand, prod.model, prod.specification)
                                .filter { it.isNotBlank() }
                                .joinToString(" • ")
                            if (sub.isNotBlank()) {
                                Text(sub, fontSize = 12.sp, color = TextMuted)
                            }
                            Text(
                                text = "${prod.category} • SKU: ${prod.sku} • IMEI: ${prod.newDevices} täze / ${prod.usedDevices} B/U",
                                fontSize = 11.sp,
                                color = TextMuted,
                            )
                        }
                    }
                }
            }
        }
    }

    val details = selectedDetails
    if (details != null) {
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { vm.dismissProductDetails() },
            title = {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(details.product.name, color = NavyDark, modifier = Modifier.weight(1f))
                    IconButton(onClick = {
                        editingProduct = details.product
                        vm.dismissProductDetails()
                    }) {
                        Icon(Icons.Default.Edit, contentDescription = "Üýtget", tint = AccentOrange)
                    }
                }
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("SKU: ${details.product.sku}", fontSize = 12.sp, color = TextMuted)
                    Text("Model: ${details.product.brand} ${details.product.model}", color = TextPrimary)
                    if (details.product.specification.isNotBlank()) {
                        Text("Aýratynlyklary: ${details.product.specification}", color = TextPrimary)
                    }
                    Text(
                        "Galyndy: ${details.product.stockQuantity} sany • Öz bahasy: ${details.product.defaultCost} ${details.product.defaultCostCurrency}",
                        fontWeight = FontWeight.SemiBold,
                        color = NavyDark,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text("Ýazylan IMEI-ler (${details.devices.size}):", fontWeight = FontWeight.Bold, color = NavyDark)
                    LazyColumn(modifier = Modifier.height(180.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        items(details.devices, key = { it.id }) { dev ->
                            val statusText = if (dev.status == "in_stock") "Bar" else "Satyldy"
                            Text(
                                text = "${dev.imei1} • $statusText (${dev.unitCost} ${dev.costCurrency})",
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                color = if (dev.status == "in_stock") GreenSuccess else TextMuted,
                            )
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.dismissProductDetails() }) { Text("Ýap") }
            },
        )
    }

    if (showCreateDialog) {
        ProductEditorDialog(
            categories = categories.filter { it.isActive },
            existing = null,
            onDismiss = { showCreateDialog = false },
            onSave = { name, catId, brand, model, mem, color, extra, minStock, cost, costCurr ->
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
                ) { _, _ -> showCreateDialog = false }
            },
        )
    }

    val editProd = editingProduct
    if (editProd != null) {
        ProductEditorDialog(
            categories = categories.filter { it.isActive },
            existing = editProd,
            onDismiss = { editingProduct = null },
            onSave = { name, catId, brand, model, mem, color, extra, minStock, cost, costCurr ->
                vm.saveProduct(
                    productId = editProd.id,
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
                ) { _, _ -> editingProduct = null }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductEditorDialog(
    categories: List<CategoryItem>,
    existing: ProductDetailInfo?,
    onDismiss: () -> Unit,
    onSave: (
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
    ) -> Unit,
) {
    var name by remember { mutableStateOf(existing?.name ?: "") }
    var brand by remember { mutableStateOf(existing?.brand ?: "") }
    var model by remember { mutableStateOf(existing?.model ?: "") }
    var memory by remember { mutableStateOf("") }
    var color by remember { mutableStateOf("") }
    var extraSpecs by remember { mutableStateOf(existing?.specification ?: "") }
    var minStockText by remember { mutableStateOf((existing?.minStockQuantity ?: 2).toString()) }
    var defaultCost by remember {
        mutableStateOf(
            existing?.defaultCost?.takeIf { it.isNotBlank() && it != "0.00" && it != "0" } ?: ""
        )
    }
    var costCurrency by remember { mutableStateOf(existing?.defaultCostCurrency ?: "USD") }
    var selectedCategoryId by remember { mutableStateOf(existing?.categoryId ?: categories.firstOrNull()?.id) }
    var catExpanded by remember { mutableStateOf(false) }

    val selectedCatName = categories.firstOrNull { it.id == selectedCategoryId }?.name ?: "Kategoriýa saýlaň"
    val chipColors = FilterChipDefaults.filterChipColors(
        selectedContainerColor = AccentBg,
        selectedLabelColor = AccentOrange,
    )

    AlertDialog(
        containerColor = SurfaceWhite,
        onDismissRequest = onDismiss,
        title = { Text(if (existing == null) "Täze haryt" else "Harydy üýtgetmek", color = NavyDark) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Ady *") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                ExposedDropdownMenuBox(
                    expanded = catExpanded,
                    onExpandedChange = { catExpanded = !catExpanded },
                ) {
                    OutlinedTextField(
                        value = selectedCatName,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("Kategoriýa") },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = catExpanded) },
                        modifier = Modifier.menuAnchor().fillMaxWidth(),
                    )
                    ExposedDropdownMenu(expanded = catExpanded, onDismissRequest = { catExpanded = false }) {
                        categories.forEach { cat ->
                            DropdownMenuItem(
                                text = { Text(cat.name) },
                                onClick = {
                                    selectedCategoryId = cat.id
                                    catExpanded = false
                                },
                            )
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = brand,
                        onValueChange = { brand = it },
                        label = { Text("Brend") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = model,
                        onValueChange = { model = it },
                        label = { Text("Model") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = memory,
                        onValueChange = { memory = it },
                        label = { Text("Ýat (256GB)") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = color,
                        onValueChange = { color = it },
                        label = { Text("Reňk") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                OutlinedTextField(
                    value = extraSpecs,
                    onValueChange = { extraSpecs = it },
                    label = { Text("Goşmaça maglumat / ştrihkod") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = defaultCost,
                        onValueChange = { defaultCost = it },
                        label = { Text("Öz bahasy") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    FilterChip(
                        selected = costCurrency == "USD",
                        onClick = { costCurrency = "USD" },
                        label = { Text("USD") },
                        colors = chipColors,
                    )
                    FilterChip(
                        selected = costCurrency == "TMT",
                        onClick = { costCurrency = "TMT" },
                        label = { Text("TMT") },
                        colors = chipColors,
                    )
                }
                OutlinedTextField(
                    value = minStockText,
                    onValueChange = { minStockText = it },
                    label = { Text("Min. galyndy (sany)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(
                colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                onClick = {
                    if (name.isNotBlank()) {
                        onSave(
                            name,
                            selectedCategoryId,
                            brand,
                            model,
                            memory,
                            color,
                            extraSpecs,
                            minStockText.toIntOrNull() ?: 2,
                            defaultCost,
                            costCurrency,
                        )
                    }
                },
            ) {
                Text("Ýatda sakla")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Ýatyr") }
        },
    )
}
