from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .normalizer import normalize_text


@dataclass(frozen=True)
class ReasonPurpose:
    code: str
    label: str
    aliases: tuple[str, ...]


_BLOCKED_ALIASES = {
    "TT",
    "THANH TOAN",
    "THANH TOAN TIEN",
    "THU",
    "THU TIEN",
    "PHI",
    "TIEN",
    "CUOC",
    "HD",
    "HOA DON",
    "CONG NO",
}


def load_reason_purposes(path: str | Path | None) -> list[ReasonPurpose]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:  # noqa: BLE001 - invalid config should not stop RPA fallback.
        return []

    purposes: list[ReasonPurpose] = []
    for item in data.get("purposes", []) or []:
        purpose = _purpose_from_dict(item)
        if purpose:
            purposes.append(purpose)
    return purposes


def load_object_purpose_defaults(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:  # noqa: BLE001 - invalid config should not stop RPA fallback.
        return {}

    defaults: dict[str, str] = {}
    for object_code, purpose_code in (data.get("object_purpose_defaults", {}) or {}).items():
        key = normalize_text(object_code)
        value = str(purpose_code or "").strip()
        if key and value:
            defaults[key] = value
    return defaults


def load_object_name_purposes(path: str | Path | None) -> list[tuple[str, str]]:
    """Luật suy nghiệp vụ theo LOẠI đối tượng: [(keyword_normalized, purpose_code)]."""
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:  # noqa: BLE001 - invalid config should not stop RPA fallback.
        return []

    rules: list[tuple[str, str]] = []
    for item in data.get("object_name_purposes", []) or []:
        if not isinstance(item, dict):
            continue
        keyword = normalize_text(item.get("keyword", ""))
        purpose_code = str(item.get("purpose", "") or "").strip()
        if keyword and purpose_code:
            rules.append((keyword, purpose_code))
    # Ưu tiên keyword dài hơn (cụ thể hơn) khi có nhiều luật cùng khớp.
    rules.sort(key=lambda rule: len(rule[0]), reverse=True)
    return rules


def match_object_name_purpose(name: Any, rules: list[tuple[str, str]] | None) -> str:
    """Trả về purpose_code nếu TÊN đối tượng chứa từ khoá loại hình, ngược lại ''."""
    if not rules:
        return ""
    normalized = normalize_text(name)
    if not normalized:
        return ""
    for keyword, purpose_code in rules:
        if keyword in normalized:
            return purpose_code
    return ""


def match_reason_purpose(text: Any, purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None) -> ReasonPurpose | None:
    normalized = normalize_text(text)
    if not normalized or not purposes:
        return None

    best_purpose: ReasonPurpose | None = None
    best_alias = ""
    for purpose in purposes:
        for alias in purpose.aliases:
            if len(alias) <= len(best_alias):
                continue
            if _contains_phrase(normalized, alias):
                best_purpose = purpose
                best_alias = alias
    return best_purpose


def _purpose_from_dict(item: Any) -> ReasonPurpose | None:
    if not isinstance(item, dict):
        return None
    code = str(item.get("code", "") or "").strip()
    label = str(item.get("label", "") or "").strip()
    if not code or not label:
        return None

    aliases: list[str] = []
    for alias in list(item.get("aliases", []) or []) + [label]:
        normalized = normalize_text(alias)
        if normalized and normalized not in _BLOCKED_ALIASES:
            aliases.append(normalized)
    aliases = sorted(dict.fromkeys(aliases), key=len, reverse=True)
    if not aliases:
        return None
    return ReasonPurpose(code=code, label=label, aliases=tuple(aliases))


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(re.escape(token) for token in phrase.split()) + r"(?![A-Z0-9])"
    return re.search(pattern, text) is not None
