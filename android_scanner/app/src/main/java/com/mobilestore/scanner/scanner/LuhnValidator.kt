package com.mobilestore.scanner.scanner

data class OcrBoxFields(
    val imeis: List<String> = emptyList(),
    val fuzzyNumericCandidates: List<String> = emptyList(),
    val serialNumber: String? = null,
)

object LuhnValidator {
    private val fifteenDigitsRegex = Regex("""(?<!\d)(\d{15})(?!\d)""")
    private val fuzzyDigitsRegex = Regex("""(?<!\d)(\d{13,16})(?!\d)""")
    private val imeiLineRegex = Regex("""(?i)IMEI\s*[12]?\s*[:#-]?\s*([\d\s\-/]{14,22})""")
    private val serialLineRegex = Regex(
        """(?i)(?:S\s*/\s*N|SERIAL(?:\s*NO\.?)?|SN)\s*[:#-]?\s*\(?S?\)?\s*([A-Z0-9]{7,20})"""
    )

    fun isValidImei(raw: String): Boolean {
        val clean = raw.filter { it.isDigit() }
        if (clean.length != 15) return false
        var sum = 0
        for (i in 0 until 15) {
            val digit = clean[i] - '0'
            sum += if (i % 2 == 1) {
                val doubled = digit * 2
                if (doubled > 9) doubled - 9 else doubled
            } else {
                digit
            }
        }
        return sum % 10 == 0
    }

    /**
     * Очищает типичные префиксы на наклейках коробок смартфонов: (S), S/N:, SN:, IMEI:, 1P и т.д.
     */
    fun cleanBoxBarcode(raw: String): String {
        var s = raw.trim()
        val prefixes = listOf(
            Regex("""^(?i)\(S\)\s*"""),
            Regex("""^(?i)S\s*/\s*N\s*[:#-]?\s*"""),
            Regex("""^(?i)SN\s*[:#-]\s*"""),
            Regex("""^(?i)IMEI\s*[12]?\s*[:#-]?\s*"""),
        )
        for (rx in prefixes) {
            s = s.replaceFirst(rx, "")
        }
        // Apple иногда кодирует серийник в Code 128 с ведущей буквой S перед 10–12 символами
        if (s.length in 11..13 && (s.startsWith("S") || s.startsWith("s"))) {
            val tail = s.substring(1)
            if (tail.any { it.isLetter() } && tail.any { it.isDigit() } && tail.all { it.isLetterOrDigit() }) {
                return tail.uppercase()
            }
        }
        return s.trim()
    }

    /**
     * Определяет, похож ли код (из Code 128 / Code 39) на серийный номер устройства (S/N).
     * Отсеивает 15-значные IMEI и чисто цифровые короткие EAN/UPC-коды.
     */
    fun isLikelySerialNumber(raw: String): Boolean {
        val clean = cleanBoxBarcode(raw).uppercase()
        if (clean.length !in 7..20) return false
        if (!clean.all { it.isLetterOrDigit() }) return false
        if (clean.all { it.isDigit() }) {
            // Чисто цифровой S/N не может быть 15-значным Luhn IMEI или стандартным EAN-8/13/UPC-12
            if (clean.length in setOf(8, 12, 13, 15)) return false
            return clean.length in 10..14
        }
        val hasLetter = clean.any { it.isLetter() }
        val hasDigit = clean.any { it.isDigit() }
        return hasLetter && hasDigit
    }

    /**
     * Извлекает валидные 15-значные IMEI (прошедшие Luhn) из распознанного OCR-текста.
     */
    fun extractValidImeisFromOcr(text: String): List<String> {
        val found = LinkedHashSet<String>()

        imeiLineRegex.findAll(text).forEach { match ->
            val digits = match.groupValues[1].filter { it.isDigit() }
            if (digits.length == 15 && isValidImei(digits)) {
                found.add(digits)
            }
        }

        fifteenDigitsRegex.findAll(text).forEach { match ->
            val candidate = match.groupValues[1]
            if (isValidImei(candidate)) {
                found.add(candidate)
            }
        }
        return found.toList()
    }

    /**
     * Извлекает из OCR-текста коробки:
     * - валидные Luhn IMEI
     * - нечёткие 13–16-значные числовые кандидаты (если 1–2 цифры бликуют — для нечёткого поиска при продаже)
     * - серийный номер рядом с метками S/N, SN, Serial
     */
    fun extractBoxFieldsFromOcr(text: String): OcrBoxFields {
        val validImeis = LinkedHashSet<String>()
        val fuzzyNums = LinkedHashSet<String>()

        imeiLineRegex.findAll(text).forEach { match ->
            val digits = match.groupValues[1].filter { it.isDigit() }
            if (digits.length == 15 && isValidImei(digits)) {
                validImeis.add(digits)
            } else if (digits.length in 13..16) {
                fuzzyNums.add(digits)
            }
        }

        fuzzyDigitsRegex.findAll(text).forEach { match ->
            val digits = match.groupValues[1]
            if (digits.length == 15 && isValidImei(digits)) {
                validImeis.add(digits)
            } else if (digits.length in 14..16) {
                fuzzyNums.add(digits)
            }
        }

        val serial = serialLineRegex.find(text)?.groupValues?.getOrNull(1)
            ?.let { cleanBoxBarcode(it).uppercase() }
            ?.takeIf { isLikelySerialNumber(it) }

        return OcrBoxFields(
            imeis = validImeis.toList(),
            fuzzyNumericCandidates = fuzzyNums.toList(),
            serialNumber = serial,
        )
    }
}
