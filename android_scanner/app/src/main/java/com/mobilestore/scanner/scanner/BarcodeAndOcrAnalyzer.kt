package com.mobilestore.scanner.scanner

import android.annotation.SuppressLint
import android.graphics.Rect
import android.graphics.RectF
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.max

/**
 * Структурированный результат мульти-скана наклейки коробки (или одиночного штрихкода).
 */
data class ScanBundle(
    val imei1: String? = null,
    val imei2: String? = null,
    val serialNumber: String? = null,
    val productBarcode: String? = null,
    val allCodes: List<String> = emptyList(),
    val source: String = "barcode", // "barcode" | "qr" | "ocr" | "multi"
) {
    val hasDeviceIdentity: Boolean
        get() = !imei1.isNullOrBlank() || !imei2.isNullOrBlank() || !serialNumber.isNullOrBlank()

    val isOnlyProductBarcode: Boolean
        get() = !hasDeviceIdentity && !productBarcode.isNullOrBlank()

    val primaryCode: String
        get() = imei1 ?: serialNumber ?: imei2 ?: productBarcode ?: allCodes.firstOrNull().orEmpty()

    fun summaryLabel(): String {
        val parts = buildList {
            if (!imei1.isNullOrBlank()) add("IMEI1")
            if (!imei2.isNullOrBlank()) add("IMEI2")
            if (!serialNumber.isNullOrBlank()) add("S/N")
            if (!productBarcode.isNullOrBlank()) add("Ştrihkod")
        }
        return if (parts.size > 1) {
            "[${parts.joinToString(" + ")}] $primaryCode"
        } else {
            val tag = when (source) {
                "ocr" -> "OCR"
                "qr" -> "QR"
                else -> parts.firstOrNull() ?: "Ştrihkod"
            }
            "[$tag] $primaryCode"
        }
    }
}

/**
 * Умный потоковый анализатор CameraX + ML Kit:
 * 1. Считывает ВСЕ штрихкоды в кадре одновременно (EAN/UPC, Code 128, Code 39, QR)
 *    с сортировкой сверху вниз по boundingBox и автоматической классификацией на:
 *    IMEI 1, IMEI 2, Serial Number (S/N) и штрихкод товара (EAN/UPC).
 * 2. За короткое окно накопления (burstWindowMs: ~550–850 мс) объединяет соседние
 *    штрихкоды наклейки коробки + OCR-подписи в один полный пакет ScanBundle.
 * 3. Соблюдает глобальную защитную паузу между сканированиями (по умолчанию 2.5 с).
 */
class BarcodeAndOcrAnalyzer(
    private val isPaused: () -> Boolean,
    private val enableOcr: () -> Boolean,
    private val previewSizeProvider: () -> Pair<Int, Int> = { 0 to 0 },
    private val boxWidthFraction: Float = SCAN_BOX_WIDTH_FRACTION,
    private val boxHeightFraction: Float = SCAN_BOX_HEIGHT_FRACTION,
    private val burstWindowMs: Long = 650L,
    private val cooldownMsProvider: () -> Long,
    private val onCooldownStarted: (cooldownUntilMs: Long) -> Unit,
    private val onBurstProgress: (String?) -> Unit,
    private val onDetected: (ScanBundle) -> Unit,
    private val onBoxTextCaptured: ((String) -> Unit)? = null,
) : ImageAnalysis.Analyzer {

    companion object {
        const val SCAN_BOX_WIDTH_FRACTION = 0.82f
        const val SCAN_BOX_HEIGHT_FRACTION = 0.36f
    }

    private val barcodeScanner = BarcodeScanning.getClient(
        BarcodeScannerOptions.Builder()
            .setBarcodeFormats(
                Barcode.FORMAT_EAN_13,
                Barcode.FORMAT_EAN_8,
                Barcode.FORMAT_UPC_A,
                Barcode.FORMAT_UPC_E,
                Barcode.FORMAT_CODE_128,
                Barcode.FORMAT_CODE_39,
                Barcode.FORMAT_QR_CODE,
            )
            .build()
    )

    private val textRecognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    private val isProcessingFrame = AtomicBoolean(false)
    private val globalCooldownUntilMs = AtomicLong(0L)
    private val pendingBoxCaptureFrames = java.util.concurrent.atomic.AtomicInteger(0)
    private val capturedBoxLines = LinkedHashSet<String>()

    private var frameCounter = 0L
    private var lastEmittedPrimary: String = ""
    private var lastEmittedAt: Long = 0L

    // Буфер короткой серии кадров для сбора всех полей с одной наклейки коробки
    private var burstStartedAt: Long = 0L
    private val burstImeis = LinkedHashSet<String>()
    private var burstSerial: String? = null
    private var burstProductBarcode: String? = null
    private val burstAllCodes = LinkedHashSet<String>()
    private var burstHadBarcode = false
    private var burstHadQr = false
    private var burstHadOcr = false

    // Консенсус для чистого OCR (когда штрихкоды не видны вообще)
    private var lastOcrCandidate: String = ""
    private var ocrConsensusCount: Int = 0

    fun requestBoxTextCapture(frames: Int = 2) {
        synchronized(capturedBoxLines) {
            capturedBoxLines.clear()
        }
        resetBurst()
        pendingBoxCaptureFrames.set(frames.coerceIn(1, 4))
        onBurstProgress("Guty teksti okalýar…")
    }

    fun triggerCooldown(durationMs: Long = cooldownMsProvider()) {
        val until = System.currentTimeMillis() + durationMs.coerceAtLeast(500L)
        globalCooldownUntilMs.set(until)
        pendingBoxCaptureFrames.set(0)
        resetBurst()
        onCooldownStarted(until)
    }

    private fun resetBurst() {
        burstStartedAt = 0L
        burstImeis.clear()
        burstSerial = null
        burstProductBarcode = null
        burstAllCodes.clear()
        burstHadBarcode = false
        burstHadQr = false
        burstHadOcr = false
        lastOcrCandidate = ""
        ocrConsensusCount = 0
        onBurstProgress(null)
    }

    @SuppressLint("UnsafeOptInUsageError")
    override fun analyze(imageProxy: ImageProxy) {
        val now = System.currentTimeMillis()
        val wantsBoxCapture = pendingBoxCaptureFrames.get() > 0

        if (!wantsBoxCapture && (isPaused() || now < globalCooldownUntilMs.get())) {
            if (burstStartedAt > 0L) resetBurst()
            imageProxy.close()
            return
        }

        if (!isProcessingFrame.compareAndSet(false, true)) {
            imageProxy.close()
            return
        }

        val mediaImage = imageProxy.image
        if (mediaImage == null) {
            isProcessingFrame.set(false)
            imageProxy.close()
            return
        }

        val rotation = imageProxy.imageInfo.rotationDegrees
        val inputImage = InputImage.fromMediaImage(mediaImage, rotation)
        val roiRect = computeRoiRect(
            rawWidth = imageProxy.width,
            rawHeight = imageProxy.height,
            rotationDegrees = rotation,
        )
        frameCounter += 1

        // Режим захвата текста коробки аксессуара строго внутри зелёной рамки (2 кадра для защиты от бликов)
        if (wantsBoxCapture) {
            textRecognizer.process(inputImage)
                .addOnSuccessListener { visionText ->
                    val lines = extractTextInsideRoi(visionText, roiRect)
                        .lines()
                        .map { it.trim() }
                        .filter { it.length >= 2 }
                    synchronized(capturedBoxLines) {
                        lines.forEach { capturedBoxLines.add(it) }
                    }
                    val left = pendingBoxCaptureFrames.decrementAndGet()
                    if (left <= 0) {
                        val merged = synchronized(capturedBoxLines) {
                            val out = capturedBoxLines.joinToString("\n")
                            capturedBoxLines.clear()
                            out
                        }
                        onBurstProgress(null)
                        onBoxTextCaptured?.invoke(merged)
                    } else {
                        onBurstProgress("Guty teksti okalýar…")
                    }
                }
                .addOnFailureListener {
                    val left = pendingBoxCaptureFrames.decrementAndGet()
                    if (left <= 0) {
                        val merged = synchronized(capturedBoxLines) {
                            val out = capturedBoxLines.joinToString("\n")
                            capturedBoxLines.clear()
                            out
                        }
                        onBurstProgress(null)
                        onBoxTextCaptured?.invoke(merged)
                    }
                }
                .addOnCompleteListener {
                    finishFrame(imageProxy)
                }
            return
        }

        barcodeScanner.process(inputImage)
            .addOnSuccessListener { barcodes ->
                // Строгая фильтрация: принимаем ТОЛЬКО штрихкоды внутри зелёной рамки!
                val sortedBarcodes = barcodes
                    .filter { !it.rawValue.isNullOrBlank() && isInsideRoi(it.boundingBox, roiRect) }
                    .sortedBy { it.boundingBox?.top ?: Int.MAX_VALUE }

                for (bc in sortedBarcodes) {
                    ingestBarcode(bc)
                }

                val shouldRunOcr = enableOcr() && (
                    // Если идёт сбор наклейки и ещё не собрали все 3 поля — запускаем OCR
                    (burstStartedAt > 0L && (burstImeis.size < 2 || burstSerial == null) && frameCounter % 2L == 0L) ||
                        // Если штрихкоды не видны — запускаем OCR на каждом 3-м кадре
                        (sortedBarcodes.isEmpty() && frameCounter % 3L == 0L)
                    )

                if (shouldRunOcr) {
                    textRecognizer.process(inputImage)
                        .addOnSuccessListener { visionText ->
                            val roiText = extractTextInsideRoi(visionText, roiRect)
                            if (roiText.isNotBlank()) {
                                ingestOcrText(roiText, hasActiveBurst = burstStartedAt > 0L)
                            }
                            maybeEmitBurst()
                        }
                        .addOnCompleteListener {
                            finishFrame(imageProxy)
                        }
                } else {
                    maybeEmitBurst()
                    finishFrame(imageProxy)
                }
            }
            .addOnFailureListener {
                finishFrame(imageProxy)
            }
    }

    /**
     * Точно проецирует зелёный прямоугольник на PreviewView (ScaleType.FILL_CENTER)
     * в координаты повёрнутого InputImage (в пикселях).
     */
    private fun computeRoiRect(
        rawWidth: Int,
        rawHeight: Int,
        rotationDegrees: Int,
    ): RectF {
        val isSwapped = rotationDegrees == 90 || rotationDegrees == 270
        val imgW = (if (isSwapped) rawHeight else rawWidth).toFloat()
        val imgH = (if (isSwapped) rawWidth else rawHeight).toFloat()

        val (viewWInt, viewHInt) = previewSizeProvider()
        val visibleW: Float
        val visibleH: Float
        if (viewWInt > 0 && viewHInt > 0) {
            val viewW = viewWInt.toFloat()
            val viewH = viewHInt.toFloat()
            val scale = max(viewW / imgW, viewH / imgH)
            visibleW = viewW / scale
            visibleH = viewH / scale
        } else {
            visibleW = imgW
            visibleH = imgH
        }

        val cropLeft = (imgW - visibleW) / 2f
        val cropTop = (imgH - visibleH) / 2f

        val roiW = visibleW * boxWidthFraction
        val roiH = visibleH * boxHeightFraction
        val left = cropLeft + (visibleW - roiW) / 2f
        val top = cropTop + (visibleH - roiH) / 2f
        return RectF(left, top, left + roiW, top + roiH)
    }

    private fun isInsideRoi(box: Rect?, roi: RectF): Boolean {
        if (box == null) return false
        val cx = box.exactCenterX()
        val cy = box.exactCenterY()
        return cx >= roi.left && cx <= roi.right && cy >= roi.top && cy <= roi.bottom
    }

    private fun extractTextInsideRoi(visionText: Text, roi: RectF): String {
        val out = mutableListOf<String>()
        for (block in visionText.textBlocks) {
            for (line in block.lines) {
                if (isInsideRoi(line.boundingBox, roi)) {
                    val t = line.text.trim()
                    if (t.isNotEmpty()) out.add(t)
                }
            }
        }
        return out.joinToString("\n")
    }

    private fun ingestBarcode(bc: Barcode) {
        val raw = bc.rawValue?.trim().orEmpty()
        if (raw.isEmpty()) return

        if (burstStartedAt == 0L) {
            burstStartedAt = System.currentTimeMillis()
        }

        val format = bc.format
        if (format == Barcode.FORMAT_QR_CODE) {
            burstHadQr = true
            burstAllCodes.add(raw)
            val ocrFromQr = LuhnValidator.extractBoxFieldsFromOcr(raw)
            ocrFromQr.imeis.forEach { burstImeis.add(it); burstAllCodes.add(it) }
            if (burstSerial == null && ocrFromQr.serialNumber != null) {
                burstSerial = ocrFromQr.serialNumber
                burstAllCodes.add(ocrFromQr.serialNumber)
            }
            if (burstImeis.isEmpty() && burstSerial == null && burstProductBarcode == null) {
                burstProductBarcode = raw
            }
            return
        }

        burstHadBarcode = true

        // 1. Стандартные товарные штрихкоды (EAN / UPC) -> только productBarcode, никогда не IMEI!
        val isRetailBarcode = format == Barcode.FORMAT_EAN_13 ||
            format == Barcode.FORMAT_EAN_8 ||
            format == Barcode.FORMAT_UPC_A ||
            format == Barcode.FORMAT_UPC_E
        if (isRetailBarcode) {
            if (burstProductBarcode == null) {
                burstProductBarcode = raw
            }
            burstAllCodes.add(raw)
            return
        }

        // 2. Code 128 / Code 39 и прочие 1D штрихкоды коробки (IMEI 1, IMEI 2, S/N)
        val clean = LuhnValidator.cleanBoxBarcode(raw)
        val digitsOnly = clean.filter { it.isDigit() }

        when {
            digitsOnly.length == 15 && clean.all { it.isDigit() } && LuhnValidator.isValidImei(digitsOnly) -> {
                burstImeis.add(digitsOnly)
                burstAllCodes.add(digitsOnly)
            }
            LuhnValidator.isLikelySerialNumber(raw) -> {
                val sn = LuhnValidator.cleanBoxBarcode(raw).uppercase()
                if (burstSerial == null) {
                    burstSerial = sn
                }
                burstAllCodes.add(sn)
                if (raw.uppercase() != sn) burstAllCodes.add(raw.uppercase())
            }
            digitsOnly.length in 13..16 && clean.all { it.isDigit() } -> {
                // Возможный IMEI с 1–2 сбойными цифрами — отправляем в общий список для нечёткого поиска
                burstAllCodes.add(digitsOnly)
            }
            else -> {
                if (burstProductBarcode == null) {
                    burstProductBarcode = clean
                }
                burstAllCodes.add(clean)
            }
        }
    }

    private fun ingestOcrText(text: String, hasActiveBurst: Boolean) {
        val fields = LuhnValidator.extractBoxFieldsFromOcr(text)
        if (hasActiveBurst) {
            // Дополняем уже начатую серию полей с наклейки
            fields.imeis.forEach { imei ->
                if (burstImeis.add(imei)) burstHadOcr = true
                burstAllCodes.add(imei)
            }
            if (burstSerial == null && fields.serialNumber != null) {
                burstSerial = fields.serialNumber
                burstAllCodes.add(fields.serialNumber)
                burstHadOcr = true
            }
            fields.fuzzyNumericCandidates.forEach { burstAllCodes.add(it) }
            return
        }

        // Чистый OCR (без видимого штрихкода): требуем 2 согласованных кадра подряд
        val bestCandidate = fields.imeis.firstOrNull() ?: fields.fuzzyNumericCandidates.firstOrNull()
        if (bestCandidate != null) {
            if (bestCandidate == lastOcrCandidate) {
                ocrConsensusCount += 1
            } else {
                lastOcrCandidate = bestCandidate
                ocrConsensusCount = 1
            }
            if (ocrConsensusCount >= 2) {
                ocrConsensusCount = 0
                burstStartedAt = System.currentTimeMillis()
                burstHadOcr = true
                fields.imeis.forEach { burstImeis.add(it); burstAllCodes.add(it) }
                fields.fuzzyNumericCandidates.forEach { burstAllCodes.add(it) }
                if (fields.serialNumber != null) {
                    burstSerial = fields.serialNumber
                    burstAllCodes.add(fields.serialNumber)
                }
            }
        }
    }

    private fun maybeEmitBurst() {
        if (burstStartedAt == 0L || burstAllCodes.isEmpty()) return

        val now = System.currentTimeMillis()
        val elapsed = now - burstStartedAt
        val hasCompletePhoneLabel = burstImeis.size >= 2 && burstSerial != null

        // Показываем живой прогресс сбора наклейки
        if (!hasCompletePhoneLabel && elapsed < burstWindowMs) {
            val found = buildList {
                if (burstImeis.isNotEmpty()) add("IMEI1")
                if (burstImeis.size >= 2) add("IMEI2")
                if (burstSerial != null) add("S/N")
                if (burstProductBarcode != null) add("Ştrihkod")
            }
            if (found.isNotEmpty()) {
                onBurstProgress("Okalýar: ${found.joinToString(" + ")}…")
            }
            return
        }

        val imeiList = burstImeis.toList()
        val bundle = ScanBundle(
            imei1 = imeiList.getOrNull(0),
            imei2 = imeiList.getOrNull(1),
            serialNumber = burstSerial,
            productBarcode = burstProductBarcode,
            allCodes = burstAllCodes.toList(),
            source = when {
                (burstImeis.size + (if (burstSerial != null) 1 else 0) + (if (burstProductBarcode != null) 1 else 0)) >= 2 -> "multi"
                burstHadQr -> "qr"
                burstHadBarcode -> "barcode"
                else -> "ocr"
            },
        )
        resetBurst()
        emitWithCooldown(bundle)
    }

    private fun finishFrame(imageProxy: ImageProxy) {
        isProcessingFrame.set(false)
        imageProxy.close()
    }

    private fun emitWithCooldown(bundle: ScanBundle) {
        val now = System.currentTimeMillis()
        val globalPauseMs = cooldownMsProvider().coerceIn(1_000L, 6_000L)
        val sameCodePauseMs = max(globalPauseMs * 2L, 4_500L)

        if (now < globalCooldownUntilMs.get()) return
        val primary = bundle.primaryCode
        if (primary.isBlank()) return
        if (primary == lastEmittedPrimary && (now - lastEmittedAt) < sameCodePauseMs) return

        lastEmittedPrimary = primary
        lastEmittedAt = now
        val until = now + globalPauseMs
        globalCooldownUntilMs.set(until)
        onCooldownStarted(until)
        onDetected(bundle)
    }

    fun release() {
        runCatching { barcodeScanner.close() }
        runCatching { textRecognizer.close() }
    }
}
