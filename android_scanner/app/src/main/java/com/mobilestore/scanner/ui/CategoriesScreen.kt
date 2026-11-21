package com.mobilestore.scanner.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.network.CategoryItem
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.SurfaceSubtle
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.viewmodel.ScannerViewModel

/**
 * Экран 4: Категории товаров — просмотр, создание, переименование
 * и безопасная мягкая деактивация с предупреждением о привязанных товарах.
 */
@Composable
fun CategoriesScreen(vm: ScannerViewModel) {
    val categories by vm.categories.collectAsState()
    val isLoading by vm.isCategoriesLoading.collectAsState()

    var showCreateDialog by remember { mutableStateOf(false) }
    var renameTarget by remember { mutableStateOf<CategoryItem?>(null) }
    var deactivateTarget by remember { mutableStateOf<CategoryItem?>(null) }

    LaunchedEffect(Unit) {
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
                Icon(Icons.Default.Add, contentDescription = "Täze kategoriýa")
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
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Haryt kategoriýalary", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = NavyDark)
                IconButton(onClick = { vm.loadCategories() }) {
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
                items(categories, key = { it.id }) { cat ->
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = if (cat.isActive) SurfaceWhite else SurfaceSubtle,
                        ),
                        border = BorderStroke(1.dp, BorderColor),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 14.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = cat.name,
                                    fontWeight = FontWeight.Bold,
                                    color = if (cat.isActive) NavyDark else TextMuted,
                                )
                                Text(
                                    text = "Harytlar: ${cat.productCount} • ${if (cat.isActive) "Işjeň" else "Öçürilen"}",
                                    fontSize = 12.sp,
                                    color = TextMuted,
                                )
                            }
                            IconButton(onClick = { renameTarget = cat }) {
                                Icon(Icons.Default.Edit, contentDescription = "Adyny üýtget", tint = NavyDark)
                            }
                            if (cat.isActive) {
                                IconButton(onClick = { deactivateTarget = cat }) {
                                    Icon(Icons.Default.Block, contentDescription = "Öçür", tint = RedDanger)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showCreateDialog) {
        var newName by remember { mutableStateOf("") }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { showCreateDialog = false },
            title = { Text("Täze kategoriýa", color = NavyDark) },
            text = {
                OutlinedTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    label = { Text("Kategoriýanyň ady") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    onClick = {
                        if (newName.isNotBlank()) {
                            vm.createCategory(newName) { showCreateDialog = false }
                        }
                    },
                ) { Text("Döret") }
            },
            dismissButton = {
                TextButton(onClick = { showCreateDialog = false }) { Text("Ýatyr") }
            },
        )
    }

    val renameCat = renameTarget
    if (renameCat != null) {
        var editedName by remember(renameCat.id) { mutableStateOf(renameCat.name) }
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { renameTarget = null },
            title = { Text("Kategoriýanyň adyny üýtget", color = NavyDark) },
            text = {
                OutlinedTextField(
                    value = editedName,
                    onValueChange = { editedName = it },
                    label = { Text("Täze ady") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = {
                Button(
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    onClick = {
                        if (editedName.isNotBlank()) {
                            vm.renameCategory(renameCat.id, editedName) { renameTarget = null }
                        }
                    },
                ) { Text("Ýatda sakla") }
            },
            dismissButton = {
                TextButton(onClick = { renameTarget = null }) { Text("Ýatyr") }
            },
        )
    }

    val deactCat = deactivateTarget
    if (deactCat != null) {
        AlertDialog(
            containerColor = SurfaceWhite,
            onDismissRequest = { deactivateTarget = null },
            title = { Text("Kategoriýany öçürmelimi?", color = NavyDark) },
            text = {
                val warn = if (deactCat.productCount > 0) {
                    "Üns beriň: «${deactCat.name}» kategoriýasyna ${deactCat.productCount} işjeň haryt berkidilen. " +
                        "Harytlar we satyş taryhy pozulmaz, diňe kategoriýa täze sanawdan gizlener."
                } else {
                    "«${deactCat.name}» kategoriýasyny öçürmelimi? Öňki maglumatlar saklanar."
                }
                Text(warn, color = TextMuted)
            },
            confirmButton = {
                Button(
                    onClick = {
                        vm.deactivateCategory(deactCat.id, force = deactCat.productCount > 0)
                        deactivateTarget = null
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = RedDanger),
                ) { Text("Öçür") }
            },
            dismissButton = {
                TextButton(onClick = { deactivateTarget = null }) { Text("Ýatyr") }
            },
        )
    }
}
