"""Умный движок распознавания аксессуаров по OCR-тексту коробки (чистый Python, без тяжёлых ML-библиотек).

Решает 3 задачи:
1. Нормализует «грязный» текст с коробок (разные шрифты, сокращения моделей вроде
   `ip 16 max`, `16pm`, `sam s22`, `rn13`, косвенные маркеры `9D`, `ESD`, `MagSafe`, `20W`).
2. Ранжирует активные карточки из `products` по 4 независимым сигналам
   (выученные алиасы + модель устройства + тип аксессуара + бренд + char n-gram сходство)
   и возвращает Топ-N совпадений с себестоимостью и последней ценой продажи.
3. Генерирует готовый черновик новой карточки (`draft_suggestion`) для быстрой приёмки
   и сохраняет подтверждённые надписи коробок в `product_ocr_aliases`.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.product import Product
from app.models.product_ocr_alias import ProductOcrAlias
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService

# Фразы-мусор на упаковках аксессуаров, не несущие смысла для поиска товара
STOP_PHRASES = (
    "made in china",
    "made in p.r.c",
    "made in prc",
    "designed in california",
    "designed by",
    "high quality",
    "best quality",
    "super quality",
    "original design",
    "all rights reserved",
    "do not throw",
    "keep away from",
    "mobile phone accessories",
    "phone accessories",
)

STOP_WORDS = {
    "for",
    "with",
    "and",
    "the",
    "new",
    "quality",
    "high",
    "super",
    "best",
    "premium",
    "luxury",
    "fashion",
    "style",
    "design",
    "series",
    "edition",
    "version",
    "model",
    "size",
    "pcs",
    "pc",
    "qty",
    "made",
    "china",
    "prc",
    "ce",
    "rohs",
    "fcc",
    "fc",
    "www",
    "http",
    "https",
    "com",
    "net",
    "org",
    "ltd",
    "inc",
    "co",
    "only",
    "use",
    "in",
    "to",
    "of",
    "by",
    "on",
    "at",
    "from",
    "compatible",
    "suitable",
    "mobile",
    "phone",
    "accessories",
    "accessory",
    "üçin",
    "ucin",
    "для",
}

# Типы аксессуаров: ключ -> (туркменское название, ключевые слова и косвенные маркеры)
ACCESSORY_TYPE_LABELS: dict[str, str] = {
    "glass": "Udarnyk / Aýna",
    "case": "Çehol",
    "lens": "Kamera aýnasy",
    "charger": "Adapter / Zarýadka",
    "cable": "Kabel",
    "audio": "Nauşnik",
    "powerbank": "Powerbank",
}

ACCESSORY_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "glass": (
        "glass",
        "tempered",
        "9d",
        "11d",
        "21d",
        "6d",
        "5d",
        "3d",
        "hd",
        "esd",
        "antistatic",
        "anti-static",
        "privacy",
        "antipeep",
        "anti-peep",
        "ceramic",
        "fullglue",
        "full glue",
        "hydrogel",
        "screen",
        "protector",
        "film",
        "ayna",
        "aýna",
        "udarnyk",
        "udarnik",
        "стекло",
        "броне",
        "пленка",
        "плёнка",
        "защитн",
    ),
    "case": (
        "case",
        "cover",
        "silicone",
        "silicon",
        "tpu",
        "magsafe",
        "leather",
        "bumper",
        "armor",
        "shockproof",
        "acrylic",
        "hybrid",
        "wallet",
        "folio",
        "cehol",
        "çehol",
        "чехол",
        "бампер",
        "накладка",
        "силикон",
    ),
    "lens": (
        "camera lens",
        "lens",
        "camera ring",
        "camera protector",
        "camera glass",
        "kamera ayna",
        "kamera aýna",
        "линза",
        "камеры",
    ),
    "charger": (
        "adapter",
        "charger",
        "charging",
        "power adapter",
        "gan",
        "wall charger",
        "car charger",
        "travel charger",
        "fast charge",
        "supervooc",
        "turbo charge",
        "zaryadka",
        "zarýadka",
        "blok",
        "адаптер",
        "заряд",
        "блок",
        "pd 20w",
        "pd20w",
        "20w",
        "25w",
        "30w",
        "33w",
        "45w",
        "65w",
        "67w",
        "100w",
        "120w",
    ),
    "cable": (
        "cable",
        "data cable",
        "charging cable",
        "cord",
        "lightning",
        "type-c",
        "type c",
        "typec",
        "usb-c",
        "usb c",
        "usbc",
        "micro usb",
        "microusb",
        "braided",
        "kabel",
        "кабель",
        "шнур",
        "провод",
        "1m",
        "1.2m",
        "1.5m",
        "2m",
        "3m",
        "3a",
        "5a",
        "6a",
    ),
    "audio": (
        "airpods",
        "buds",
        "earbuds",
        "earphone",
        "earphones",
        "headphone",
        "headphones",
        "headset",
        "tws",
        "bluetooth audio",
        "nausnik",
        "nauşnik",
        "наушник",
        "гарнитур",
    ),
    "powerbank": (
        "powerbank",
        "power bank",
        "portable charger",
        "battery pack",
        "10000mah",
        "20000mah",
        "30000mah",
        "5000mah",
        "повербанк",
    ),
}

# Базовый список популярных брендов аксессуаров и электроники
# (дополняется автоматически всеми брендами из таблицы products!)
KNOWN_ACCESSORY_BRANDS: tuple[str, ...] = (
    "Blueo",
    "Remax",
    "Baseus",
    "Hoco",
    "Borofone",
    "Anker",
    "Ugreen",
    "Spigen",
    "Nillkin",
    "Mocolo",
    "Benks",
    "ESR",
    "Pitaka",
    "Mcdodo",
    "Joyroom",
    "Belkin",
    "Celebrat",
    "LDNIO",
    "Awei",
    "QCY",
    "Oraimo",
    "WiWU",
    "Coteetci",
    "Yesido",
    "Kakusiga",
    "Kaku",
    "Green Lion",
    "Porodo",
    "Levelo",
    "X-Level",
    "Guess",
    "Karl Lagerfeld",
    "UAG",
    "OtterBox",
    "Apple",
    "Samsung",
    "Xiaomi",
    "Honor",
    "Huawei",
    "Original",
)

# Характерные фичи/спецификации, которые полезно вытаскивать с коробки
FEATURE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(21d|11d|9d|6d|5d|3d)\b", "{}"),
    (r"\b(esd|anti[-\s]?static)\b", "Anti-Static"),
    (r"\b(privacy|anti[-\s]?peep)\b", "Privacy"),
    (r"\b(full\s*glue)\b", "Full Glue"),
    (r"\b(ceramic)\b", "Ceramic"),
    (r"\b(hydrogel)\b", "Hydrogel"),
    (r"\b(matte)\b", "Matte"),
    (r"\b(clear|transparent)\b", "Clear"),
    (r"\b(magsafe)\b", "MagSafe"),
    (r"\b(silicone|silicon)\b", "Silicone"),
    (r"\b(tpu)\b", "TPU"),
    (r"\b(leather)\b", "Leather"),
    (r"\b(gan)\b", "GaN"),
    (r"\b(pd)\b", "PD"),
    (r"\b(qc\s*3\.?0|qc\s*4\.?0)\b", "QC"),
    (r"\b(\d{2,3}\s*w)\b", "{}"),
    (r"\b(type[-\s]?c|usb[-\s]?c)\b", "Type-C"),
    (r"\b(lightning)\b", "Lightning"),
    (r"\b(\d(?:\.\d)?\s*m)\b", "{}"),
    (r"\b(\d{4,5}\s*mah)\b", "{}"),
)

# Отображение кириллических символов-двойников внутри латинских OCR-токенов
_CYR_TO_LAT = str.maketrans({
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "к": "k",
    "м": "m",
    "т": "t",
    "н": "h",
    "в": "b",
})


@dataclass
class ParsedBoxSignals:
    raw_text: str
    normalized_text: str
    cleaned_query: str
    device_model: str = ""          # e.g. "iPhone 16 Pro Max"
    device_model_key: str = ""      # e.g. "iphone 16 pro max"
    device_family: str = ""         # e.g. "iphone" | "samsung" | "redmi" | "poco" | "xiaomi"
    accessory_type: str = ""        # e.g. "glass" | "case" | "charger" | "cable" | "lens" | ...
    accessory_type_label: str = ""  # e.g. "Udarnyk / Aýna"
    brand: str = ""                 # e.g. "Blueo"
    features: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)


def _fix_mixed_script_token(tok: str) -> str:
    """Если токен в основном латинский/цифровой, меняет случайно вклеенные кириллические двойники."""
    has_lat_or_dig = any(("a" <= ch <= "z") or ch.isdigit() for ch in tok)
    has_cyr = any("\u0400" <= ch <= "\u04ff" for ch in tok)
    if has_lat_or_dig and has_cyr:
        return tok.translate(_CYR_TO_LAT)
    return tok


def normalize_ocr_text(raw_text: str) -> str:
    """Приводит сырой OCR-текст с коробки к чистому нормализованному виду (без мусора упаковки)."""
    if not raw_text:
        return ""

    text = raw_text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.lower()

    # Убираем известные длинные мусорные фразы
    for phrase in STOP_PHRASES:
        text = text.replace(phrase, " ")

    # Типичные OCR-ошибки для популярных слов
    text = re.sub(r"\b[1l|]phone\b", "iphone", text)
    text = re.sub(r"\biph0ne\b", "iphone", text)
    text = re.sub(r"\bma9safe\b", "magsafe", text)
    text = re.sub(r"\b6lass\b", "glass", text)
    text = re.sub(r"\btype\s*[-_/]\s*c\b", "type-c", text)
    text = re.sub(r"\busb\s*[-_/]\s*c\b", "usb-c", text)
    text = re.sub(r"\banti\s*[-_/]\s*static\b", "anti-static", text)
    text = re.sub(r"\banti\s*[-_/]\s*peep\b", "anti-peep", text)
    text = re.sub(r"\bfull\s+glue\b", "fullglue", text)

    # Убираем знаки препинания, оставляя буквы, цифры, дефис, плюс и точку (для 1.5m / 6.7)
    text = re.sub(r"[^0-9a-zа-яёäöüýžňşç+\-.]+", " ", text)

    raw_tokens = text.split()
    cleaned_tokens: list[str] = []
    seen_consecutive = ""
    for raw_tok in raw_tokens:
        tok = _fix_mixed_script_token(raw_tok.strip(".-"))
        if not tok:
            continue
        # Отбрасываем одиночные бессмысленные буквы (кроме полезных цифр/моделей)
        if len(tok) == 1 and not tok.isdigit():
            continue
        # Отбрасываем длинные цифровые мусорные коды (штрихкоды/EAN/артикулы длиннее 8 цифр)
        if tok.isdigit() and len(tok) >= 8:
            continue
        if tok in STOP_WORDS:
            continue
        if tok == seen_consecutive:
            continue
        seen_consecutive = tok
        cleaned_tokens.append(tok)

    return " ".join(cleaned_tokens)[:255]


def _extract_device_model(norm_text: str) -> tuple[str, str, str]:
    """Вытаскивает каноническую модель телефона из сокращений и вариантов написания.

    Возвращает (display_model, canonical_key, device_family).
    Примеры:
      - "ip 16 max" / "16pm" / "i16 pro max" -> ("iPhone 16 Pro Max", "iphone 16 pro max", "iphone")
      - "ip 15 pro" / "15pro" -> ("iPhone 15 Pro", "iphone 15 pro", "iphone")
      - "sam s22u" / "s22 ultra" -> ("Samsung S22 Ultra", "samsung s22 ultra", "samsung")
      - "sam s22" -> ("Samsung S22", "samsung s22", "samsung")
      - "a55 5g" -> ("Samsung A55", "samsung a55", "samsung")
      - "rn13 pro+" -> ("Redmi Note 13 Pro+", "redmi note 13 pro+", "redmi")
    """
    t = f" {norm_text} "

    # 1. iPhone (явные упоминания или короткие коды вроде 16pm, ip 16 max, i15 pro)
    # 1a. Компактный код: 11..19 + pm (Pro Max)
    m = re.search(r"\b(?:ip|iph|iphone|i)?\s*(1[1-9]|2[0-9])\s*pm\b", t)
    if m:
        num = m.group(1)
        return f"iPhone {num} Pro Max", f"iphone {num} pro max", "iphone"

    # 1b. С префиксом ip/iph/iphone/apple/i + номер + вариант (pro max / max / pro / plus / mini / air / e)
    m = re.search(
        r"\b(?:iphone|iph|ip|apple)\s*[-/]?\s*(1[0-9]|2[0-9]|[678x]|xr|xs|se(?:\s*[234])?)"
        r"(?:\s*(pro\s*max|promax|max|pro|plus|\+|mini|air|e))?\b",
        t,
    )
    if not m:
        # Также ловим склеенное i16 pro max / i15pro / 16 pro max (без слова iphone, если есть pro max / pro / plus)
        m = re.search(
            r"\bi(1[1-9]|2[0-9])(?:\s*(pro\s*max|promax|max|pro|plus|\+|mini|air|e))?\b",
            t,
        )
    if not m:
        m = re.search(
            r"\b(1[1-9]|2[0-9])\s*(pro\s*max|promax|pro|plus|mini)\b",
            t,
        )
        # Убедимся, что перед этим нет redmi / note / xiaomi / mi / poco / pixel / honor
        if m:
            prefix = t[: m.start()].strip().split()[-2:]
            if any(p in {"redmi", "note", "xiaomi", "mi", "poco", "pixel", "honor", "realme", "oppo", "vivo", "rn"} for p in prefix):
                m = None

    if m:
        num = m.group(1).upper()
        variant_raw = (m.group(2) or "").strip().lower()
        variant = ""
        if variant_raw in ("pro max", "promax", "max"):
            variant = "Pro Max" if num not in ("XS",) else "Max"
            if num.isdigit() and int(num) >= 11:
                variant = "Pro Max"
        elif variant_raw == "pro":
            variant = "Pro"
        elif variant_raw in ("plus", "+"):
            variant = "Plus"
        elif variant_raw == "mini":
            variant = "Mini"
        elif variant_raw == "air":
            variant = "Air"
        elif variant_raw == "e":
            num = f"{num}e"
        display = f"iPhone {num} {variant}".strip()
        return display, display.lower(), "iphone"

    # 2. Samsung Galaxy S / Note / Z Fold / Z Flip / A / M
    # S-серия: sam s22, s24u, s23 ultra, s24+, s23 fe
    m = re.search(
        r"\b(?:samsung|sam|galaxy|gal|sm)?\s*s\s*(2[0-9]|10|9|8)\s*(ultra|ult|u|plus|\+|fe)?\b",
        t,
    )
    if m:
        num = m.group(1)
        var_raw = (m.group(2) or "").strip().lower()
        var = ""
        if var_raw in ("ultra", "ult", "u"):
            var = "Ultra"
        elif var_raw in ("plus", "+"):
            var = "Plus"
        elif var_raw == "fe":
            var = "FE"
        display = f"Samsung S{num} {var}".strip()
        return display, display.lower(), "samsung"

    # Z Fold / Z Flip
    m = re.search(r"\b(?:samsung|sam|galaxy)?\s*z?\s*(fold|flip)\s*([3-9])\b", t)
    if m:
        kind = m.group(1).capitalize()
        num = m.group(2)
        display = f"Samsung Z {kind} {num}"
        return display, display.lower(), "samsung"

    # A / M серия Samsung: a55, sam a54 5g, a15, m34
    m = re.search(
        r"\b(?:samsung|sam|galaxy|gal)?\s*([am])\s*([0-9]{2}[s]?)(?:\s*5g)?\b",
        t,
    )
    if m:
        letter = m.group(1).upper()
        num = m.group(2).lower()
        # Не путаем 1m/2m (длина кабеля) или m2/m3
        if len(num) >= 2:
            display = f"Samsung {letter}{num}"
            return display, display.lower(), "samsung"

    # 3. Redmi Note (rn13, rn13 pro+, redmi note 14 pro)
    m = re.search(
        r"\b(?:redmi\s*note|redmi\s*n|rn)\s*([89]|1[0-9])\s*(pro\s*\+|pro\s*plus|pro|s|t|c)?\b",
        t,
    )
    if m:
        num = m.group(1)
        var_raw = (m.group(2) or "").strip().lower()
        var = ""
        if var_raw in ("pro+", "pro +", "pro plus"):
            var = "Pro+"
        elif var_raw == "pro":
            var = "Pro"
        elif var_raw:
            var = var_raw.upper()
        display = f"Redmi Note {num} {var}".strip()
        return display, display.lower(), "redmi"

    # Обычный Redmi (redmi 13c, redmi 12, redmi a3)
    m = re.search(r"\bredmi\s*([a]?\d{1,2}[cxt]?)\s*(pro)?\b", t)
    if m:
        num = m.group(1).upper()
        var = "Pro" if m.group(2) else ""
        display = f"Redmi {num} {var}".strip()
        return display, display.lower(), "redmi"

    # 4. Poco (poco x6 pro, poco f6, poco m6)
    m = re.search(r"\bpoco\s*([xfmc]\s*\d{1,2})\s*(pro|gt)?\b", t)
    if m:
        code = m.group(1).replace(" ", "").upper()
        var = m.group(2).capitalize() if m.group(2) else ""
        display = f"Poco {code} {var}".strip()
        return display, display.lower(), "poco"

    # 5. Xiaomi / Mi
    m = re.search(r"\b(?:xiaomi|mi)\s*(1[1-9])\s*(ultra|pro|t\s*pro|t|lite)?\b", t)
    if m:
        num = m.group(1)
        var = (m.group(2) or "").strip().title()
        display = f"Xiaomi {num} {var}".strip()
        return display, display.lower(), "xiaomi"

    # 6. Honor / Huawei / Pixel / Realme / Oppo / Vivo / Nothing
    m = re.search(
        r"\b(honor|huawei|pixel|realme|oppo|vivo|oneplus|nothing)\s+([a-z0-9]{1,6}(?:\s+(?:pro|plus|ultra|lite|a))?)\b",
        t,
    )
    if m:
        fam = m.group(1).lower()
        sub = m.group(2).strip().upper()
        display = f"{fam.capitalize()} {sub}"
        return display, display.lower(), fam

    return "", "", ""


def _detect_accessory_type(norm_text: str) -> tuple[str, str]:
    """Определяет тип аксессуара по прямым и косвенным маркерам."""
    if not norm_text:
        return "", ""
    padded = f" {norm_text} "
    scores: dict[str, int] = {}
    for acc_type, keywords in ACCESSORY_TYPE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if " " in kw:
                if kw in padded:
                    score += 3
            else:
                if re.search(rf"(?<![0-9a-zа-яёäöüýžňşç]){re.escape(kw)}(?![0-9a-zа-яёäöüýžňşç])", padded):
                    score += 2
                elif len(kw) >= 5 and kw in padded:
                    score += 1
        if score > 0:
            scores[acc_type] = score

    if not scores:
        return "", ""

    # Особый приоритет: "camera lens / camera glass" -> lens, а не glass
    if "lens" in scores and scores["lens"] >= 2:
        return "lens", ACCESSORY_TYPE_LABELS["lens"]
    # Особый приоритет: powerbank (если есть mah / powerbank), даже если упоминается usb-c / 20w
    if "powerbank" in scores and scores["powerbank"] >= 2:
        return "powerbank", ACCESSORY_TYPE_LABELS["powerbank"]
    # Если явно написано "magsafe" вместе с "case/silicone/cover/clear", это case;
    # если "adapter/charger/20w" + "cable", приоритет тому, у кого больше совпадений
    best_type = max(scores.items(), key=lambda kv: kv[1])[0]
    return best_type, ACCESSORY_TYPE_LABELS.get(best_type, best_type)


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    clean = re.sub(r"\s+", " ", text.strip().lower())
    if not clean:
        return Counter()
    if len(clean) < n:
        return Counter({clean: 1})
    return Counter(clean[i : i + n] for i in range(len(clean) - n + 1))


def _cosine_similarity(c1: Counter[str], c2: Counter[str]) -> float:
    if not c1 or not c2:
        return 0.0
    common = set(c1.keys()) & set(c2.keys())
    if not common:
        return 0.0
    dot = sum(c1[k] * c2[k] for k in common)
    n1 = math.sqrt(sum(v * v for v in c1.values()))
    n2 = math.sqrt(sum(v * v for v in c2.values()))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _detect_brand(norm_text: str, catalog_brands: list[str]) -> str:
    """Находит бренд аксессуара из текста коробки (используя базу магазина + базовый список)."""
    if not norm_text:
        return ""
    padded = f" {norm_text} "
    tokens = norm_text.split()

    # Объединяем бренды из каталога пользователя (в приоритете) и встроенный список
    candidates: list[str] = []
    seen_low: set[str] = set()
    for b in [*catalog_brands, *KNOWN_ACCESSORY_BRANDS]:
        clean = (b or "").strip()
        if len(clean) < 2:
            continue
        low = clean.lower()
        if low not in seen_low:
            seen_low.add(low)
            candidates.append(clean)

    # 1. Точное совпадение слова/фразы бренда
    # Бренды устройств (Apple/Samsung/Xiaomi) проверяем последними, чтобы не перебивать бренд аксессуара (Blueo/Remax)
    device_brands = {"apple", "samsung", "xiaomi", "honor", "huawei"}
    ordered = sorted(candidates, key=lambda b: (b.lower() in device_brands, -len(b)))

    for brand in ordered:
        b_low = brand.lower()
        if re.search(rf"(?<![0-9a-z]){re.escape(b_low)}(?![0-9a-z])", padded):
            return brand

    # 2. Нечёткое совпадение токена с брендом (ловит OCR-опечатки вроде Blveo -> Blueo, Basues -> Baseus)
    best_brand = ""
    best_score = 0.0
    for brand in ordered:
        b_low = brand.lower()
        if " " in b_low or len(b_low) < 4 or b_low in device_brands:
            continue
        b_ng = _char_ngrams(b_low, 2)
        for tok in tokens:
            if abs(len(tok) - len(b_low)) > 1 or len(tok) < 4:
                continue
            dist = _levenshtein(tok, b_low)
            if dist == 1 and len(b_low) >= 5 and tok[0] == b_low[0]:
                score = 0.90
            else:
                score = _cosine_similarity(b_ng, _char_ngrams(tok, 2))
            if score >= 0.72 and score > best_score:
                best_score = score
                best_brand = brand

    return best_brand


def _extract_features(norm_text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern, template in FEATURE_PATTERNS:
        for m in re.finditer(pattern, norm_text, flags=re.IGNORECASE):
            val = m.group(1).replace(" ", "").upper() if "{}" in template else template
            if val.endswith("M") and val[:-1].replace(".", "", 1).isdigit():
                val = val.lower()
            elif val.endswith("MAH"):
                val = val[:-3] + "mAh"
            key = val.lower()
            if key not in seen:
                seen.add(key)
                found.append(val)
    return found[:6]


def parse_box_ocr(raw_text: str, catalog_brands: list[str] | None = None) -> ParsedBoxSignals:
    """Разбирает сырой текст с коробки аксессуара на структурированные сигналы."""
    norm = normalize_ocr_text(raw_text)
    model_disp, model_key, family = _extract_device_model(norm)
    acc_type, acc_label = _detect_accessory_type(norm)
    brand = _detect_brand(norm, catalog_brands or [])
    features = _extract_features(norm)

    # Короткая чистая строка для редактируемого поля поиска на телефоне
    query_parts = [p for p in (brand, model_disp, " ".join(features[:3])) if p]
    cleaned_query = " ".join(query_parts).strip() or norm[:80]

    return ParsedBoxSignals(
        raw_text=raw_text or "",
        normalized_text=norm,
        cleaned_query=cleaned_query,
        device_model=model_disp,
        device_model_key=model_key,
        device_family=family,
        accessory_type=acc_type,
        accessory_type_label=acc_label,
        brand=brand,
        features=features,
        tokens=norm.split(),
    )


def _get_last_sale_price(session: Session, product_id: int) -> tuple[Decimal | None, str | None]:
    """Возвращает цену и валюту последней не отменённой продажи данного товара."""
    row = session.execute(
        select(SaleItem.unit_price, SaleItem.currency)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(
            SaleItem.product_id == product_id,
            Sale.status != "cancelled",
        )
        .order_by(Sale.sale_date.desc(), SaleItem.id.desc())
        .limit(1)
    ).first()
    if not row:
        return None, None
    price, currency = row
    return Decimal(str(price)), str(currency or "TMT")


def _suggest_category_id(
    categories: list[Category],
    acc_type: str,
) -> int | None:
    """Подбирает наиболее подходящую активную категорию из базы пользователя."""
    if not categories:
        return None
    if acc_type:
        keywords = ACCESSORY_TYPE_KEYWORDS.get(acc_type, ())
        for cat in categories:
            c_low = normalize_ocr_text(cat.name)
            if any(kw in c_low for kw in keywords):
                return cat.id
    # Фоллбэк: категория «Aksessuarlar / Аксессуары»
    for cat in categories:
        c_low = cat.name.lower()
        if "aksessuar" in c_low or "аксессуар" in c_low or "accessor" in c_low:
            return cat.id
    return categories[0].id


def build_draft_suggestion(
    parsed: ParsedBoxSignals,
    categories: list[Category],
) -> dict[str, Any]:
    """Формирует автозаполненный черновик новой карточки товара из OCR-текста коробки."""
    cat_id = _suggest_category_id(categories, parsed.accessory_type)
    type_word_map = {
        "glass": "Udarnyk",
        "case": "Çehol",
        "lens": "Kamera aýnasy",
        "charger": "Adapter",
        "cable": "Kabel",
        "audio": "Nauşnik",
        "powerbank": "Powerbank",
    }
    type_word = type_word_map.get(parsed.accessory_type, "")

    name_parts: list[str] = []
    if parsed.brand:
        name_parts.append(parsed.brand)
    if type_word:
        name_parts.append(type_word)
    if parsed.features:
        # Добавляем до 2 самых важных фич в название (например, 9D, MagSafe, 20W)
        name_parts.extend(parsed.features[:2])
    if parsed.device_model:
        name_parts.append(parsed.device_model)

    suggested_name = " ".join(name_parts).strip()
    if not suggested_name:
        suggested_name = parsed.cleaned_query[:80].title()

    return {
        "name": suggested_name[:140],
        "category_id": cat_id,
        "brand": parsed.brand,
        "model": parsed.device_model,
        "specification": ", ".join(parsed.features),
        "accessory_type": parsed.accessory_type,
        "accessory_type_label": parsed.accessory_type_label,
    }


def record_ocr_alias(
    session: Session,
    product_id: int,
    raw_text: str,
) -> ProductOcrAlias | None:
    """Сохраняет подтверждённый отпечаток текста коробки для товара (с защитой от шума)."""
    norm = normalize_ocr_text(raw_text)
    alnum_count = sum(1 for ch in norm if ch.isalnum())
    if alnum_count < 4 or not norm:
        return None

    prod = session.get(Product, int(product_id))
    if prod is None:
        return None

    existing = session.scalar(
        select(ProductOcrAlias).where(
            ProductOcrAlias.product_id == prod.id,
            ProductOcrAlias.normalized_text == norm,
        )
    )
    if existing is not None:
        existing.hits = (existing.hits or 0) + 1
        existing.updated_at = datetime.now()
        if raw_text and len(raw_text) > len(existing.raw_text or ""):
            existing.raw_text = raw_text[:500]
        session.flush()
        return existing

    alias = ProductOcrAlias(
        product_id=prod.id,
        normalized_text=norm,
        raw_text=(raw_text or "").strip()[:500] or None,
        hits=1,
    )
    session.add(alias)
    session.flush()
    return alias


def match_accessory_text(
    session: Session,
    raw_text: str,
    category_id: int | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Ищет Топ-N подходящих товаров в базе по OCR-тексту с коробки аксессуара."""
    categories = session.scalars(
        select(Category).where(Category.is_active.is_(True)).order_by(Category.name)
    ).all()
    cat_map = {c.id: c.name for c in categories}

    all_active_products = session.scalars(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
    ).all()

    catalog_brands = sorted({(p.brand or "").strip() for p in all_active_products if (p.brand or "").strip()})
    parsed = parse_box_ocr(raw_text, catalog_brands=catalog_brands)
    draft = build_draft_suggestion(parsed, categories)

    if not parsed.normalized_text:
        return {
            "raw_text": raw_text or "",
            "parsed": {
                "normalized_text": "",
                "cleaned_query": "",
                "brand": "",
                "model": "",
                "accessory_type": "",
                "accessory_type_label": "",
                "features": [],
            },
            "draft_suggestion": draft,
            "items": [],
            "categories": [{"id": c.id, "name": c.name} for c in categories],
        }

    # Загружаем выученные алиасы коробок
    all_aliases = session.scalars(select(ProductOcrAlias)).all()
    aliases_by_product: dict[int, list[ProductOcrAlias]] = {}
    exact_alias_products: set[int] = set()
    for al in all_aliases:
        aliases_by_product.setdefault(al.product_id, []).append(al)
        if al.normalized_text == parsed.normalized_text:
            exact_alias_products.add(al.product_id)

    query_ngrams = _char_ngrams(parsed.normalized_text, 3)
    query_tokens = set(parsed.tokens)

    default_curr = SettingsService.get("default_currency", "TMT")
    default_rate = SettingsService.get_default_exchange_rate()

    scored: list[tuple[float, Product, str]] = []

    for prod in all_active_products:
        if category_id is not None and prod.category_id != category_id:
            continue

        cat_name = cat_map.get(prod.category_id, "")
        prod_blob = " ".join(
            part for part in (cat_name, prod.brand or "", prod.name or "", prod.model or "", prod.specification or "") if part
        )
        prod_norm = normalize_ocr_text(prod_blob)
        _prod_model_disp, prod_model_key, prod_family = _extract_device_model(prod_norm)
        prod_type, _ = _detect_accessory_type(prod_norm)

        score = 0.0
        reasons: list[str] = []

        # 1. Выученные алиасы (самый сильный сигнал при совпадении коробки)
        best_alias_sim = 0.0
        best_alias_hits = 0
        for al in aliases_by_product.get(prod.id, ()):
            if al.normalized_text == parsed.normalized_text:
                best_alias_sim = 1.0
                best_alias_hits = max(best_alias_hits, al.hits or 1)
                break
            sim = _cosine_similarity(query_ngrams, _char_ngrams(al.normalized_text, 3))
            if sim > best_alias_sim:
                best_alias_sim = sim
                best_alias_hits = al.hits or 1

        has_strong_alias = best_alias_sim >= 0.90
        if best_alias_sim >= 0.98:
            # Если точно такой же алиас привязан к нескольким товарам — снижаем вес, чтобы показать все варианты
            alias_pts = 72.0 if len(exact_alias_products) <= 1 else 46.0
            score += alias_pts + min(8.0, best_alias_hits * 1.5)
            reasons.append("Ýatda saklanan guty")
        elif best_alias_sim >= 0.65:
            score += 42.0 * best_alias_sim
            reasons.append("Meňzeş guty")

        # 2. Совпадение модели устройства (критично отличать 16 Pro от 16 Pro Max!)
        if parsed.device_model_key:
            if prod_model_key == parsed.device_model_key:
                score += 42.0
                reasons.append(f"Model: {parsed.device_model}")
            elif prod_model_key and not has_strong_alias:
                if parsed.device_family and prod_family == parsed.device_family:
                    # Та же линейка, но другая модель/размер (например 16 Pro vs 16 Pro Max) — штраф
                    score -= 22.0
                else:
                    # Совсем другая марка телефона (iPhone vs Samsung) — сильный штраф
                    score -= 35.0

        # 3. Тип аксессуара (ударник vs чехол vs кабель vs зарядка)
        if parsed.accessory_type:
            if prod_type == parsed.accessory_type:
                score += 24.0
                reasons.append(parsed.accessory_type_label)
            elif prod_type and not has_strong_alias:
                # Явный конфликт (на коробке 9D стекло, а карточка — чехол)
                score -= 30.0

        # 4. Бренд аксессуара (Blueo vs Remax vs Baseus...)
        prod_brand_low = (prod.brand or "").strip().lower()
        if parsed.brand:
            b_low = parsed.brand.lower()
            if prod_brand_low == b_low or b_low in prod_norm.split():
                score += 24.0
                reasons.append(f"Brend: {parsed.brand}")
            elif prod_brand_low and prod_brand_low not in {"apple", "samsung", "xiaomi"}:
                # На коробке явно указан другой бренд аксессуара
                score -= 10.0

        # 5. Совпадение фич/спецификации (20W, MagSafe, 9D, Privacy, 1m...)
        if parsed.features:
            matched_feats = [f for f in parsed.features if f.lower() in prod_norm]
            if matched_feats:
                score += min(16.0, len(matched_feats) * 6.0)
                reasons.append(", ".join(matched_feats[:2]))

        # 6. Символьное n-gram сходство + пересечение токенов (ловит OCR-опечатки и нестандартные названия)
        ngram_sim = _cosine_similarity(query_ngrams, _char_ngrams(prod_norm, 3))
        score += 22.0 * ngram_sim

        prod_tokens = set(prod_norm.split())
        if query_tokens and prod_tokens:
            overlap = len(query_tokens & prod_tokens)
            if overlap > 0:
                score += min(14.0, overlap * 4.0)

        # Минимальный порог релевантности
        if score < 12.0:
            continue

        # Небольшой приоритет товарам, которые реально есть в наличии
        if prod.stock_quantity > 0:
            score += 4.0

        detail = " • ".join(reasons[:3]) if reasons else "Tekst meňzeşligi"
        scored.append((score, prod, detail))

    scored.sort(key=lambda item: (item[0], item[1].stock_quantity > 0, item[1].stock_quantity), reverse=True)

    # Нормализуем баллы в понятные 0..99%
    items_payload: list[dict[str, Any]] = []
    for raw_score, prod, detail in scored[: max(1, min(int(limit), 15))]:
        pct = max(25, min(99, round((raw_score / 105.0) * 100)))
        unit_cost, cost_curr, _ = SalesService._resolve_item_cost_basis(
            session=session,
            product_id=prod.id,
            stock_item=None,
            fallback_currency=default_curr,
            fallback_rate=default_rate,
        )
        last_price, last_curr = _get_last_sale_price(session, prod.id)
        avail_status = "available" if prod.stock_quantity > 0 else "out_of_stock"
        avail_msg = "Satyş üçin elýeterli" if prod.stock_quantity > 0 else f"«{prod.name}» harydy skladda ýok"

        items_payload.append({
            "product_id": prod.id,
            "stock_item_id": None,
            "sku": prod.sku,
            "name": prod.name,
            "brand": prod.brand or "",
            "model": prod.model or "",
            "specification": prod.specification or "",
            "category_id": prod.category_id,
            "category_name": cat_map.get(prod.category_id, "Kategoriýasyz"),
            "imei": None,
            "imei2": None,
            "serial_number": None,
            "condition": "new",
            "stock_quantity": prod.stock_quantity,
            "unit_cost": f"{unit_cost:.2f}",
            "cost_currency": cost_curr,
            "last_sale_price": f"{last_price:.2f}" if last_price is not None else None,
            "last_sale_currency": last_curr,
            "default_currency": default_curr,
            "exchange_rate": f"{default_rate:.4f}",
            "photo_url": None,
            "availability_status": avail_status,
            "availability_message": avail_msg,
            "match_type": "ocr_box",
            "match_score": pct,
            "match_detail": f"{pct}% • {detail}",
            "scanned_code": parsed.cleaned_query,
            "matched_code": prod.sku,
            "requires_confirmation": False,
        })

    return {
        "raw_text": raw_text,
        "parsed": {
            "normalized_text": parsed.normalized_text,
            "cleaned_query": parsed.cleaned_query,
            "brand": parsed.brand,
            "model": parsed.device_model,
            "accessory_type": parsed.accessory_type,
            "accessory_type_label": parsed.accessory_type_label,
            "features": parsed.features,
        },
        "draft_suggestion": draft,
        "items": items_payload,
        "categories": [{"id": c.id, "name": c.name} for c in categories],
    }
