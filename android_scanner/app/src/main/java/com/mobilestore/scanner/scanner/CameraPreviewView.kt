package com.mobilestore.scanner.scanner

import android.view.ViewGroup
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FlashOff
import androidx.compose.material.icons.filled.FlashOn
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.TealAccent
import kotlinx.coroutines.delay
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@Composable
fun CameraPreviewView(
    isPaused: Boolean,
    enableOcr: Boolean,
    burstWindowMs: Long = 650L,
    cooldownMs: Long = 2_500L,
    cooldownTriggerKey: Int = 0,
    boxCaptureTriggerKey: Int = 0,
    onDetected: (ScanBundle) -> Unit,
    onBoxTextCaptured: ((String) -> Unit)? = null,
    onCameraStatusChanged: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentPaused by rememberUpdatedState(isPaused)
    val currentOcr by rememberUpdatedState(enableOcr)
    val currentCooldownMs by rememberUpdatedState(cooldownMs)
    val currentOnDetected by rememberUpdatedState(onDetected)
    val currentOnBoxTextCaptured by rememberUpdatedState(onBoxTextCaptured)

    var torchEnabled by remember { mutableStateOf(false) }
    var boundCamera by remember { mutableStateOf<Camera?>(null) }
    var previewViewRef by remember { mutableStateOf<PreviewView?>(null) }
    var previewSize by remember { mutableStateOf(IntSize.Zero) }
    var cooldownUntilMs by remember { mutableLongStateOf(0L) }
    var remainingMs by remember { mutableLongStateOf(0L) }
    var burstLabel by remember { mutableStateOf<String?>(null) }
    var focusRingPoint by remember { mutableStateOf<Offset?>(null) }

    val currentPreviewSize by rememberUpdatedState(previewSize)

    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    val analyzer = remember {
        BarcodeAndOcrAnalyzer(
            isPaused = { currentPaused },
            enableOcr = { currentOcr },
            previewSizeProvider = { currentPreviewSize.width to currentPreviewSize.height },
            boxWidthFraction = BarcodeAndOcrAnalyzer.SCAN_BOX_WIDTH_FRACTION,
            boxHeightFraction = BarcodeAndOcrAnalyzer.SCAN_BOX_HEIGHT_FRACTION,
            burstWindowMs = burstWindowMs,
            cooldownMsProvider = { currentCooldownMs },
            onCooldownStarted = { until ->
                ContextCompat.getMainExecutor(context).execute {
                    cooldownUntilMs = until
                    burstLabel = null
                }
            },
            onBurstProgress = { label ->
                ContextCompat.getMainExecutor(context).execute {
                    burstLabel = label
                }
            },
            onDetected = { bundle ->
                ContextCompat.getMainExecutor(context).execute {
                    currentOnDetected(bundle)
                }
            },
            onBoxTextCaptured = { rawText ->
                ContextCompat.getMainExecutor(context).execute {
                    currentOnBoxTextCaptured?.invoke(rawText)
                }
            },
        )
    }

    LaunchedEffect(cooldownTriggerKey) {
        if (cooldownTriggerKey > 0) {
            analyzer.triggerCooldown(currentCooldownMs)
        }
    }

    LaunchedEffect(boxCaptureTriggerKey) {
        if (boxCaptureTriggerKey > 0) {
            analyzer.requestBoxTextCapture(frames = 2)
        }
    }

    LaunchedEffect(focusRingPoint) {
        if (focusRingPoint != null) {
            delay(750L)
            focusRingPoint = null
        }
    }

    LaunchedEffect(cooldownUntilMs) {
        while (true) {
            val left = cooldownUntilMs - System.currentTimeMillis()
            if (left <= 0L) {
                remainingMs = 0L
                break
            }
            remainingMs = left
            delay(100L)
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            analyzer.release()
            analysisExecutor.shutdown()
        }
    }

    val isInCooldown = remainingMs > 0L

    Box(
        modifier = modifier
            .onSizeChanged { previewSize = it }
            .pointerInput(Unit) {
                detectTapGestures { offset ->
                    val cam = boundCamera ?: return@detectTapGestures
                    val pv = previewViewRef ?: return@detectTapGestures
                    focusRingPoint = offset
                    val factory = pv.meteringPointFactory
                    val point = factory.createPoint(offset.x, offset.y)
                    val action = FocusMeteringAction.Builder(
                        point,
                        FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE,
                    )
                        .setAutoCancelDuration(3, TimeUnit.SECONDS)
                        .build()
                    runCatching { cam.cameraControl.startFocusAndMetering(action) }
                }
            },
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                val previewView = PreviewView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    scaleType = PreviewView.ScaleType.FILL_CENTER
                }
                previewViewRef = previewView

                val providerFuture = ProcessCameraProvider.getInstance(ctx)
                providerFuture.addListener({
                    try {
                        val cameraProvider = providerFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.surfaceProvider = previewView.surfaceProvider
                        }
                        val analysis = ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build()
                            .also {
                                it.setAnalyzer(analysisExecutor, analyzer)
                            }

                        cameraProvider.unbindAll()
                        val cam = cameraProvider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            analysis,
                        )
                        boundCamera = cam

                        // Автофокус по центру зелёной рамки при запуске
                        previewView.post {
                            if (previewView.width > 0 && previewView.height > 0) {
                                val pt = previewView.meteringPointFactory.createPoint(
                                    previewView.width / 2f,
                                    previewView.height / 2f,
                                )
                                val focusAction = FocusMeteringAction.Builder(
                                    pt,
                                    FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE,
                                )
                                    .setAutoCancelDuration(4, TimeUnit.SECONDS)
                                    .build()
                                runCatching { cam.cameraControl.startFocusAndMetering(focusAction) }
                            }
                        }
                        onCameraStatusChanged("Işjeň")
                    } catch (e: Exception) {
                        onCameraStatusChanged("Ýalňyşlyk: ${e.message}")
                    }
                }, ContextCompat.getMainExecutor(ctx))

                previewView
            },
        )

        // Полупрозрачная маска за пределами зелёной рамки + точное окно сканирования
        val frameColor = when {
            isPaused || isInCooldown -> AccentOrange
            burstLabel != null -> TealAccent
            else -> GreenSuccess
        }
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen),
        ) {
            val boxW = size.width * BarcodeAndOcrAnalyzer.SCAN_BOX_WIDTH_FRACTION
            val boxH = size.height * BarcodeAndOcrAnalyzer.SCAN_BOX_HEIGHT_FRACTION
            val left = (size.width - boxW) / 2f
            val top = (size.height - boxH) / 2f
            val radius = CornerRadius(24f, 24f)

            // Затемнение снаружи рамки, чтобы пользователь видел точную активную зону
            drawRect(color = Color.Black.copy(alpha = 0.48f))
            drawRoundRect(
                color = Color.Transparent,
                topLeft = Offset(left, top),
                size = Size(boxW, boxH),
                cornerRadius = radius,
                blendMode = BlendMode.Clear,
            )

            // Основная рамка
            drawRoundRect(
                color = frameColor,
                topLeft = Offset(left, top),
                size = Size(boxW, boxH),
                cornerRadius = radius,
                style = Stroke(width = 6f),
            )

            // Кольцо фокуса при касании экрана
            focusRingPoint?.let { pt ->
                drawCircle(
                    color = AccentOrange.copy(alpha = 0.9f),
                    radius = 34f,
                    center = pt,
                    style = Stroke(width = 4f),
                )
            }
        }

        // Индикатор сбора наклейки или паузы между сканированиями
        val statusPillText: Pair<String, Color>? = when {
            !isPaused && burstLabel != null -> burstLabel!! to Color(0xFF5EEAD4)
            !isPaused && isInCooldown -> {
                val sec = String.format(Locale.US, "%.1f", remainingMs / 1000.0)
                "Indiki skana çenli: $sec s" to AccentOrange
            }
            else -> null
        }
        if (statusPillText != null) {
            Surface(
                color = NavyDark.copy(alpha = 0.88f),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(top = 195.dp),
            ) {
                Text(
                    text = statusPillText.first,
                    color = statusPillText.second,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                )
            }
        }

        FloatingActionButton(
            onClick = {
                val cam = boundCamera ?: return@FloatingActionButton
                if (cam.cameraInfo.hasFlashUnit()) {
                    torchEnabled = !torchEnabled
                    cam.cameraControl.enableTorch(torchEnabled)
                }
            },
            shape = CircleShape,
            containerColor = if (torchEnabled) AccentOrange else NavyDark.copy(alpha = 0.82f),
            contentColor = Color.White,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(16.dp),
        ) {
            Icon(
                imageVector = if (torchEnabled) Icons.Default.FlashOn else Icons.Default.FlashOff,
                contentDescription = "Fonar",
            )
        }
    }
}
