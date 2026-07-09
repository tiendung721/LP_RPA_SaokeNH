from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.normalizer import normalize_text, parse_amount  # noqa: E402
from src.reason_aliases import (  # noqa: E402
    ReasonPurpose,
    load_object_name_purposes,
    load_object_purpose_defaults,
    load_reason_purposes,
    match_reason_purpose,
)


DEFAULT_INPUT = PROJECT_ROOT / "input" / "thong_ke.xlsx"
DEFAULT_REASON_CONFIG = PROJECT_ROOT / "config" / "reason_aliases.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "reason_mining"

GOODS_PURPOSE_CODES = {"goods"}
MIN_COUNT = 5
MIN_SHARE = 0.75

OBJECT_NAME_KEYWORD_CANDIDATES: dict[str, str] = {
    "CANG VU HANG HAI": "port_authority_fee",
    "HOA TIEU": "pilotage_fee",
    "KIEM DICH": "quarantine_fee",
    "KIEM SOAT BENH TAT": "quarantine_fee",
    "CUC HAI QUAN": "customs_fee",
    "DANG KIEM": "inspection_fee",
    "BUU DIEN": "courier_charge",
    "CANG QUOC TE": "port_charges",
    "VINACONTROL": "survey_fee",
    "VINMEC": "crew_medical_fee",
    "KHACH SAN": "hotel_fee",
    "DU LICH": "hotel_fee",
    "VIEN THONG": "telecom_charge",
    "DIEN LUC": "electricity",
    "CAP NUOC": "water",
}

# Lý do mang tính kho quỹ/nội bộ/ngân hàng: KHÔNG nâng thành nghiệp vụ 331/131.
_TREASURY_REASON_TOKENS = (
    "CHUYEN TIEN TAI KHOAN",
    "CHUYEN TAI KHOAN",
    "CHUYEN KHOAN",
    "CHUYEN TK",
    "BAN NGOAI TE",
    "MUA NGOAI TE",
    "LAI TIEN GUI",
    "LAI NHAP VON",
    "NHAP QUY",
    "RUT TIEN",
    "TAI KHOAN VAY",
    "TAT TOAN",
    "KI QUY",
    "KY QUY",
    "TAM UNG",
    "UNG TIEN",
    "HOAN TRA TAM UNG",
    "HOAN TRA TIEN VAY",
    "CHO VAY",
    "THU HOI",
    "GOP VON",
    "KIEU HOI",
    "PHONG TOA",
)
_BANK_NAME_TOKENS = ("NGAN HANG", "BANK")
# Dấu hiệu lý do thực chất chỉ nhắc lại TÊN đối tượng ("Thu tiền Công ty ...") -> không phải nghiệp vụ.
_COMPANY_MARKERS = ("CONG TY", "CTY", "TNHH", "CO PHAN", "DNTN", "DOANH NGHIEP", "TAP DOAN")
_REASON_LEAD_VERBS = r"^(?:TT|THANH TOAN|THU TIEN|THU|NOP TIEN|NOP|CHI TIEN|CHI)\b\s*"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    reason_config = Path(args.reason_config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    purposes = load_reason_purposes(reason_config)
    object_defaults = load_object_purpose_defaults(reason_config)
    object_name_rules = load_object_name_purposes(reason_config)

    stats_df = read_reason_stats(input_path)
    enriched = enrich_reason_stats(stats_df, purposes)

    existing_codes = {purpose.code for purpose in purposes}
    known_default_candidates, new_purpose_default_candidates, reason_bundles = mine_object_defaults(
        enriched,
        object_defaults,
        object_name_rules,
        existing_codes,
        args.min_count,
        args.min_share,
    )
    purpose_candidates = mine_new_purpose_candidates(
        enriched,
        purposes,
        args.min_count,
        existing_codes=existing_codes,
        exclude_reason_norms=set(reason_bundles.keys()),
    )
    object_name_candidates = mine_object_name_purpose_candidates(
        enriched,
        object_name_rules,
        args.min_count,
        args.min_share,
    )

    report_path = output_dir / "reason_aliases_mining_report.xlsx"
    yaml_path = output_dir / "reason_aliases_suggestions.yaml"
    write_report(
        report_path,
        purpose_candidates,
        object_name_candidates,
        known_default_candidates,
        new_purpose_default_candidates,
        args,
        input_path,
        reason_config,
    )
    write_yaml_suggestions(
        yaml_path,
        purpose_candidates,
        object_name_candidates,
        known_default_candidates,
        new_purpose_default_candidates,
        reason_bundles,
    )
    print(f"Wrote report: {report_path}")
    print(f"Wrote suggestions: {yaml_path}")
    print(
        "Candidates:",
        f"purposes={len(purpose_candidates)}",
        f"object_name_purposes={len(object_name_candidates)}",
        f"object_defaults_known={len(known_default_candidates)}",
        f"object_defaults_new_purpose={len(new_purpose_default_candidates)}",
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine reason alias suggestions from thong_ke.xlsx without editing config.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to thong_ke workbook")
    parser.add_argument("--reason-config", default=str(DEFAULT_REASON_CONFIG), help="Current reason_aliases.yaml")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for report files")
    parser.add_argument("--min-count", type=int, default=MIN_COUNT, help="Minimum support count")
    parser.add_argument("--min-share", type=float, default=MIN_SHARE, help="Minimum dominant-purpose share")
    return parser.parse_args()


def read_reason_stats(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    excel = pd.ExcelFile(path)
    for sheet_name in excel.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
        df = df.where(pd.notna(df), "")
        columns = {normalize_text(column): column for column in df.columns}
        if {"MA DT", "LY DO DIEN GIAI", "SO LAN"}.issubset(columns):
            rename = {
                columns["MA DT"]: "object_code",
                columns.get("TEN DT", "Tên ĐT"): "object_name",
                columns.get("NHOM DT", "Nhóm ĐT"): "object_group",
                columns["LY DO DIEN GIAI"]: "reason",
                columns["SO LAN"]: "count",
                columns.get("NGUON DU LIEU", "Nguồn dữ liệu"): "source",
            }
            # Cột số lần theo nguồn (nếu có) để ưu tiên lý do đã được RPA thật xác nhận.
            if "RPA INPUT" in columns:
                rename[columns["RPA INPUT"]] = "rpa_input"
            if "RPA EXCEPTION" in columns:
                rename[columns["RPA EXCEPTION"]] = "rpa_exception"
            return df.rename(columns=rename)
    raise ValueError("Cannot find a sheet with columns: Mã ĐT, Lý do/diễn giải, Số lần")


def enrich_reason_stats(df: pd.DataFrame, purposes: list[ReasonPurpose]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in df.to_dict("records"):
        reason = str(record.get("reason", "") or "").strip()
        count = int(parse_amount(record.get("count", 0)) or 0)
        if not reason or count <= 0:
            continue
        matched = match_reason_purpose(reason, purposes)
        rows.append(
            {
                "object_code": str(record.get("object_code", "") or "").strip(),
                "object_name": str(record.get("object_name", "") or "").strip(),
                "object_group": str(record.get("object_group", "") or "").strip(),
                "reason": reason,
                "reason_norm": normalize_text(reason),
                "count": count,
                "source": str(record.get("source", "") or "").strip(),
                "rpa_support": int(parse_amount(record.get("rpa_input", 0)) or 0)
                + int(parse_amount(record.get("rpa_exception", 0)) or 0),
                "matched_purpose": matched.code if matched else "",
            }
        )
    return pd.DataFrame(rows)


def mine_new_purpose_candidates(
    df: pd.DataFrame,
    purposes: list[ReasonPurpose],
    min_count: int,
    existing_codes: set[str] | None = None,
    exclude_reason_norms: set[str] | None = None,
) -> list[dict[str, Any]]:
    if existing_codes is None:
        existing_codes = {purpose.code for purpose in purposes}
    exclude_reason_norms = exclude_reason_norms or set()
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
    grouped = df[df["matched_purpose"] == ""].groupby(["reason_norm", "reason"], dropna=False)["count"].sum().reset_index()
    for record in grouped.sort_values("count", ascending=False).to_dict("records"):
        reason_norm = str(record["reason_norm"])
        count = int(record["count"])
        if count < min_count or _looks_like_goods(reason_norm) or reason_norm in exclude_reason_norms:
            continue
        code = _purpose_code_from_reason(reason_norm)
        rows.append(
            {
                "suggested_code": _dedupe_code(code, existing_codes),
                "label": _label_from_reason(record["reason"]),
                "alias": reason_norm,
                "count": count,
                "review_note": "Review label/code before copying to purposes.",
            }
        )
    return rows


def mine_object_name_purpose_candidates(
    df: pd.DataFrame,
    existing_rules: list[tuple[str, str]],
    min_count: int,
    min_share: float,
) -> list[dict[str, Any]]:
    existing_keywords = {keyword for keyword, _ in existing_rules}
    rows: list[dict[str, Any]] = []
    matched_df = df[df["matched_purpose"] != ""]
    for keyword, purpose in OBJECT_NAME_KEYWORD_CANDIDATES.items():
        keyword_norm = normalize_text(keyword)
        if keyword_norm in existing_keywords:
            continue
        subset = matched_df[matched_df["object_name"].map(lambda value: keyword_norm in normalize_text(value))]
        if subset.empty:
            continue
        total = int(subset["count"].sum())
        purpose_total = int(subset[subset["matched_purpose"] == purpose]["count"].sum())
        share = purpose_total / total if total else 0
        if purpose_total >= min_count and share >= min_share:
            rows.append(
                {
                    "keyword": keyword_norm,
                    "purpose": purpose,
                    "count": purpose_total,
                    "total_for_keyword": total,
                    "share": round(share, 4),
                    "sample_objects": _sample_values(subset["object_name"]),
                }
            )
    rows.sort(key=lambda row: (-row["count"], row["keyword"]))
    return rows


def mine_object_defaults(
    df: pd.DataFrame,
    existing_defaults: dict[str, str],
    object_name_rules: list[tuple[str, str]],
    existing_codes: set[str],
    min_count: int,
    min_share: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Suy nghiệp vụ mặc định cho từng Mã ĐT từ nghiệp vụ chủ đạo trong lịch sử.

    Một lần quét, phân đôi theo bản chất của "bucket" áp đảo (mỗi nghiệp vụ đã có
    là 1 bucket; mỗi lý do CHƯA có nghiệp vụ tính theo `reason_norm` là 1 bucket riêng):

      * ``known`` – bucket áp đảo là nghiệp vụ ĐÃ có trong catalog -> default trỏ purpose sẵn có.
      * ``new_purpose`` – bucket áp đảo là lý do CHƯA có nghiệp vụ -> đề xuất purpose MỚI + default
        (gỡ nghẽn con-gà-quả-trứng: trước đây default chỉ sinh cho nghiệp vụ đã tồn tại).
      * ``bundles`` – ``reason_norm -> {code,label,alias}``: nhiều Mã ĐT cùng một lý do dùng chung 1 code.

    Hai nhóm loại trừ lẫn nhau vì cùng xét trên bucket áp đảo tổng thể của mỗi Mã ĐT.
    """
    known_rows: list[dict[str, Any]] = []
    new_purpose_rows: list[dict[str, Any]] = []
    bundles: dict[str, dict[str, str]] = {}
    if df.empty:
        return known_rows, new_purpose_rows, bundles
    for object_code, group in df.groupby("object_code", dropna=False):
        code_norm = normalize_text(object_code)
        if not code_norm or code_norm in existing_defaults:
            continue
        total = int(group["count"].sum())
        if total <= 0:
            continue

        buckets: collections.Counter = collections.Counter()
        rpa_by_reason: collections.Counter = collections.Counter()
        raw_by_reason: dict[str, str] = {}
        for record in group.to_dict("records"):
            count = int(record["count"])
            matched = str(record.get("matched_purpose", "") or "")
            if matched:
                buckets[("purpose", matched)] += count
                continue
            reason_norm = str(record.get("reason_norm", "") or "")
            if not reason_norm:
                continue
            buckets[("reason", reason_norm)] += count
            rpa_by_reason[reason_norm] += int(record.get("rpa_support", 0) or 0)
            raw_by_reason.setdefault(reason_norm, str(record.get("reason", "") or ""))
        if not buckets:
            continue

        (kind, key), top_count = buckets.most_common(1)[0]
        share = top_count / total if total else 0
        object_name = str(group["object_name"].iloc[0] or "")

        if kind == "purpose":
            if (
                top_count < min_count
                or share < min_share
                or key in GOODS_PURPOSE_CODES
                or _object_name_already_explains_purpose(object_name, key, object_name_rules)
            ):
                continue
            known_rows.append(
                {
                    "object_code": object_code,
                    "object_name": object_name,
                    "suggested_purpose": key,
                    "count": top_count,
                    "total_for_object": total,
                    "share": round(share, 4),
                    "top_reasons": _top_reasons(group),
                    "source": _sample_values(group["source"], limit=3),
                }
            )
            continue

        # kind == "reason": nghiệp vụ chưa có trong catalog.
        reason_norm = key
        if _looks_like_goods(reason_norm) or _is_treasury_or_bank(object_name, reason_norm):
            continue
        if _reason_is_counterparty_echo(reason_norm, object_name):
            continue
        rpa_support = int(rpa_by_reason[reason_norm])
        # Lịch sử nhất quán tuyệt đối (share≈1) hoặc được RPA thật xác nhận -> hạ ngưỡng support.
        effective_min = min_count
        if share >= 0.999:
            effective_min = max(2, min_count // 2)
        if rpa_support > 0:
            effective_min = min(effective_min, 3)
        if top_count < effective_min or share < min_share:
            continue

        if reason_norm not in bundles:
            code = _dedupe_code(_purpose_code_from_reason(reason_norm), existing_codes)
            bundles[reason_norm] = {
                "code": code,
                "label": _label_from_reason(raw_by_reason.get(reason_norm, "")),
                "alias": reason_norm,
            }
        new_purpose_rows.append(
            {
                "object_code": object_code,
                "object_name": object_name,
                "dominant_reason": raw_by_reason.get(reason_norm, ""),
                "suggested_purpose": bundles[reason_norm]["code"],
                "suggested_label": bundles[reason_norm]["label"],
                "count": top_count,
                "total_for_object": total,
                "share": round(share, 4),
                "rpa_support": rpa_support,
            }
        )
    known_rows.sort(key=lambda row: (-row["count"], row["object_code"]))
    new_purpose_rows.sort(key=lambda row: (-row["count"], row["object_code"]))
    return known_rows, new_purpose_rows, bundles


def write_report(
    path: Path,
    purpose_candidates: list[dict[str, Any]],
    object_name_candidates: list[dict[str, Any]],
    known_default_candidates: list[dict[str, Any]],
    new_purpose_default_candidates: list[dict[str, Any]],
    args: argparse.Namespace,
    input_path: Path,
    reason_config: Path,
) -> None:
    params = pd.DataFrame(
        [
            {"key": "input", "value": str(input_path)},
            {"key": "reason_config", "value": str(reason_config)},
            {"key": "min_count", "value": args.min_count},
            {"key": "min_share", "value": args.min_share},
            {"key": "note", "value": "Report-only. Review suggestions before editing config/reason_aliases.yaml."},
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(purpose_candidates).to_excel(writer, sheet_name="PURPOSE_CANDIDATES", index=False)
        pd.DataFrame(object_name_candidates).to_excel(writer, sheet_name="OBJECT_NAME_PURPOSES", index=False)
        pd.DataFrame(known_default_candidates).to_excel(writer, sheet_name="OBJECT_DEFAULTS", index=False)
        pd.DataFrame(new_purpose_default_candidates).to_excel(writer, sheet_name="OBJECT_DEFAULTS_NEW", index=False)
        params.to_excel(writer, sheet_name="PARAMETERS", index=False)


def write_yaml_suggestions(
    path: Path,
    purpose_candidates: list[dict[str, Any]],
    object_name_candidates: list[dict[str, Any]],
    known_default_candidates: list[dict[str, Any]],
    new_purpose_default_candidates: list[dict[str, Any]],
    reason_bundles: dict[str, dict[str, str]],
) -> None:
    # Purpose mới của Nhóm B đứng trước để default trỏ vào chắc chắn tồn tại; dedupe theo code.
    purposes_out: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    candidate_purposes = [
        {"code": bundle["code"], "label": bundle["label"], "aliases": [bundle["alias"]]}
        for bundle in reason_bundles.values()
    ] + [
        {"code": row["suggested_code"], "label": row["label"], "aliases": [row["alias"]]}
        for row in purpose_candidates
    ]
    for item in candidate_purposes:
        if item["code"] in seen_codes:
            continue
        seen_codes.add(item["code"])
        purposes_out.append(item)

    # Nhóm A trỏ purpose sẵn có trong config; Nhóm B trỏ purpose mới ở trên.
    defaults_out: dict[str, str] = {}
    for row in known_default_candidates:
        defaults_out[row["object_code"]] = row["suggested_purpose"]
    for row in new_purpose_default_candidates:
        defaults_out[row["object_code"]] = row["suggested_purpose"]

    data = {
        "purposes": purposes_out,
        "object_name_purposes": [
            {"keyword": row["keyword"], "purpose": row["purpose"]}
            for row in object_name_candidates
        ],
        "object_purpose_defaults": defaults_out,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _looks_like_goods(reason_norm: str) -> bool:
    return any(token in reason_norm for token in {"TIEN HANG", "TIENHANG", "MUA HANG", "BAN HANG"})


def _purpose_code_from_reason(reason_norm: str) -> str:
    text = re.sub(r"\b(TT|THANH TOAN|THU|NOP|TIEN|PHI|CUOC)\b", " ", reason_norm)
    tokens = [token.lower() for token in text.split() if len(token) > 1][:5]
    return "_".join(tokens) or "review_purpose"


def _dedupe_code(code: str, existing_codes: set[str]) -> str:
    candidate = code
    suffix = 2
    while candidate in existing_codes:
        candidate = f"{code}_{suffix}"
        suffix += 1
    existing_codes.add(candidate)
    return candidate


def _label_from_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    text = re.sub(r"^\s*(TT|Thanh toán|Thu|Nộp)\s+", "", text, flags=re.IGNORECASE)
    text = _strip_trailing_reference(text)
    return text[:1].lower() + text[1:] if text else ""


def _strip_trailing_reference(text: str) -> str:
    """Bỏ đuôi tham chiếu chứng từ/số/ngày để nhãn nghiệp vụ gọn (report-only, người vẫn duyệt lại)."""
    patterns = [
        r"\s*(?:HĐ|HD|HOÁ ĐƠN|HOÀ ĐƠN|HOA DON|SỐ|SO|TỜ KHAI|TO KHAI|BILL|INV)\b.*$",
        r"\s*\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\s*$",
        r"\s+\d{2,}\s*$",
    ]
    result = text
    for pattern in patterns:
        stripped = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
        if stripped:
            result = stripped
    return result


def _is_treasury_or_bank(object_name: str, reason_norm: str) -> bool:
    """True nếu Mã ĐT là ngân hàng, hoặc lý do mang tính kho quỹ/nội bộ (không phải nghiệp vụ 331/131)."""
    name_norm = normalize_text(object_name)
    if any(token in name_norm for token in _BANK_NAME_TOKENS):
        return True
    return any(token in reason_norm for token in _TREASURY_REASON_TOKENS)


def _reason_is_counterparty_echo(reason_norm: str, object_name: str) -> bool:
    """True nếu lý do chỉ nhắc lại TÊN đối tượng ("Thu tiền Công ty X") -> không có nghiệp vụ thực.

    Chính là mẫu fallback trơ đang rò vào cột lý do lịch sử; nâng nó thành purpose sẽ tạo
    nghiệp vụ tự-tham-chiếu vô nghĩa (vd code `cong_ty_tnhh_...`).
    """
    core = re.sub(_REASON_LEAD_VERBS, "", reason_norm).strip()
    if not core:
        return True
    if any(marker in core for marker in _COMPANY_MARKERS):
        return True
    core_tokens = [token for token in core.split() if len(token) > 1]
    if not core_tokens:
        return True
    name_tokens = {token for token in normalize_text(object_name).split() if len(token) > 1}
    if not name_tokens:
        return False
    # Ngưỡng cao: chỉ loại khi lõi lý do gần như TRÙNG KHỚP tên đối tượng (tên thương mại lặp lại),
    # tránh loại nhầm nghiệp vụ đúng ngành nghề (vd "phí công chứng" ↔ "văn phòng công chứng").
    overlap = sum(1 for token in core_tokens if token in name_tokens)
    return overlap / len(core_tokens) >= 0.8


def _object_name_already_explains_purpose(
    object_name: str,
    purpose: str,
    object_name_rules: list[tuple[str, str]],
) -> bool:
    name_norm = normalize_text(object_name)
    return any(rule_purpose == purpose and keyword in name_norm for keyword, rule_purpose in object_name_rules)


def _top_reasons(group: pd.DataFrame, limit: int = 5) -> str:
    reasons = group.groupby("reason")["count"].sum().sort_values(ascending=False).head(limit)
    return "; ".join(f"{reason} ({int(count)})" for reason, count in reasons.items())


def _sample_values(values: Any, limit: int = 5) -> str:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return " | ".join(result)


if __name__ == "__main__":
    raise SystemExit(main())
