from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .models import ExtractedEntities
from .normalizer import normalize_text


class OwnCompanyConfig:
    def __init__(self, aliases: list[str], tax_codes: list[str], object_codes: list[str]):
        self.aliases = list(dict.fromkeys(normalize_text(alias) for alias in aliases if normalize_text(alias)))
        self.tax_codes = list(dict.fromkeys(normalize_text(code) for code in tax_codes if normalize_text(code)))
        self.object_codes = list(dict.fromkeys(normalize_text(code) for code in object_codes if normalize_text(code)))

    @classmethod
    def from_yaml(cls, path: str | Path | None) -> "OwnCompanyConfig":
        if not path or not Path(path).exists():
            return cls([], [], [])
        with Path(path).open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        data = data.get("own_company", data)
        return cls(
            aliases=list(data.get("aliases", [])),
            tax_codes=list(data.get("tax_codes", [])),
            object_codes=list(data.get("object_codes", [])),
        )

    def is_own_code(self, code: str) -> bool:
        return normalize_text(code) in self.object_codes

    def is_own_tax_code(self, value: str) -> bool:
        return normalize_text(value) in self.tax_codes

    def is_own_name(self, value: str) -> bool:
        normalized = normalize_text(value)
        if not normalized:
            return False
        return any(_contains_phrase(normalized, alias) or alias in normalized for alias in self.aliases)

    def find_hits(self, value: str) -> list[str]:
        normalized = normalize_text(value)
        hits = [alias for alias in self.aliases if alias and (alias in normalized or _contains_phrase(normalized, alias))]
        hits.extend(code for code in self.tax_codes if code and code in normalized)
        return list(dict.fromkeys(hits))

    def strip_from_text(self, value: str) -> str:
        text = normalize_text(value)
        for alias in sorted(self.aliases, key=len, reverse=True):
            text = _remove_phrase(text, alias)
        for code in self.tax_codes:
            text = _remove_phrase(text, code)
        return re.sub(r"\s+", " ", text).strip()


class EntityExtractor:
    def __init__(self, own_company: OwnCompanyConfig):
        self.own_company = own_company

    def extract(self, bank: str, description: str, counterparty_raw: str = "") -> ExtractedEntities:
        normalized_description = normalize_text(description)
        normalized_counterparty = normalize_text(counterparty_raw)
        cleaned_description = self.own_company.strip_from_text(normalized_description)
        own_hits = self.own_company.find_hits(f"{description} {counterparty_raw}")

        intent = _detect_intent(cleaned_description)
        invoice_no = _extract_first(r"(?:HD|HOA DON|SO HD)\s*(?:SO)?\s*([A-Z0-9,\- ]{1,40})", cleaned_description)
        bill_no = _extract_first(r"(?:BILL|BL)\s*([A-Z0-9,\- ]{1,40})", cleaned_description)
        tax_code = _extract_first(r"(?:MST|MA SO THUE|TAX CODE)\s*(\d{8,14})", normalized_description)
        bank_account_hint = _extract_first(r"(?:CK 24 7 CHO|CHO)\s*(\d{6,20})", cleaned_description)
        service_hint = _extract_service(cleaned_description)
        declaration_no = _extract_declaration_no(normalized_description)
        loan_account = _extract_loan_account(normalized_description)
        vessel = _extract_vessel(normalized_description)
        cash_person_name, cash_person_source = _extract_cash_person_name(normalized_description, normalized_counterparty)

        counterparty_hint = ""
        counterparty_source = ""
        if bank == "MSB" and normalized_counterparty and not self.own_company.is_own_name(normalized_counterparty):
            counterparty_hint = _clean_counterparty_raw(normalized_counterparty)
            counterparty_source = "counterparty_raw"
        if not counterparty_hint:
            counterparty_hint, counterparty_source = _extract_counterparty_hint(cleaned_description)

        return ExtractedEntities(
            counterparty_hint=counterparty_hint,
            counterparty_source=counterparty_source,
            cash_person_name=cash_person_name,
            cash_person_source=cash_person_source,
            cleaned_description=cleaned_description,
            intent=intent,
            invoice_no=invoice_no,
            bill_no=bill_no,
            tax_code=tax_code,
            bank_account_hint=bank_account_hint,
            service_hint=service_hint,
            declaration_no=declaration_no,
            loan_account=loan_account,
            vessel=vessel,
            own_company_hits=own_hits,
        )


def _extract_counterparty_hint(text: str) -> tuple[str, str]:
    patterns = [
        ("ck_247_cho", r"CK 24 7 CHO\s+(?:\d{6,20}\s+)?(.+)"),
        ("tt_cho", r"TT\s+CHO\s+(.+)"),
        ("ct_cho", r"CT\s+CHO\s+(.+)"),
        ("tt_service_cho", r"TT\s+(.+?)\s+CHO\s+(.+)"),
        ("tt_cang", r"TT\s+CANG\s+(.+?)(?=\s+(?:TAU|ST|TG|GD)\b|$)"),
        ("thanh_toan_cho", r"THANH TOAN(?:\s+[A-Z0-9]+){0,8}\s+CHO\s+(.+)"),
        ("chuyen_tien_cho", r"CHUYEN TIEN(?:\s+[A-Z0-9]+){0,6}\s+CHO\s+(.+)"),
        ("thu_tien_tu", r"THU TIEN TU\s+(.+)"),
        ("co_so_before_chuyen_tien", r"^(CO SO\s+.{3,80}?)(?=\s+CHUYEN TIEN\b)"),
        ("cp_vietnam_corporation", r"\b(CP VIETNAM CORPORATION)\b"),
        ("english_company_prefix", r"^(.{3,100}?\b(?:COMPANY LIMITED|CO LTD|CORPORATION|COMPANY|LTD))(?=\s|$)"),
        ("company_start_before_purpose", r"^(?:CONG TY|CTY|CT)\s+([A-Z0-9]{2,80}?)(?=\s+(?:TAM UNG|THANH TOAN|TT|CHUYEN)\b)"),
        (
            "company_prefix_before_transfer",
            r"\b(?:(?:CONG TY|CTY|C TY)(?:\s+(?:TNHH|CP|CO PHAN))?|CT\s+(?:TNHH|CP))\s+(.{3,120}?)(?=\s+(?:CHUYEN KHOAN|CHUYEN TIEN|THANH TOAN|TT|TAM UNG|NOP)\b)",
        ),
        ("tt_phi_cang_vu", r"\bTT\s+PHI\s+(CANG\s+VU\s+.+?)(?=\s+(?:TAU|ST|SO|HD|GD)\b|$)"),
        ("cho", r"\bCHO\s+(.+)"),
        (
            "company_prefix",
            r"\b(?:(?:CONG TY|CTY|C TY)(?:\s+(?:TNHH|CP|CO PHAN))?|CT\s+(?:TNHH|CP))\s+(.{3,100}?)(?=\s+(?:TT|THANH TOAN|NOP|CHUYEN|CK|PAYMENT|PAY|TAX CODE|MST|MA SO THUE|GD|TAI)\b|\s+\d{8,14}\b|$)",
        ),
        (
            "compact_company_prefix",
            r"\bCTY([A-Z0-9]{3,80}?)(?=\s+(?:TT|THANH TOAN|NOP|CHUYEN|CK|PAYMENT|PAY|TAX CODE|MST|MA SO THUE|GD|TAI|BILL|BL|STSTMSHP[0-9]*)\b|\s+\d{8,14}\b|$)",
        ),
        ("name_before_tax_code", r"^(.{3,80}?)\s+(?:TAX CODE|MST|MA SO THUE)\b"),
    ]
    for source, pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        hint_value = match.group(2) if source == "tt_service_cho" and match.lastindex and match.lastindex >= 2 else match.group(1)
        hint = _clean_counterparty_segment(hint_value)
        if hint:
            return hint, source
    return "", ""


def _clean_counterparty_segment(segment: str) -> str:
    segment = re.sub(r"^\d{6,20}\s+", "", segment).strip()
    if re.search(r"\bCP VIETNAM CORPORATION\b", segment):
        return "CP VIETNAM CORPORATION"
    if re.search(r"\bTCL SMART DEVICE VIET NAM COMPANY LIMITED\b", segment):
        return "TCL SMART DEVICE VIET NAM"
    if " CHO " in segment:
        segment = segment.rsplit(" CHO ", 1)[-1].strip()
    segment = _cut_counterparty_noise(segment)
    segment = re.sub(r"HD\s*\d+.*$", "", segment).strip()
    stop_pattern = (
        r"\b(?:THEO|HD|HOA DON|SO HD|BANG KE|BILL|BL|KY HOA DON|TAU|LAN|MST|MA SO THUE"
        r"|TAM UNG|UNG TIEN|THANH TOAN|CHUYEN TIEN|CHUYEN KHOAN|PAYMENT|PHI CAP LENH|LAY LENH"
        r"|PHI DO|PHI D O|PHI DICH VU|PHI DAI LY|PHI CANG VU|PHI LAM TAU|CONG NO)\b|\bTHANG\s+\d"
    )
    segment = re.split(stop_pattern, segment, maxsplit=1)[0]
    segment = re.sub(
        r"\b(?:DICH VU VAN TAI BIEN|DICH VU VAN TAI|THUONG MAI VA VAN TAI|THUONG MAI|VAN TAI BIEN|VAN TAI|DICH VU)\b",
        " ",
        segment,
    )
    segment = re.sub(r"\b(CTY|CT|CONG TY|TNHH|CO PHAN|CP|COMPANY|LIMITED|LTD|JSC|CORPORATION)\b", " ", segment)
    segment = re.sub(r"[^A-Z0-9]+", " ", segment)
    tokens = [token for token in segment.split() if token not in {"CUOC", "PHI", "DICH"}]
    if _looks_like_own_branch_segment(tokens):
        return ""
    return " ".join(tokens[:6]).strip()


def _clean_counterparty_raw(segment: str) -> str:
    segment = re.sub(r"^\d{6,20}\s+", "", segment).strip()
    segment = _cut_counterparty_noise(segment)
    segment = re.sub(
        r"\b(THUONG MAI VA VAN TAI|VAN TAI TM VA DV|TM VA VAN TAI|TM VA DV|TM DV|DICH VU|VAN TAI)\b",
        " ",
        segment,
    )
    segment = re.sub(r"\b(CN|CTY|CT|CONG TY|TNHH|CO PHAN|CP|MTV|COMPANY|LIMITED|LTD|JSC)\b", " ", segment)
    segment = re.sub(r"[^A-Z0-9]+", " ", segment)
    tokens = [token for token in segment.split() if token not in {"VA"}]
    return " ".join(tokens[:10]).strip()


def _extract_cash_person_name(description: str, counterparty_raw: str = "") -> tuple[str, str]:
    raw_person = _clean_person_name(counterparty_raw)
    if raw_person:
        return raw_person, "counterparty_raw"

    patterns = [
        ("acb_cash_marker", r"^([A-Z ]{5,60}?)\s+\d{6,20}\s+(?:CHI SEC|NT)\b"),
        ("person_before_cash_marker", r"^([A-Z ]{5,60}?)(?=\s+(?:CHI SEC|RUT TIEN MAT|RUT TM|NOP TIEN MAT|NOP TM|NT)\b)"),
        ("cash_person_label", r"\b(?:NGUOI NHAN|NGUOI NOP|NGUOI RUT|TEN NGUOI NHAN|TEN NGUOI NOP)\s*:?\s*([A-Z ]{5,60})"),
    ]
    for source, pattern in patterns:
        match = re.search(pattern, description)
        if not match:
            continue
        person = _clean_person_name(match.group(1))
        if person:
            return person, source
    return "", ""


def _clean_person_name(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    value = _cut_counterparty_noise(value)
    value = re.split(r"[\#;\-\.,/\[\]\(\)]", value, maxsplit=1)[0]
    value = re.sub(r"[^A-Z ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    tokens = value.split()
    if not _looks_like_person_name(tokens):
        return ""
    return " ".join(tokens[:6])


def _looks_like_person_name(tokens: list[str]) -> bool:
    if not 2 <= len(tokens) <= 6:
        return False
    if any(token in _NON_PERSON_NAME_TOKENS for token in tokens):
        return False
    return tokens[0] in _VIETNAMESE_FAMILY_NAMES


def _cut_counterparty_noise(segment: str) -> str:
    noise_pattern = (
        r"\b(?:GD|NHTMCP|TAX CODE|MST|MA SO THUE)\b"
        r"|\["
        r"|\b\d{6}\b(?:\s+\d{2}\b){0,3}"
        r"|\b(?=[A-Z0-9]*\d)[A-Z0-9]{10,}\b"
    )
    return re.split(noise_pattern, segment, maxsplit=1)[0].strip()


def _looks_like_own_branch_segment(tokens: list[str]) -> bool:
    if len(tokens) < 2 or tokens[:2] != ["VAN", "PHONG"]:
        return False
    return any(token in {"HAI", "PHONG", "HAIPHONG", "HN", "HCM", "HOCHIMINH"} for token in tokens[2:])


def _detect_intent(text: str) -> str:
    for intent in ["NOP THUE", "THANH TOAN", "TT CHO", "CHUYEN TIEN", "TAM UNG", "TRA LUONG", "LAI NHAP VON"]:
        if intent in text:
            return intent
    return ""


def _extract_service(text: str) -> str:
    for pattern in [
        r"THANH TOAN\s+(.+?)\s+CHO\s+",
        r"TT\s+(.+?)\s+CHO\s+",
    ]:
        match = re.search(pattern, text)
        if match:
            return _clean_counterparty_segment(match.group(1))
    return ""


def _extract_declaration_no(text: str) -> str:
    return _extract_first(r"\bTK\s*(\d{10,11})\b", text)


def _extract_loan_account(text: str) -> str:
    patterns = [
        r"\bTK\s+VAY\s+00\s+(\d{3,4})\b",
        r"\bTK\s+VAY\s+(?:00)?(\d{6,20})\b",
        r"\bTKV\s+(\d{6,20})\b",
    ]
    for pattern in patterns:
        value = _extract_first(pattern, text)
        if value:
            return f"00...{value[-4:]}"
    return ""


def _extract_vessel(text: str) -> str:
    for pattern in [
        r"\bTIEN\s+TAU\s+([A-Z][A-Z0-9 ]{1,60}?)(?=\s+(?:CHO|CUA|TAI|ST|SO|HD|GD|TG|BL|BILL|THEO|REF)\b|\s+\d{4,}\b|$)",
        r"\b(?:TAU|MV|M V)\s+([A-Z][A-Z0-9 ]{1,60}?)(?=\s+(?:ST|SO|HD|GD|TG|BL|BILL|THEO|REF)\b|\s+\d{4,}\b|$)",
    ]:
        value = _extract_first(pattern, text)
        if value:
            value = re.sub(r"\b(?:ST|SO|HD|GD|TG|BL|BILL|THEO|REF)\b.*$", "", value).strip()
            return re.sub(r"\s+", " ", value)
    return ""


def _extract_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(re.escape(token) for token in phrase.split()) + r"(?![A-Z0-9])"
    return re.search(pattern, text) is not None


def _remove_phrase(text: str, phrase: str) -> str:
    if not phrase:
        return text
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(re.escape(token) for token in phrase.split()) + r"(?![A-Z0-9])"
    text = re.sub(pattern, " ", text)
    text = text.replace(phrase, " ")
    return re.sub(r"\s+", " ", text).strip()


_VIETNAMESE_FAMILY_NAMES = {
    "BUI",
    "CAO",
    "CHAU",
    "CHU",
    "DAO",
    "DANG",
    "DINH",
    "DO",
    "DUONG",
    "HA",
    "HO",
    "HOANG",
    "HUYNH",
    "KIEU",
    "LA",
    "LAM",
    "LE",
    "LUONG",
    "LY",
    "MAC",
    "MAI",
    "NGO",
    "NGUYEN",
    "PHAM",
    "PHAN",
    "QUACH",
    "TA",
    "THAI",
    "TO",
    "TON",
    "TRAN",
    "TRINH",
    "TRUONG",
    "VU",
    "VO",
}

_NON_PERSON_NAME_TOKENS = {
    "CASH",
    "CHI",
    "CONG",
    "CO",
    "CP",
    "CT",
    "CTY",
    "GIAO",
    "HANG",
    "KHACH",
    "MAT",
    "NGAN",
    "NHAP",
    "NOP",
    "PHI",
    "QUY",
    "RUT",
    "SEC",
    "TAI",
    "TIEN",
    "TK",
    "TM",
    "TNHH",
    "TY",
}

