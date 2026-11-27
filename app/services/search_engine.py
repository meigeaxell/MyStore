"""Единый быстрый движок поиска MobileStore (SQLite FTS5 + синонимы + digit-safe RapidFuzz).

Особенности:
- Нормализация туркменской латиницы (ç/c, ş/s, ä/a, ö/o, ü/u, ý/y, ň/n, ž/z),
  кириллицы и русской раскладки клавиатуры (шзрщту -> iphone).
- Пользовательский словарь синонимов (таблица `search_synonyms`, двунаправленный).
- Встроенный полнотекстовый индекс SQLite FTS5 (< 2-3 мс на 5 000+ товарах).
- Умный fuzzy-поиск через RapidFuzz: прощает опечатки в словах (samsng -> samsung),
  но строго проверяет цифровые индексы моделей (a54 != a55, 15 != 16).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.models.category import Category
from app.models.product import Product
from app.models.product_ocr_alias import ProductOcrAlias
from app.models.search_synonym import SearchSynonym

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover - fallback if rapidfuzz not installed
    _rf_fuzz = None


_TK_FOLD = str.maketrans({
    "ä": "a", "ö": "o", "ü": "u", "ý": "y", "ž": "z", "ň": "n", "ş": "s", "ç": "c",
    "Ä": "a", "Ö": "o", "Ü": "u", "Ý": "y", "Ž": "z", "Ň": "n", "Ş": "s", "Ç": "c",
})

_RU_LAYOUT = "йцукенгшщзхъфывапролджэячсмитьбюё"
_EN_LAYOUT = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
_LAYOUT_MAP = {ord(r): ord(e) for r, e in zip(_RU_LAYOUT, _EN_LAYOUT)}
_LAYOUT_MAP.update({ord(r.upper()): ord(e.upper()) for r, e in zip(_RU_LAYOUT, _EN_LAYOUT)})

_CYR_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HAS_CYR_RE = re.compile(r"[а-яёА-ЯЁ]")
_HAS_DIGIT_RE = re.compile(r"\d")

DEFAULT_SEARCH_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("ip", "iphone, ayfon, айфон"),
    ("13pm", "iphone 13 pro max"),
    ("14pm", "iphone 14 pro max"),
    ("15pm", "iphone 15 pro max"),
    ("16pm", "iphone 16 pro max"),
    ("17pm", "iphone 17 pro max"),
    ("sam", "samsung, самсунг"),
    ("rn12", "redmi note 12"),
    ("rn13", "redmi note 13"),
    ("rn14", "redmi note 14"),
    ("cehol", "çehol, case, cover, chehol, чехол"),
    ("udarnyk", "glass, steklo, aýna, защитное, стекло"),
    ("nausnik", "nauşnik, earbuds, airpods, pods, headphones, наушники"),
    ("zaradnik", "zarýadnik, charger, adapter, blok, зарядка, блок"),
    ("kabel", "cable, type-c, lightning, шнур, кабель"),
    ("gara", "black, blk, черный"),
    ("ak", "white, wht, белый"),
    ("gok", "gök, blue, синий"),
    ("yashyl", "ýaşyl, green, зеленый"),
    ("gyzyl", "red, красный"),
    ("altyn", "gold, золотой"),
)

# In-memory кэш синонимов и FTS-готовности (инвалидируется при правках)
_SYNONYM_GROUPS_CACHE: list[tuple[str, list[str]]] | None = None
_TOKEN_SYNONYMS_CACHE: dict[str, set[str]] | None = None
_PHRASE_EXPANSIONS_CACHE: dict[str, list[str]] | None = None
_FTS_READY_ENGINES: set[int] = set()


def normalize_text(raw: str | None) -> str:
    """Приводит строку к нижнему регистру, сворачивает туркменскую латиницу и транслитерирует кириллицу."""
    s = (raw or "").strip().lower().translate(_TK_FOLD)
    if _HAS_CYR_RE.search(s):
        s = "".join(_CYR_TRANSLIT.get(ch, ch) for ch in s)
    return " ".join(_TOKEN_RE.findall(s))


def normalize_layout_variant(raw: str | None) -> str:
    """Преобразует случайно набранную в русской раскладке латиницу (шзрщту -> iphone)."""
    s = (raw or "").strip()
    if not s or not _HAS_CYR_RE.search(s):
        return ""
    converted = s.translate(_LAYOUT_MAP).lower().translate(_TK_FOLD)
    return " ".join(_TOKEN_RE.findall(converted))


def invalidate_synonym_cache() -> None:
    global _SYNONYM_GROUPS_CACHE, _TOKEN_SYNONYMS_CACHE, _PHRASE_EXPANSIONS_CACHE
    _SYNONYM_GROUPS_CACHE = None
    _TOKEN_SYNONYMS_CACHE = None
    _PHRASE_EXPANSIONS_CACHE = None


def ensure_default_synonyms(session: Session | None = None) -> None:
    """Заполняет базовый словарь синонимов, если таблица `search_synonyms` пуста."""
    def _seed(sess: Session) -> None:
        try:
            cnt = sess.scalar(select(func.count(SearchSynonym.id))) or 0
        except SQLAlchemyError:
            return
        if cnt > 0:
            return
        for term, expansions in DEFAULT_SEARCH_SYNONYMS:
            sess.add(SearchSynonym(term=term, expansions=expansions, is_active=True))
        sess.flush()

    if session is not None:
        _seed(session)
        return
    try:
        with SessionLocal() as owned, owned.begin():
            _seed(owned)
    except SQLAlchemyError:
        pass


def _load_synonym_maps(session: Session | None = None) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Возвращает (однословные двунаправленные синонимы, многословные раскрытия сокращений)."""
    global _SYNONYM_GROUPS_CACHE, _TOKEN_SYNONYMS_CACHE, _PHRASE_EXPANSIONS_CACHE
    if _TOKEN_SYNONYMS_CACHE is not None and _PHRASE_EXPANSIONS_CACHE is not None:
        return _TOKEN_SYNONYMS_CACHE, _PHRASE_EXPANSIONS_CACHE

    rows: list[tuple[str, str]] = []
    try:
        if session is not None:
            ensure_default_synonyms(session)
            db_rows = session.scalars(
                select(SearchSynonym).where(SearchSynonym.is_active.is_(True))
            ).all()
            rows = [(r.term, r.expansions) for r in db_rows]
        else:
            ensure_default_synonyms()
            with SessionLocal() as owned:
                db_rows = owned.scalars(
                    select(SearchSynonym).where(SearchSynonym.is_active.is_(True))
                ).all()
                rows = [(r.term, r.expansions) for r in db_rows]
    except SQLAlchemyError:
        rows = list(DEFAULT_SEARCH_SYNONYMS)

    token_map: dict[str, set[str]] = {}
    phrase_map: dict[str, list[str]] = {}
    groups: list[tuple[str, list[str]]] = []

    for raw_term, raw_exp in rows:
        t_norm = normalize_text(raw_term)
        if not t_norm:
            continue
        parts = [normalize_text(p) for p in raw_exp.split(",")]
        parts = [p for p in parts if p]
        groups.append((t_norm, parts))

        single_tokens = {t_norm} if " " not in t_norm else set()
        for p in parts:
            if " " in p:
                if " " not in t_norm:
                    phrase_map.setdefault(t_norm, []).append(p)
            else:
                single_tokens.add(p)
        if len(single_tokens) > 1:
            for tok in single_tokens:
                token_map.setdefault(tok, set()).update(single_tokens)

    _SYNONYM_GROUPS_CACHE = groups
    _TOKEN_SYNONYMS_CACHE = token_map
    _PHRASE_EXPANSIONS_CACHE = phrase_map
    return token_map, phrase_map


def expand_query_tokens(raw_query: str, session: Session | None = None) -> list[set[str]]:
    """Превращает поисковый запрос в список токен-групп (каждая группа — альтернативы слова).

    Учитывает туркменскую латиницу, кириллицу, синонимы и многословные сокращения (16pm -> iphone 16 pro max).
    """
    norm = normalize_text(raw_query)
    if not norm:
        return []
    token_map, phrase_map = _load_synonym_maps(session)
    groups: list[set[str]] = []
    for tok in norm.split():
        if tok in phrase_map:
            # Например, 16pm -> ['iphone', '16', 'pro', 'max']
            first_phrase = phrase_map[tok][0]
            for pt in first_phrase.split():
                alts = set(token_map.get(pt, {pt}))
                alts.add(pt)
                groups.append(alts)
        else:
            alts = set(token_map.get(tok, {tok}))
            alts.add(tok)
            groups.append(alts)
    return groups


def matches_query_in_memory(haystack_raw: str, query_raw: str) -> bool:
    """Быстрая проверка совпадения для in-memory фильтров (учитывает синонимы, кириллицу и раскладку)."""
    q_clean = (query_raw or "").strip()
    if not q_clean:
        return True
    hay_norm = normalize_text(haystack_raw)
    if not hay_norm:
        return False

    # 1. Основная проверка с раскрытием синонимов
    groups = expand_query_tokens(q_clean)
    if groups and all(any(alt in hay_norm for alt in grp) for grp in groups):
        return True

    # 2. Проверка варианта в русской раскладке (шзрщту -> iphone)
    layout_norm = normalize_layout_variant(q_clean)
    if layout_norm:
        l_groups = expand_query_tokens(layout_norm)
        if l_groups and all(any(alt in hay_norm for alt in grp) for grp in l_groups):
            return True

    return False


# ---------------------------------------------------------------------------
# SQLite FTS5 индекс для мгновенного поиска по 5 000–50 000 товаров
# ---------------------------------------------------------------------------

def _ensure_fts_table(session: Session) -> bool:
    bind = session.get_bind()
    bind_key = id(bind)
    if bind_key in _FTS_READY_ENGINES:
        return True
    try:
        session.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5("
                "product_id UNINDEXED, name_norm, meta_norm, code_norm)"
            )
        )
        fts_cnt = session.execute(text("SELECT count(*) FROM products_fts")).scalar() or 0
        prod_cnt = session.scalar(select(func.count(Product.id)).where(Product.is_active.is_(True))) or 0
        if prod_cnt > 0 and fts_cnt == 0:
            rebuild_fts_index(session)
        _FTS_READY_ENGINES.add(bind_key)
        return True
    except SQLAlchemyError:
        return False


def _product_fts_fields(prod: Product, cat_name: str | None = None) -> tuple[str, str, str]:
    name_norm = normalize_text(prod.name)
    meta_norm = normalize_text(" ".join(filter(None, [prod.brand, prod.model, prod.specification, cat_name])))
    code_norm = normalize_text(" ".join(filter(None, [prod.barcode, prod.sku])))
    return name_norm, meta_norm, code_norm


def sync_product_fts(session: Session, prod: Product) -> None:
    """Обновляет одну запись товара в FTS5-индексе (вызывается при сохранении/архивации)."""
    if not _ensure_fts_table(session):
        return
    try:
        session.execute(text("DELETE FROM products_fts WHERE product_id = :pid"), {"pid": prod.id})
        if prod.is_active:
            cat = session.get(Category, prod.category_id)
            n_norm, m_norm, c_norm = _product_fts_fields(prod, cat.name if cat else "")
            session.execute(
                text(
                    "INSERT INTO products_fts (product_id, name_norm, meta_norm, code_norm) "
                    "VALUES (:pid, :n, :m, :c)"
                ),
                {"pid": prod.id, "n": n_norm, "m": m_norm, "c": c_norm},
            )
    except SQLAlchemyError:
        pass


def rebuild_fts_index(session: Session | None = None) -> int:
    """Полностью пересобирает FTS5-индекс активных товаров."""
    def _do(sess: Session) -> int:
        sess.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5("
                "product_id UNINDEXED, name_norm, meta_norm, code_norm)"
            )
        )
        sess.execute(text("DELETE FROM products_fts"))
        rows = sess.execute(
            select(Product, Category.name)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Product.is_active.is_(True))
        ).all()
        payload = []
        for prod, cat_name in rows:
            n_norm, m_norm, c_norm = _product_fts_fields(prod, cat_name)
            payload.append({"pid": prod.id, "n": n_norm, "m": m_norm, "c": c_norm})
        if payload:
            sess.execute(
                text(
                    "INSERT INTO products_fts (product_id, name_norm, meta_norm, code_norm) "
                    "VALUES (:pid, :n, :m, :c)"
                ),
                payload,
            )
        _FTS_READY_ENGINES.add(id(sess.get_bind()))
        return len(payload)

    if session is not None:
        return _do(session)
    with SessionLocal() as owned, owned.begin():
        return _do(owned)


def _build_fts_match_expr(groups: list[set[str]]) -> str:
    clauses: list[str] = []
    for grp in groups:
        safe_terms = [f"{t}*" for t in sorted(grp) if t and t.isalnum()]
        if not safe_terms:
            continue
        if len(safe_terms) == 1:
            clauses.append(safe_terms[0])
        else:
            clauses.append("(" + " OR ".join(safe_terms) + ")")
    return " AND ".join(clauses)


def _fuzzy_token_score(query_tok: str, candidate_tokens: list[str]) -> float:
    if not candidate_tokens:
        return 0.0
    if _rf_fuzz is not None:
        best = 0.0
        for ct in candidate_tokens:
            if query_tok in ct:
                return 100.0
            sc = float(_rf_fuzz.ratio(query_tok, ct))
            best = max(best, sc)
        return best
    best = 0.0
    for ct in candidate_tokens:
        if query_tok in ct:
            return 100.0
        sc = difflib.SequenceMatcher(None, query_tok, ct).ratio() * 100.0
        best = max(best, sc)
    return best


@dataclass
class SearchHit:
    product: Product
    category_name: str
    score: float
    matched_by: str = "exact"  # exact | fts | fuzzy


@dataclass
class SearchResult:
    hits: list[SearchHit] = field(default_factory=list)
    out_of_stock_count: int = 0
    suggestion: str = ""
    expanded_preview: str = ""


def search_products(
    session: Session,
    query: str,
    *,
    category_id: int | None = None,
    in_stock_only: bool = False,
    limit: int = 50,
    enable_fuzzy: bool = True,
) -> SearchResult:
    """Единый быстрый поиск товаров: FTS5 + синонимы + раскладка + digit-safe RapidFuzz."""
    raw = (query or "").strip()
    if not raw:
        return SearchResult()

    groups = expand_query_tokens(raw, session=session)
    layout_norm = normalize_layout_variant(raw)
    layout_groups = expand_query_tokens(layout_norm, session=session) if layout_norm else []

    preview_parts = []
    for grp in groups:
        if len(grp) > 1:
            preview_parts.append("(" + " / ".join(sorted(grp)[:4]) + ")")
        else:
            preview_parts.append(next(iter(grp)))
    expanded_preview = " ".join(preview_parts)

    candidate_ids: list[int] = []
    fts_ok = _ensure_fts_table(session)

    if fts_ok:
        for grp_set in (groups, layout_groups):
            if not grp_set:
                continue
            expr = _build_fts_match_expr(grp_set)
            if not expr:
                continue
            try:
                fts_rows = session.execute(
                    text(
                        "SELECT product_id FROM products_fts "
                        "WHERE products_fts MATCH :expr "
                        "ORDER BY bm25(products_fts, 1.0, 0.6, 1.2) "
                        "LIMIT :lim"
                    ),
                    {"expr": expr, "lim": max(limit * 4, 200)},
                ).scalars().all()
                for pid in fts_rows:
                    if pid not in candidate_ids:
                        candidate_ids.append(int(pid))
            except SQLAlchemyError:
                pass

    hits: list[SearchHit] = []
    out_of_stock_ids: set[int] = set()

    if candidate_ids:
        stmt = (
            select(Product, Category.name)
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Product.id.in_(candidate_ids), Product.is_active.is_(True))
        )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        rows_by_id = {p.id: (p, cn or "") for p, cn in session.execute(stmt).all()}

        for rank_idx, pid in enumerate(candidate_ids):
            pair = rows_by_id.get(pid)
            if pair is None:
                continue
            prod, cat_name = pair
            if in_stock_only and int(prod.stock_quantity or 0) <= 0:
                out_of_stock_ids.add(prod.id)
                continue
            stock_bonus = 20.0 if int(prod.stock_quantity or 0) > 0 else 0.0
            score = max(10.0, 100.0 - rank_idx * 0.4) + stock_bonus
            hits.append(SearchHit(product=prod, category_name=cat_name, score=score, matched_by="fts"))

    # Второй эшелон: digit-safe RapidFuzz, если точный/FTS поиск дал < 5 результатов
    if enable_fuzzy and len(hits) < 5:
        active_groups = groups or layout_groups
        if active_groups:
            seen_ids = {h.product.id for h in hits}
            stmt = (
                select(Product, Category.name)
                .outerjoin(Category, Product.category_id == Category.id)
                .where(Product.is_active.is_(True))
            )
            if category_id is not None:
                stmt = stmt.where(Product.category_id == category_id)
            all_rows = session.execute(stmt).all()

            digit_groups = [g for g in active_groups if all(_HAS_DIGIT_RE.search(t) for t in g)]
            word_groups = [g for g in active_groups if g not in digit_groups]

            fuzzy_scored: list[SearchHit] = []
            for prod, cat_name in all_rows:
                if prod.id in seen_ids:
                    continue
                hay_norm = normalize_text(
                    " ".join(filter(None, [prod.name, prod.brand, prod.model, prod.specification, cat_name, prod.barcode]))
                )
                if not hay_norm:
                    continue
                cand_tokens = hay_norm.split()

                # Цифровые индексы (15, 54, 55, 256, 16pm) должны совпадать строго!
                digits_ok = True
                for d_grp in digit_groups:
                    if not any(any(dt == ct or ct.startswith(dt) for ct in cand_tokens) for dt in d_grp):
                        digits_ok = False
                        break
                if not digits_ok:
                    continue

                if not word_groups:
                    avg_score = 88.0
                else:
                    word_scores = []
                    for w_grp in word_groups:
                        best_alt = max(_fuzzy_token_score(alt, cand_tokens) for alt in w_grp)
                        word_scores.append(best_alt)
                    if min(word_scores) < 72.0:
                        continue
                    avg_score = sum(word_scores) / len(word_scores)
                    if avg_score < 76.0:
                        continue

                if in_stock_only and int(prod.stock_quantity or 0) <= 0:
                    out_of_stock_ids.add(prod.id)
                    continue

                stock_bonus = 15.0 if int(prod.stock_quantity or 0) > 0 else 0.0
                fuzzy_scored.append(
                    SearchHit(
                        product=prod,
                        category_name=cat_name or "",
                        score=avg_score + stock_bonus,
                        matched_by="fuzzy",
                    )
                )

            fuzzy_scored.sort(key=lambda h: (-h.score, h.product.name.lower()))
            hits.extend(fuzzy_scored[: max(0, limit - len(hits))])

    hits.sort(
        key=lambda h: (
            0 if int(h.product.stock_quantity or 0) > 0 else 1,
            -h.score,
            h.product.name.lower(),
        )
    )
    hits = hits[:limit]

    suggestion = ""
    if not hits and enable_fuzzy:
        # Ищем ближайший товар для подсказки «Belki şuny gözlediňiz...»
        res_any = search_products(
            session,
            raw,
            category_id=category_id,
            in_stock_only=False,
            limit=1,
            enable_fuzzy=True,
        ) if in_stock_only else None
        if res_any and res_any.hits:
            suggestion = res_any.hits[0].product.name

    return SearchResult(
        hits=hits,
        out_of_stock_count=len(out_of_stock_ids),
        suggestion=suggestion,
        expanded_preview=expanded_preview,
    )


# ---------------------------------------------------------------------------
# CRUD для вкладки «Gözleg sözlügi» в Настройках
# ---------------------------------------------------------------------------

def list_synonyms() -> list[SearchSynonym]:
    ensure_default_synonyms()
    with SessionLocal() as session:
        return list(
            session.scalars(select(SearchSynonym).order_by(SearchSynonym.term.asc())).all()
        )


def upsert_synonym(term: str, expansions: str, synonym_id: int | None = None) -> SearchSynonym:
    clean_term = normalize_text(term)
    clean_exp = ", ".join(p.strip() for p in (expansions or "").split(",") if p.strip())
    if not clean_term:
        raise ValueError("Gysga sözi (ýa-da adalgany) giriziň.")
    if not clean_exp:
        raise ValueError("Meňzeş sözleri otur bilen bölüp giriziň.")

    with SessionLocal() as session, session.begin():
        if synonym_id is not None:
            row = session.get(SearchSynonym, synonym_id)
            if row is None:
                raise ValueError("Ýazgy tapylmady.")
            dup = session.scalar(
                select(SearchSynonym).where(
                    SearchSynonym.term == clean_term,
                    SearchSynonym.id != synonym_id,
                )
            )
            if dup is not None:
                raise ValueError(f"«{clean_term}» eýýäm sözlükde bar.")
            row.term = clean_term
            row.expansions = clean_exp
            row.is_active = True
        else:
            row = session.scalar(select(SearchSynonym).where(SearchSynonym.term == clean_term))
            if row is not None:
                row.expansions = clean_exp
                row.is_active = True
            else:
                row = SearchSynonym(term=clean_term, expansions=clean_exp, is_active=True)
                session.add(row)
        session.flush()
        session.refresh(row)
    invalidate_synonym_cache()
    return row


def delete_synonym(synonym_id: int) -> None:
    with SessionLocal() as session, session.begin():
        row = session.get(SearchSynonym, synonym_id)
        if row is not None:
            session.delete(row)
    invalidate_synonym_cache()


def reset_default_synonyms() -> int:
    with SessionLocal() as session, session.begin():
        existing = {
            r.term: r for r in session.scalars(select(SearchSynonym)).all()
        }
        added = 0
        for term, expansions in DEFAULT_SEARCH_SYNONYMS:
            clean_t = normalize_text(term)
            if clean_t in existing:
                existing[clean_t].expansions = expansions
                existing[clean_t].is_active = True
            else:
                session.add(SearchSynonym(term=clean_t, expansions=expansions, is_active=True))
                added += 1
    invalidate_synonym_cache()
    return added


def list_ocr_aliases() -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
            select(ProductOcrAlias, Product.name, Product.brand, Product.model)
            .join(Product, ProductOcrAlias.product_id == Product.id)
            .order_by(ProductOcrAlias.hits.desc(), ProductOcrAlias.id.desc())
            .limit(300)
        ).all()
        return [
            {
                "id": alias.id,
                "raw_text": alias.raw_text or alias.normalized_text,
                "normalized_text": alias.normalized_text,
                "product_id": alias.product_id,
                "product_name": prod_name,
                "brand_model": " / ".join(filter(None, [brand, model])),
                "usage_count": alias.hits,
            }
            for alias, prod_name, brand, model in rows
        ]


def delete_ocr_alias(alias_id: int) -> None:
    with SessionLocal() as session, session.begin():
        row = session.get(ProductOcrAlias, alias_id)
        if row is not None:
            session.delete(row)
