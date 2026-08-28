from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CatalogObject
from .normalizer import normalize_text


def load_object_overrides(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        "receivable": _catalog_overrides(data.get("receivable", {})),
        "payable": _catalog_overrides(data.get("payable", {})),
        "internal": _catalog_overrides(data.get("internal", {})),
    }


def _catalog_overrides(data: dict[str, Any]) -> dict[str, Any]:
    supplemental_objects: list[CatalogObject] = []
    aliases: dict[str, list[str]] = {}
    exact_phrases: dict[str, str] = {}
    disabled_object_codes = {
        normalize_text(code)
        for code in data.get("disabled_object_codes", []) or []
        if normalize_text(code)
    }

    for record in data.get("supplemental_objects", []) or []:
        code = str(record.get("code", "") or "").strip()
        name = str(record.get("name", "") or "").strip()
        if not code or not name:
            continue
        supplemental_objects.append(
            CatalogObject(
                code=code,
                name=name,
                tax_code=str(record.get("tax_code", "") or "").strip(),
                group_name=str(record.get("group_name", "") or "").strip(),
                group_code=str(record.get("group_code", "") or "").strip(),
            )
        )
        record_aliases = [normalize_text(alias) for alias in record.get("aliases", []) or [] if normalize_text(alias)]
        if record_aliases:
            aliases.setdefault(code, []).extend(record_aliases)
        record_phrases = [str(phrase) for phrase in record.get("exact_phrases", []) or [] if str(phrase or "").strip()]
        for phrase in record_phrases:
            exact_phrases[normalize_text(phrase)] = code

    for code, values in (data.get("aliases", {}) or {}).items():
        aliases.setdefault(str(code), []).extend(normalize_text(value) for value in values or [] if normalize_text(value))

    for phrase, code in (data.get("exact_phrases", {}) or {}).items():
        phrase_norm = normalize_text(phrase)
        if phrase_norm and str(code or "").strip():
            exact_phrases[phrase_norm] = str(code).strip()

    return {
        "supplemental_objects": supplemental_objects,
        "aliases": {code: list(dict.fromkeys(values)) for code, values in aliases.items()},
        "exact_phrases": exact_phrases,
        "disabled_object_codes": disabled_object_codes,
    }
