from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .models import Rule
from .normalizer import parse_amount


DEFAULT_CONFIG: dict[str, Any] = {
    "bank_accounts": {"VCB": "1121VCB", "ACB": "1121CT", "MSB": "1121HB"},
    "bank_object_codes": {"VCB": "VCB", "ACB": "ACB", "MSB": "MSBHB"},
    "foreign_currency_accounts": {"VCB": "1122VCB", "ACB": "1122ACB", "MSB": "1122HB"},
    "matching": {"min_score": 80, "min_gap": 8},
    "output": {
        "date_format": "%d/%m/%Y",
        "excel_file": "rpa_input.xlsx",
        "summary_file": "rpa_summary.xlsx",
        "object_match_review_file": "object_match_review.xlsx",
        "rpa_reason_encoding": "",
    },
    "rules": {"default_rules_file": "config/default_rules.yaml"},
    "own_company_file": "config/own_company.yaml",
    "object_aliases_file": "config/object_aliases.yaml",
    "object_overrides_file": "config/object_overrides.yaml",
    "reason_aliases_file": "config/reason_aliases.yaml",
    "internal_objects_file": "input/MA NOI BO CTY.xlsx",
    "historical_memory": {
        "enabled": True,
        "file": "input/thong_ke.xlsx",
        "min_unique_similarity": 35,
        "min_ambiguous_similarity": 70,
        "min_ambiguous_gap": 8,
    },
}


def load_config(path: str | Path) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    path = Path(path)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        config = _deep_merge(config, loaded)
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_rules(
    rules_path: str | Path | None,
    default_rules_path: str | Path,
    logger: logging.Logger | None = None,
) -> tuple[list[Rule], str]:
    logger = logger or logging.getLogger(__name__)
    if rules_path:
        logger.info("Ignoring Excel rules path and using default YAML rules: %s", rules_path)

    default_rules_path = Path(default_rules_path)
    rules = _load_rules_from_yaml(default_rules_path)
    logger.info("Using default YAML rules: %s", default_rules_path)
    return rules, str(default_rules_path)


def _load_rules_from_yaml(path: Path) -> list[Rule]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [_rule_from_dict(item) for item in data.get("rules", [])]


def _rule_from_dict(item: dict[str, Any]) -> Rule:
    return Rule(
        flow=str(item.get("flow", "")).strip(),
        use_case=str(item.get("use_case", "")).strip(),
        account=str(item.get("account", "")).strip(),
        bank_scope=[str(bank).upper() for bank in item.get("bank_scope", [])],
        include_keywords=[str(keyword) for keyword in item.get("include_keywords", [])],
        context_keywords=[str(keyword) for keyword in item.get("context_keywords", [])],
        exclude_keywords=[str(keyword) for keyword in item.get("exclude_keywords", [])],
        auto_process=bool(item.get("auto_process", True)),
        priority=int(item.get("priority", 999)),
        requires_object=bool(item.get("requires_object", False)),
        object_catalog=str(item.get("object_catalog", "none") or "none"),
        error_note=str(item.get("error_note", "") or ""),
        context_required=bool(item.get("context_required", False)),
        rule_id=str(item.get("rule_id", "") or ""),
        direction=str(item.get("direction", "") or ""),
        reason_template=str(item.get("reason_template", "") or ""),
        amount_equals=_optional_amount(item.get("amount_equals")),
        forced_object_code=str(item.get("forced_object_code", "") or "").strip(),
        default_object_code=str(item.get("default_object_code", "") or "").strip(),
        default_object_from_bank=bool(item.get("default_object_from_bank", False)),
        account_from_foreign_currency_bank=bool(item.get("account_from_foreign_currency_bank", False)),
    )


def _optional_amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    amount = parse_amount(value)
    return amount if amount > 0 else None

