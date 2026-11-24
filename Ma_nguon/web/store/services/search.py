"""Accent-insensitive, multi-token Vietnamese search helpers.

PostgreSQL databases initialized with C/POSIX locale only fold ASCII characters in
ILIKE queries, causing Vietnamese uppercase letters (such as Đ/đ, Ă/ă, Ơ/ơ, Ư/ư)
and accentless queries to miss valid matches. Normalizing in Python with NFD
folding handles Vietnamese accents, punctuation variants (-, –, ·), synonyms,
and multi-word queries consistently across storefront and staff screens.
"""

import re
import unicodedata

from store.models import ExternalSkuMap

_PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)
_FILLER_TOKENS = {"mau", "co", "size"}
_SYNONYMS = {
    "sandal": ("xang", "dan"),
    "sandals": ("xang", "dan"),
    "xangdan": ("xang", "dan"),
    "sneaker": ("giay",),
    "sneakers": ("giay",),
}


def fold_vietnamese(text):
    """Lowercase and strip Vietnamese diacritics (including đ/Đ) into plain ASCII."""
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def normalized_words(text):
    """Split folded text into alphanumeric words (ignoring -, –, ·, spaces)."""
    return [tok for tok in _PUNCT_RE.split(fold_vietnamese(text)) if tok]


def query_tokens(query):
    """Extract normalized search tokens, expanding footwear synonyms and trimming fillers."""
    raw_tokens = normalized_words(query)
    if not raw_tokens:
        return []
    expanded = []
    for tok in raw_tokens:
        if tok in _SYNONYMS:
            expanded.extend(_SYNONYMS[tok])
        else:
            expanded.append(tok)
    meaningful = [tok for tok in expanded if tok not in _FILLER_TOKENS]
    return meaningful or expanded


def _matches_token(token, *, words, folded_fields, exact_code_fields, size_tokens, raw_compact):
    # Pure 1-2 digit numbers (e.g. "39", "40") represent shoe sizes — avoid false
    # matches inside product codes like "MH02391" unless the user typed a longer code.
    if token.isdigit() and len(token) <= 2:
        return token in size_tokens or token in words
    if token in words:
        return True
    if any(token in field for field in folded_fields):
        return True
    if any(token in code for code in exact_code_fields):
        return True
    if raw_compact and any(raw_compact in code for code in exact_code_fields):
        return True
    return False


def filter_shop_variants(queryset, query):
    """Filter active storefront Variant queryset with accent-insensitive multi-token search."""
    if not query or not query.strip():
        return queryset
    tokens = query_tokens(query)
    if not tokens:
        return queryset.none()
    raw_compact = re.sub(r"[^a-z0-9]+", "", fold_vietnamese(query))
    rows = list(
        queryset.values_list(
            "pk",
            "sku",
            "product_id",
            "product__code",
            "product__name",
            "product__category__code",
            "product__category__name",
            "product__brand__code",
            "product__brand__name",
            "size__code",
            "size__name",
            "color__code",
            "color__name",
        )
    )
    if not rows:
        return queryset.none()
    variant_ids = [row[0] for row in rows]
    ext_by_variant = {}
    for vid, ext_id in ExternalSkuMap.objects.filter(internal_variant_id__in=variant_ids).values_list(
        "internal_variant_id", "external_product_id"
    ):
        ext_by_variant.setdefault(vid, []).append(fold_vietnamese(ext_id))

    matched_ids = []
    for (
        pk,
        sku,
        _product_id,
        p_code,
        p_name,
        cat_code,
        cat_name,
        brand_code,
        brand_name,
        size_code,
        size_name,
        color_code,
        color_name,
    ) in rows:
        text_parts = [p_name, cat_name, brand_name, color_name, size_name]
        words = set()
        folded_fields = []
        for part in text_parts:
            folded = fold_vietnamese(part)
            folded_fields.append(folded)
            words.update(normalized_words(part))
        # Include category/brand/color codes as words too
        for code in (cat_code, brand_code, color_code):
            if code:
                fcode = fold_vietnamese(code)
                words.add(fcode)
                folded_fields.append(fcode)
        size_tokens = set(normalized_words(f"{size_code} {size_name}"))
        exact_codes = [
            fold_vietnamese(p_code),
            fold_vietnamese(sku),
            re.sub(r"[^a-z0-9]+", "", fold_vietnamese(sku)),
            *ext_by_variant.get(pk, ()),
        ]
        # Allow matching exact external_product_id or hyphenated SKU as a single compact query
        if len(raw_compact) >= 5 and any(raw_compact in code for code in exact_codes if code):
            matched_ids.append(pk)
            continue
        if all(
            _matches_token(
                tok,
                words=words,
                folded_fields=folded_fields,
                exact_code_fields=exact_codes,
                size_tokens=size_tokens,
                raw_compact="",
            )
            for tok in tokens
        ):
            matched_ids.append(pk)
    return queryset.filter(pk__in=matched_ids)


def filter_queryset_text(queryset, query, field_paths, *, size_paths=()):
    """Generic accent-insensitive multi-token filter for staff tables (catalog/inventory/forecasts)."""
    if not query or not query.strip():
        return queryset
    tokens = query_tokens(query)
    if not tokens:
        return queryset.none()
    raw_compact = re.sub(r"[^a-z0-9]+", "", fold_vietnamese(query))
    all_paths = ("pk",) + tuple(field_paths)
    size_indices = [all_paths.index(p) for p in size_paths if p in all_paths]
    rows = list(queryset.values_list(*all_paths))
    if not rows:
        return queryset.none()
    matched_ids = []
    for row in rows:
        pk = row[0]
        values = row[1:]
        words = set()
        folded_fields = []
        compact_fields = []
        for val in values:
            if val is None:
                continue
            folded = fold_vietnamese(val)
            folded_fields.append(folded)
            words.update(normalized_words(val))
            compact_fields.append(re.sub(r"[^a-z0-9]+", "", folded))
        size_tokens = set()
        for idx in size_indices:
            if row[idx] is not None:
                size_tokens.update(normalized_words(row[idx]))
        if len(raw_compact) >= 5 and any(raw_compact in c for c in compact_fields if c):
            matched_ids.append(pk)
            continue
        if all(
            (
                (tok in size_tokens or tok in words)
                if (tok.isdigit() and len(tok) <= 2 and size_indices)
                else (tok in words or any(tok in f for f in folded_fields))
            )
            for tok in tokens
        ):
            matched_ids.append(pk)
    return queryset.filter(pk__in=matched_ids)
