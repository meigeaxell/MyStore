package com.mobilestore.scanner.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.NavyDark

private val LedGreen = Color(0xFF22C55E)
private val LedRed = Color(0xFFEF4444)

/**
 * Компактный светящийся LED-индикатор состояния подключения к ПК:
 * - Зелёный с мягким свечением — подключено
 * - Красный с мягким свечением — нет подключения / ошибка
 * - Оранжевый пульсирующий — идёт подключение
 */
@Composable
fun ConnectionGlowDot(
    state: ConnectionState,
    size: Dp = 20.dp,
    modifier: Modifier = Modifier,
) {
    val dotColor = when (state) {
        is ConnectionState.Connected -> LedGreen
        is ConnectionState.Connecting -> AccentOrange
        is ConnectionState.Error, ConnectionState.Disconnected -> LedRed
    }

    val transition = rememberInfiniteTransition(label = "connGlow")
    val glowAlpha by transition.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.85f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = if (state is ConnectionState.Connecting) 600 else 1400),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "glowAlpha",
    )

    Box(modifier = modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.size(size)) {
            val radius = this.size.minDimension / 2f
            // Внешнее мягкое свечение
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        dotColor.copy(alpha = glowAlpha),
                        dotColor.copy(alpha = glowAlpha * 0.35f),
                        Color.Transparent,
                    ),
                    radius = radius,
                ),
                radius = radius,
            )
            // Яркое ядро индикатора
            drawCircle(
                color = dotColor,
                radius = radius * 0.48f,
            )
            // Лёгкий блик в центре
            drawCircle(
                color = Color.White.copy(alpha = 0.55f),
                radius = radius * 0.16f,
            )
        }
    }
}

/**
 * Миниатюрная полупрозрачная пилюля со светящимся индикатором поверх камеры.
 */
@Composable
fun ConnectionGlowPill(
    state: ConnectionState,
    trailingText: String? = null,
    modifier: Modifier = Modifier,
) {
    Surface(
        color = NavyDark.copy(alpha = 0.72f),
        shape = RoundedCornerShape(20.dp),
        modifier = modifier,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ConnectionGlowDot(state = state, size = 18.dp)
            if (!trailingText.isNullOrBlank()) {
                Spacer(Modifier.width(6.dp))
                Text(
                    text = trailingText,
                    color = Color.White,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
            }
        }
    }
}
