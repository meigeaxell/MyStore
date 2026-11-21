package com.mobilestore.scanner.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Точная цветовая палитра настольного приложения MobileStore (app/ui/theme.py)
val AccentOrange = Color(0xFFF58A2E)       // ACCENT
val AccentOrangeHover = Color(0xFFE57C20)  // primaryBtn:hover
val AccentSoft = Color(0xFFFFE6CC)         // ACCENT_SOFT
val AccentBg = Color(0xFFFFF3E6)           // ACCENT_BG
val NavyDark = Color(0xFF1B2A41)           // NAVY
val TealAccent = Color(0xFF1E9E86)         // TEAL
val BlueAccent = Color(0xFF2F6BFF)         // BLUE
val GreenSuccess = Color(0xFF16A34A)       // GREEN
val RedDanger = Color(0xFFE5484D)          // RED
val TextPrimary = Color(0xFF1D2939)        // TEXT
val TextMuted = Color(0xFF667085)          // MUTED
val BorderColor = Color(0xFFE8EBF0)        // BORDER
val SurfaceBg = Color(0xFFF6F7F9)          // BG
val SurfaceWhite = Color(0xFFFFFFFF)       // WHITE
val SurfaceSubtle = Color(0xFFF2F4F7)      // disabled / subtle fill

private val MobileStoreColorScheme = lightColorScheme(
    primary = AccentOrange,
    onPrimary = SurfaceWhite,
    primaryContainer = AccentBg,
    onPrimaryContainer = AccentOrange,
    secondary = NavyDark,
    onSecondary = SurfaceWhite,
    secondaryContainer = SurfaceSubtle,
    onSecondaryContainer = NavyDark,
    tertiary = TealAccent,
    onTertiary = SurfaceWhite,
    background = SurfaceBg,
    onBackground = TextPrimary,
    surface = SurfaceWhite,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceBg,
    onSurfaceVariant = TextMuted,
    outline = BorderColor,
    outlineVariant = BorderColor,
    error = RedDanger,
    onError = SurfaceWhite,
)

@Composable
fun MobileStoreTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = MobileStoreColorScheme,
        content = content,
    )
}
