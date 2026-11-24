package com.mobilestore.scanner

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoveToInbox
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilestore.scanner.ui.ReceivingScreen
import com.mobilestore.scanner.ui.SaleScanScreen
import com.mobilestore.scanner.ui.SettingsScreen
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.MobileStoreTheme
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceBg
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.viewmodel.BannerMessage
import com.mobilestore.scanner.viewmodel.ScannerViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MobileStoreTheme {
                MobileStoreScannerRoot()
            }
        }
    }
}

private data class NavTab(val label: String, val icon: ImageVector)

@Composable
private fun MobileStoreScannerRoot(vm: ScannerViewModel = viewModel()) {
    val context = LocalContext.current
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasCameraPermission = granted
    }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    val tabs = remember {
        listOf(
            NavTab("Skaner", Icons.Default.QrCodeScanner),
            NavTab("Kabul ediş", Icons.Default.MoveToInbox),
            NavTab("Sazlama", Icons.Default.Settings),
        )
    }
    var selectedTab by remember { mutableIntStateOf(0) }

    val banner by vm.banner.collectAsState()
    var lastShownBanner by remember { mutableStateOf<BannerMessage?>(null) }
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(banner) {
        val current = banner ?: return@LaunchedEffect
        lastShownBanner = current
        snackbarHostState.showSnackbar(
            message = current.text,
            duration = SnackbarDuration.Short,
        )
        vm.clearBanner()
    }

    Scaffold(
        containerColor = SurfaceBg,
        snackbarHost = {
            SnackbarHost(hostState = snackbarHostState) { data ->
                val tone = banner ?: lastShownBanner
                val bgColor = when {
                    tone?.isError == true -> RedDanger
                    tone?.isWarning == true -> AccentOrange
                    else -> GreenSuccess
                }
                Snackbar(
                    snackbarData = data,
                    containerColor = bgColor,
                    contentColor = Color.White,
                )
            }
        },
        bottomBar = {
            NavigationBar(
                containerColor = SurfaceWhite,
                contentColor = AccentOrange,
            ) {
                tabs.forEachIndexed { idx, tab ->
                    NavigationBarItem(
                        selected = selectedTab == idx,
                        onClick = { selectedTab = idx },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = AccentOrange,
                            selectedTextColor = AccentOrange,
                            indicatorColor = AccentBg,
                            unselectedIconColor = TextMuted,
                            unselectedTextColor = TextMuted,
                        ),
                    )
                }
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when (selectedTab) {
                0 -> SaleScanScreen(
                    vm = vm,
                    hasCameraPermission = hasCameraPermission,
                    onRequestCameraPermission = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                )
                1 -> ReceivingScreen(
                    vm = vm,
                    hasCameraPermission = hasCameraPermission,
                    onRequestCameraPermission = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                )
                2 -> SettingsScreen(vm = vm)
            }
        }
    }
}
