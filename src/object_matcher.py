from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

from .entity_extractor import OwnCompanyConfig
from .models import CatalogObject, ObjectCandidate, ObjectMatchResult
from .normalizer import clean_string, is_empty, normalize_text


@dataclass(frozen=True)
class _SearchPart:
    text: str
    source: str


@dataclass
class ObjectMatcher:
    objects: list[CatalogObject]
    min_score: float = 80
    min_gap: float = 8
    ambiguous_min_score: float = 90
    aliases: dict[str, list[str]] = field(default_factory=dict)
    exact_phrase_overrides: dict[str, str] = field(default_factory=dict)
    own_company: OwnCompanyConfig = field(default_factory=lambda: OwnCompanyConfig([], [], []))

    def __post_init__(self) -> None:
        self.exact_phrase_overrides = {
            normalize_text(phrase): code
            for phrase, code in self.exact_phrase_overrides.items()
            if normalize_text(phrase) and str(code or "").strip()
        }
        self._prepared_objects = [
            (obj, _object_variants(obj), _variant_tokens(_object_variants(obj)))
            for obj in self.objects
            if not self._is_own_company_object(obj)
        ]
        self._variant_token_index: dict[str, set[int]] = {}
        for idx, (_, _, variant_tokens) in enumerate(self._prepared_objects):
            for token in variant_tokens:
                self._variant_token_index.setdefault(token, set()).add(idx)
        self._objects_by_norm_code = self._build_code_lookup()
        self._alias_hit_cache: dict[str, list[CatalogObject]] = {}
        self._match_cache: dict[tuple[str, str, str, str], ObjectMatchResult] = {}
        self._unsafe_aliases = self._build_unsafe_aliases()

    @classmethod
    def from_excel(
        cls,
        path: str | Path,
        min_score: float = 80,
        min_gap: float = 8,
        ambiguous_min_score: float = 90,
        aliases: dict[str, list[str]] | None = None,
        exact_phrase_overrides: dict[str, str] | None = None,
        supplemental_objects: list[CatalogObject] | None = None,
        own_company: OwnCompanyConfig | None = None,
    ) -> "ObjectMatcher":
        return cls(
            load_catalog(path) + list(supplemental_objects or []),
            min_score=min_score,
            min_gap=min_gap,
            ambiguous_min_score=ambiguous_min_score,
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            own_company=own_company or OwnCompanyConfig([], [], []),
        )

    @classmethod
    def from_records(
        cls,
        records: list[dict[str, Any]],
        min_score: float = 80,
        min_gap: float = 8,
        ambiguous_min_score: float = 90,
        aliases: dict[str, list[str]] | None = None,
        exact_phrase_overrides: dict[str, str] | None = None,
        own_company: OwnCompanyConfig | None = None,
    ) -> "ObjectMatcher":
        objects = [
            CatalogObject(
                code=clean_string(record.get("code", "")),
                name=clean_string(record.get("name", "")),
                group_name=clean_string(record.get("group_name", "")),
                address=clean_string(record.get("address", "")),
                tax_code=clean_string(record.get("tax_code", "")),
                group_code=clean_string(record.get("group_code", "")),
            )
            for record in records
            if clean_string(record.get("code", "")) and clean_string(record.get("name", ""))
        ]
        return cls(
            objects,
            min_score=min_score,
            min_gap=min_gap,
            ambiguous_min_score=ambiguous_min_score,
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            own_company=own_company or OwnCompanyConfig([], [], []),
        )

    def match(
        self,
        counterparty_raw: str = "",
        description: str = "",
        counterparty_hint: str = "",
        cleaned_description: str = "",
    ) -> ObjectMatchResult:
        cache_key = (
            normalize_text(counterparty_raw),
            normalize_text(description),
            normalize_text(counterparty_hint),
            normalize_text(cleaned_description),
        )
        cached = self._match_cache.get(cache_key)
        if cached is not None:
            return cached
        base_search_parts = [
            _SearchPart(normalize_text(counterparty_hint), "hint"),
            _SearchPart(normalize_text(counterparty_raw), "counterparty"),
            _SearchPart(normalize_text(cleaned_description), "description"),
            _SearchPart(self.own_company.strip_from_text(description), "description"),
        ]
        expanded_search_parts = [
            _SearchPart(_expand_common_abbreviations(part.text), part.source)
            for part in base_search_parts
        ]
        search_parts = _dedupe_search_parts(base_search_parts + expanded_search_parts)
        search_texts = [part.text for part in search_parts]
        if not search_parts or not self._prepared_objects:
            result = ObjectMatchResult(error_note="Không tìm thấy mã đối tượng")
            self._match_cache[cache_key] = result
            return result

        exact_candidates = self._exact_phrase_candidates(search_parts)
        if exact_candidates:
            best = exact_candidates[0]
            result = ObjectMatchResult(
                code=best.code,
                name=best.name,
                status="OK",
                score=best.score,
                source=best.source,
                candidates=exact_candidates[:5],
            )
            self._match_cache[cache_key] = result
            return result

        alias_candidates = self._alias_candidates(search_parts)
        fuzzy_candidates = self._fuzzy_candidates(search_texts, bool(counterparty_hint))
        scored = _merge_candidates(alias_candidates + fuzzy_candidates)
        top_candidates = scored[:5]
        if not top_candidates:
            result = ObjectMatchResult(error_note="Không tìm thấy mã đối tượng", candidates=[])
            self._match_cache[cache_key] = result
            return result

        best = top_candidates[0]
        second_score = top_candidates[1].score if len(top_candidates) > 1 else 0.0
        gap = best.score - second_score

        if best.score < self.min_score:
            result = ObjectMatchResult(
                status="NOT_FOUND",
                error_note="Không tìm thấy mã đối tượng",
                score=best.score,
                source=best.source,
                candidates=top_candidates,
            )
            self._match_cache[cache_key] = result
            return result

        if best.source == "fuzzy_name" and best.score < self.ambiguous_min_score:
            result = ObjectMatchResult(
                status="NOT_FOUND",
                error_note="Không tìm thấy mã đối tượng",
                score=best.score,
                source=best.source,
                candidates=top_candidates,
            )
            self._match_cache[cache_key] = result
            return result

        exact_source = best.source in {"alias_match", "tax_code"}
        strong_source = exact_source or best.source == "catalog_phrase"
        second = top_candidates[1] if len(top_candidates) > 1 else None
        competing_strong = bool(second and second.score >= 95 and second.source in {"alias_match", "catalog_phrase", "tax_code"})
        strong_enough = best.score >= 95 and (exact_source or (strong_source and not competing_strong))
        if len(top_candidates) > 1 and gap < self.min_gap and not strong_enough:
            if best.score < self.ambiguous_min_score:
                result = ObjectMatchResult(
                    status="NOT_FOUND",
                    error_note="Không tìm thấy mã đối tượng",
                    score=best.score,
                    source=best.source,
                    candidates=top_candidates,
                )
                self._match_cache[cache_key] = result
                return result
            result = ObjectMatchResult(
                code="ERROR",
                status="AMBIGUOUS",
                error_note="Nhiều mã đối tượng khớp gần bằng nhau",
                score=best.score,
                source=best.source,
                candidates=top_candidates,
            )
            self._match_cache[cache_key] = result
            return result
        result = ObjectMatchResult(
            code=best.code,
            name=best.name,
            status="OK",
            score=best.score,
            source=best.source,
            candidates=top_candidates,
        )
        self._match_cache[cache_key] = result
        return result

    def _exact_phrase_candidates(self, search_parts: list[_SearchPart]) -> list[ObjectCandidate]:
        candidates: list[ObjectCandidate] = []
        for phrase, code in self.exact_phrase_overrides.items():
            obj = self._objects_by_norm_code.get(normalize_text(code))
            if not obj or self._is_own_company_object(obj):
                continue
            if any(_contains_phrase(part.text, phrase) for part in search_parts):
                candidates.append(_candidate_from_object(obj, 100.0, "exact_phrase", phrase))
        candidates.sort(key=lambda item: len(normalize_text(item.matched_on)), reverse=True)
        return _merge_candidates(candidates)

    def _alias_candidates(self, search_parts: list[_SearchPart]) -> list[ObjectCandidate]:
        candidates: list[ObjectCandidate] = []
        for code, aliases in self.aliases.items():
            obj = self._objects_by_norm_code.get(normalize_text(code))
            if not obj or self._is_own_company_object(obj):
                continue
            for alias in aliases:
                if alias in self._unsafe_aliases or _is_blocked_auto_alias(alias):
                    continue
                if any(_alias_matches_search_part(alias, part) for part in search_parts):
                    candidates.append(_candidate_from_object(obj, 100.0, "alias_match", alias))
                    break
        return candidates

    def alias_audit_records(self, catalog: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code, aliases in self.aliases.items():
            target = self._objects_by_norm_code.get(normalize_text(code))
            for alias in aliases:
                hits = self._alias_catalog_hits(alias)
                equivalent_keys = {_catalog_equivalence_key(obj) for obj in hits}
                risk = "ok"
                if not target:
                    risk = "missing_code"
                elif _is_blocked_auto_alias(alias):
                    risk = "blocked_alias"
                elif alias in self._unsafe_aliases:
                    risk = "unsafe_collision"
                elif _is_weak_alias(alias):
                    risk = "weak_alias"
                rows.append(
                    {
                        "catalog": catalog,
                        "code": code,
                        "alias": alias,
                        "risk": risk,
                        "collision_count": len(equivalent_keys),
                        "hit_codes": ", ".join(obj.code for obj in hits[:10]),
                        "hit_names": " | ".join(obj.name for obj in hits[:5]),
                    }
                )
        return rows

    def _build_unsafe_aliases(self) -> dict[str, str]:
        unsafe: dict[str, str] = {}
        for aliases in self.aliases.values():
            for alias in aliases:
                if not alias or _is_exact_identifier(alias):
                    continue
                hits = self._alias_catalog_hits(alias)
                equivalent_keys = {_catalog_equivalence_key(obj) for obj in hits}
                if len(equivalent_keys) > 1:
                    unsafe[alias] = "alias matches multiple catalog objects"
        return unsafe

    def _alias_catalog_hits(self, alias: str) -> list[CatalogObject]:
        if not alias:
            return []
        cached = self._alias_hit_cache.get(alias)
        if cached is not None:
            return cached
        tokens = [token for token in alias.split() if len(token) >= 3]
        if tokens:
            candidate_indexes = set(self._variant_token_index.get(tokens[0], set()))
            for token in tokens[1:]:
                candidate_indexes &= self._variant_token_index.get(token, set())
        else:
            candidate_indexes = set(range(len(self._prepared_objects)))
        hits: list[CatalogObject] = []
        for idx in candidate_indexes:
            obj, variants, _ = self._prepared_objects[idx]
            if any(_alias_matches_variant(alias, variant) for variant in variants):
                hits.append(obj)
        self._alias_hit_cache[alias] = hits
        return hits

    def _fuzzy_candidates(self, search_parts: list[str], has_hint: bool) -> list[ObjectCandidate]:
        search_tokens = _search_tokens(search_parts)
        if not search_tokens:
            return []
        candidate_indexes: set[int] = set()
        for token in search_tokens:
            candidate_indexes.update(self._variant_token_index.get(token, set()))
        if not candidate_indexes:
            return []
        scored: list[ObjectCandidate] = []
        for idx in candidate_indexes:
            obj, variants, variant_tokens = self._prepared_objects[idx]
            if variant_tokens and not (search_tokens & variant_tokens):
                continue
            score, source, matched_on = self._score_object(variants, search_parts, has_hint)
            if score > 0:
                scored.append(_candidate_from_object(obj, round(score, 2), source, matched_on))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def _score_object(self, variants: list[str], search_parts: list[str], has_hint: bool) -> tuple[float, str, str]:
        best = 0.0
        best_source = "fuzzy_name"
        best_variant = ""
        for idx, part in enumerate(search_parts):
            if not part:
                continue
            is_hint_part = has_hint and idx == 0
            for variant in variants:
                if not variant:
                    continue
                if _is_exact_identifier(variant) and _contains_identifier(part, variant):
                    return 100.0, "tax_code", variant
            for variant in variants:
                if not variant or _is_weak_context_variant(variant, part, is_hint_part):
                    continue
                if _is_catalog_phrase_match(part, variant):
                    return 100.0, "catalog_phrase", variant
            for variant in variants:
                if not variant or _is_weak_context_variant(variant, part, is_hint_part):
                    continue
                if is_hint_part and (_contains_phrase(part, variant) or _contains_phrase(variant, part)):
                    return 100.0, "entity_match", variant
            for variant in variants:
                if not variant:
                    continue
                if _is_weak_context_variant(variant, part, is_hint_part):
                    continue
                token_score = fuzz.token_set_ratio(part, variant)
                partial_score = fuzz.partial_ratio(part, variant)
                score = token_score * 0.65 + partial_score * 0.35
                if is_hint_part:
                    score = min(100.0, score + 8)
                if score > best:
                    best = score
                    best_source = "entity_match" if is_hint_part else "fuzzy_name"
                    best_variant = variant
        return best, best_source, best_variant

    def _is_own_company_object(self, obj: CatalogObject) -> bool:
        return self.own_company.is_own_code(obj.code) or self.own_company.is_own_name(obj.name) or self.own_company.is_own_tax_code(obj.tax_code)

    def _build_code_lookup(self) -> dict[str, CatalogObject]:
        lookup = {normalize_text(obj.code): obj for obj, _, _ in self._prepared_objects}
        dropped_d_hits: dict[str, list[CatalogObject]] = {}
        for obj, _, _ in self._prepared_objects:
            code = normalize_text(obj.code)
            if not code.startswith("D") or len(code) < 4:
                continue
            dropped_d_hits.setdefault(code[1:], []).append(obj)
        for code, hits in dropped_d_hits.items():
            equivalent_keys = {_catalog_equivalence_key(obj) for obj in hits}
            if code not in lookup and len(equivalent_keys) == 1:
                lookup[code] = hits[0]
        return lookup


def load_catalog(path: str | Path) -> list[CatalogObject]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    # Close the ExcelFile explicitly. Leaving its ZIP handle to garbage
    # collection prevents Rule Manager from atomically replacing the catalog
    # on Windows after a read.
    with pd.ExcelFile(path) as excel:
        sheet_name = "r_dmdt" if "r_dmdt" in excel.sheet_names else excel.sheet_names[0]
        raw = pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object)
    data_start, columns = _detect_catalog_columns(raw)

    objects: list[CatalogObject] = []
    for row_idx in range(data_start, len(raw)):
        row = raw.iloc[row_idx]
        code = clean_string(_safe_get(row, columns.get("code")))
        name = clean_string(_safe_get(row, columns.get("name")))
        if not code or not name or code.startswith("["):
            continue
        objects.append(
            CatalogObject(
                code=code,
                name=name,
                group_name=clean_string(_safe_get(row, columns.get("group_name"))),
                address=clean_string(_safe_get(row, columns.get("address"))),
                tax_code=clean_string(_safe_get(row, columns.get("tax_code"))),
                group_code=clean_string(_safe_get(row, columns.get("group_code"))),
            )
        )
    return objects


def _detect_catalog_columns(raw: pd.DataFrame) -> tuple[int, dict[str, int]]:
    for idx, row in raw.head(20).iterrows():
        normalized_cells = [normalize_text(value) for value in row.tolist()]
        code_idx = _find_cell_index(normalized_cells, ["MA DT", "MA DOI TUONG"])
        name_idx = _find_cell_index(normalized_cells, ["TEN DOI TUONG", "TEN DT"])
        if code_idx is not None and name_idx is not None:
            return int(idx) + 1, {
                "code": code_idx,
                "name": name_idx,
                "group_name": _find_cell_index(normalized_cells, ["TEN NHOM"]),
                "address": _find_cell_index(normalized_cells, ["DIA CHI"]),
                "tax_code": _find_cell_index(normalized_cells, ["MA SO THUE", "MS THUE"]),
                "group_code": _find_cell_index(normalized_cells, ["MA NHOM DT"]),
            }

    for idx, row in raw.head(30).iterrows():
        values = [clean_string(value) for value in row.tolist()]
        if sum(1 for value in values if value.startswith("[") and value.endswith("]")) >= 4:
            return int(idx) + 1, {
                "code": 1,
                "name": 3,
                "group_name": 4,
                "address": 5,
                "tax_code": 7,
                "group_code": 9,
            }
    raise ValueError("Không tìm thấy cấu trúc cột danh mục đối tượng")


def _find_cell_index(cells: list[str], aliases: list[str]) -> int | None:
    normalized_aliases = [normalize_text(alias) for alias in aliases]
    for idx, cell in enumerate(cells):
        if any(alias in cell for alias in normalized_aliases):
            return idx
    return None


def _safe_get(row: pd.Series, idx: int | None) -> Any:
    if idx is None or idx >= len(row):
        return ""
    value = row.iloc[idx]
    return "" if is_empty(value) else value


def _object_variants(obj: CatalogObject) -> list[str]:
    code = clean_string(obj.code)
    variants = [
        normalize_text(obj.name),
        _simplify_name_norm(obj.name),
        normalize_text(code),
        normalize_text(obj.tax_code),
    ]
    code_norm = normalize_text(code)
    if code[:1].upper() == "Đ" and code_norm.startswith("D") and len(code_norm) >= 4:
        variants.append(code_norm[1:])
    return list(dict.fromkeys(variant for variant in variants if variant))


def _variant_tokens(variants: list[str]) -> set[str]:
    tokens: set[str] = set()
    for variant in variants:
        tokens.update(token for token in variant.split() if len(token) >= 3)
    return tokens


def _search_tokens(search_parts: list[str]) -> set[str]:
    tokens: set[str] = set()
    for part in search_parts:
        tokens.update(token for token in part.split() if len(token) >= 3 and token not in _SEARCH_STOP_TOKENS)
    return tokens


def _simplify_name_norm(name: str) -> str:
    text = normalize_text(name)
    phrase_stops = [
        "CONG TY TRACH NHIEM HUU HAN",
        "CONG TY TNHH MOT THANH VIEN",
        "CONG TY TNHH MTV",
        "CONG TY CO PHAN",
        "CONG TY TNHH",
        "CONG TY",
        "C NG TY",
        "CTY",
        "TNHH",
        "CO PHAN",
        "CHI NHANH",
        "MOT THANH VIEN",
        "TRACH NHIEM HUU HAN",
        "VIET NAM",
        "VIETNAM",
    ]
    for phrase in phrase_stops:
        text = re_sub_phrase(text, phrase, " ")
    word_stops = {
        "CP",
        "MTV",
        "TRACH",
        "NHIEM",
        "HUU",
        "HAN",
    }
    tokens = [token for token in text.split() if token not in word_stops]
    return " ".join(tokens)


def re_sub_phrase(text: str, phrase: str, repl: str) -> str:
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(map(re.escape, phrase.split())) + r"(?![A-Z0-9])"
    return " ".join(re.sub(pattern, repl, text).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    if len(phrase) <= 1:
        return False
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(map(re.escape, phrase.split())) + r"(?![A-Z0-9])"
    return re.search(pattern, text) is not None


def _alias_matches_search_part(alias: str, part: _SearchPart) -> bool:
    if not alias or not _contains_phrase(part.text, alias):
        return False
    if _is_weak_alias(alias):
        return part.source in {"hint", "counterparty"}
    return True


def _expand_common_abbreviations(text: str) -> str:
    replacements = {
        "CTCP": "CONG TY CO PHAN",
        "CTY": "CONG TY",
        "C TY": "CONG TY",
        "CVU": "CANG VU",
        "DT": "DAU TU",
        "TMDV": "THUONG MAI DICH VU",
        "TM DV": "THUONG MAI DICH VU",
        "TM": "THUONG MAI",
        "DV": "DICH VU",
        "XNK": "XUAT NHAP KHAU",
        "XM": "XI MANG",
        "VT": "VAN TAI",
        "QT": "QUOC TE",
        "KS": "KIEM SOAT",
        "HH": "HANG HAI",
        "DL": "DAI LY",
    }
    expanded = text
    for source, target in replacements.items():
        expanded = re_sub_phrase(expanded, source, target)
    return expanded


def _is_exact_identifier(value: str) -> bool:
    return value.isdigit() and len(value) >= 5


def _contains_identifier(text: str, identifier: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(identifier)}(?!\d)", text) is not None


def _is_catalog_phrase_match(text: str, variant: str) -> bool:
    tokens = [token for token in variant.split() if token not in _LEGAL_FORM_TOKENS]
    if len(tokens) < 2 and not _is_exact_identifier(variant):
        return False
    return _contains_phrase(text, variant) or _is_ordered_specific_phrase(text, variant)


def _is_ordered_specific_phrase(text: str, variant: str) -> bool:
    text_tokens = text.split()
    variant_tokens = variant.split()
    if len(text_tokens) < 3 or len(variant_tokens) < len(text_tokens):
        return False
    variant_idx = 0
    for token in text_tokens:
        found = False
        while variant_idx < len(variant_tokens):
            variant_token = variant_tokens[variant_idx]
            variant_idx += 1
            if variant_token == token or (len(token) == 1 and variant_token.startswith(token)):
                found = True
                break
        if not found:
            return False
    return True


_LEGAL_FORM_TOKENS = {"CONG", "TY", "CTY", "TNHH", "CP", "CO", "PHAN", "MTV", "JSC", "LTD"}
_GENERIC_SINGLE_TOKEN_VARIANTS = {
    "BAO",
    "BEST",
    "BLUE",
    "CITY",
    "CUOC",
    "DICH",
    "DUNG",
    "EAST",
    "FISH",
    "GOLD",
    "HANH",
    "HAI",
    "HOPE",
    "LANH",
    "LIME",
    "MART",
    "MUA",
    "PHI",
    "PHONG",
    "REAL",
    "RICH",
    "SON",
    "STEEL",
    "THANH",
    "THIEN",
    "THUE",
    "TIEN",
    "VAN",
    "VINA",
    "VIET",
    "VIETNAM",
    "VU",
    "WEST",
}
_SEARCH_STOP_TOKENS = _LEGAL_FORM_TOKENS | {
    "BANK",
    "BILL",
    "BUYING",
    "CHUYEN",
    "CHO",
    "CONG",
    "CONGNO",
    "DON",
    "GIAO",
    "HANG",
    "HOA",
    "KHOAN",
    "LEPHAM",
    "NOP",
    "PAYABLE",
    "PAYMENT",
    "REF",
    "SO",
    "TAI",
    "TAI KHOAN",
    "THANH",
    "THEO",
    "TIEN",
    "TOAN",
    "TRA",
}


def _is_weak_context_variant(variant: str, part: str, is_hint_part: bool) -> bool:
    variant_tokens = variant.split()
    part_tokens = part.split()
    if not variant_tokens or len(part_tokens) <= 1:
        return False

    significant_tokens = [token for token in variant_tokens if len(token) > 1 and token not in _LEGAL_FORM_TOKENS]
    if len(variant_tokens) == 1:
        token = variant_tokens[0]
        if part == token:
            return False
        return True

    if len(significant_tokens) == 1:
        token = significant_tokens[0]
        if is_hint_part and part == variant:
            return False
        return len(token) <= 2 or token in _GENERIC_SINGLE_TOKEN_VARIANTS

    return False


def _alias_matches_variant(alias: str, variant: str) -> bool:
    if not alias or not variant:
        return False
    if _is_exact_identifier(alias):
        return _contains_identifier(variant, alias)
    return _contains_phrase(variant, alias)


def _is_weak_alias(alias: str) -> bool:
    tokens = alias.split()
    compact = alias.replace(" ", "")
    if not compact:
        return True
    if compact.isdigit():
        return len(compact) < 5
    if any(char.isdigit() for char in compact):
        return True
    if len(tokens) <= 1:
        return len(compact) <= 4 or compact in _GENERIC_SINGLE_TOKEN_VARIANTS
    significant = [token for token in tokens if token not in _LEGAL_FORM_TOKENS and token not in _GENERIC_SINGLE_TOKEN_VARIANTS]
    return len(significant) < 2 and not any(char.isdigit() for char in compact)


_BLOCKED_SHORT_AUTO_ALIASES = {
    "HD",  # hoa don / hop dong appears in many payment descriptions.
    "TCT",  # tong cong ty / tong cuc thue, too broad as a standalone alias.
}


def _is_blocked_auto_alias(alias: str) -> bool:
    compact = alias.replace(" ", "")
    if not compact:
        return True
    if compact.isdigit():
        return len(compact) < 5
    if len(compact) <= 2:
        return True
    return compact in _BLOCKED_SHORT_AUTO_ALIASES


def _catalog_equivalence_key(obj: CatalogObject) -> str:
    return _candidate_equivalence_key(ObjectCandidate(code=obj.code, name=obj.name, score=0.0))


def _candidate_from_object(obj: CatalogObject, score: float, source: str, matched_on: str) -> ObjectCandidate:
    return ObjectCandidate(
        code=obj.code,
        name=obj.name,
        score=score,
        source=source,
        matched_on=matched_on,
        tax_code=obj.tax_code,
        group_name=obj.group_name,
        group_code=obj.group_code,
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_search_parts(values: list[_SearchPart]) -> list[_SearchPart]:
    result: list[_SearchPart] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not value.text:
            continue
        key = (value.text, value.source)
        if key in seen:
            continue
        result.append(value)
        seen.add(key)
    return result


def _merge_candidates(candidates: list[ObjectCandidate]) -> list[ObjectCandidate]:
    best_by_code: dict[str, ObjectCandidate] = {}
    for candidate in candidates:
        key = normalize_text(candidate.code)
        existing = best_by_code.get(key)
        if existing is None or _is_better_candidate(candidate, existing):
            best_by_code[key] = candidate
    best_by_equivalent_name: dict[str, ObjectCandidate] = {}
    for candidate in best_by_code.values():
        key = _candidate_equivalence_key(candidate)
        existing = best_by_equivalent_name.get(key)
        if existing is None or _is_better_candidate(candidate, existing):
            best_by_equivalent_name[key] = candidate
    merged = list(best_by_equivalent_name.values())
    merged.sort(key=_candidate_sort_key, reverse=True)
    return merged


_SOURCE_PRIORITY = {
    "exact_phrase": 6,
    "tax_code": 5,
    "alias_match": 4,
    "catalog_phrase": 3,
    "entity_match": 2,
    "fuzzy_name": 1,
}


def _candidate_sort_key(candidate: ObjectCandidate) -> tuple[float, int, int]:
    return (candidate.score, _SOURCE_PRIORITY.get(candidate.source, 0), len(normalize_text(candidate.matched_on)))


def _is_better_candidate(candidate: ObjectCandidate, existing: ObjectCandidate) -> bool:
    return _candidate_sort_key(candidate) > _candidate_sort_key(existing)


def _candidate_equivalence_key(candidate: ObjectCandidate) -> str:
    normalized_name = normalize_text(candidate.name)
    return normalized_name or normalize_text(candidate.code)
