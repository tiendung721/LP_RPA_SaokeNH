from __future__ import annotations

import re

from .flows import FLOW_CHI_TIEN_MAT, FLOW_THU_TIEN_MAT
from .models import ExtractedEntities
from .normalizer import clean_display_text, normalize_text
from .reason_aliases import ReasonPurpose, match_object_name_purpose, match_reason_purpose


OBJECT_CODE_PLACEHOLDER = "{object_code}"

TEMPLATES: dict[tuple[str, str], str] = {
    ("bao_no", "331"): "TT tiền hàng ({object_code})",
    ("bao_no", "141"): "Tạm ứng cá nhân {object_code}",
    ("bao_no", "334"): "Trả lương nhân viên",
    ("bao_no", "3331"): "Nộp thuế GTGT",
    ("bao_no", "3333"): "Nộp thuế XNK",
    ("bao_no", "3334"): "Nộp thuế TNDN",
    ("bao_no", "3335"): "Nộp thuế TNCN",
    ("bao_no", "6421"): "TT phí hải quan",
    ("bao_no", "64211"): "TT phí hải quan",
    ("bao_no", "635"): "Chi phí tài chính",
    ("bao_no", "1122"): "Mua ngoại tệ",
    ("bao_no", "34111"): "TT tài khoản vay",
    ("bao_co", "131"): "Thanh toán ({object_code})",
    ("bao_co", "141"): "Nhận tiền tạm ứng {object_code}",
    ("bao_co", "515"): "Lãi tiền gửi ngân hàng",
    ("bao_co", "1122"): "Bán ngoại tệ",
    ("bao_co", "34111"): "Nhận tiền vay ngân hàng",
    (FLOW_THU_TIEN_MAT, "1111"): "Rút tiền nhập quỹ",
    (FLOW_CHI_TIEN_MAT, "1111"): "Nộp tiền mặt vào tài khoản",
}


def generate_reason(
    flow: str,
    debit_account: str = "",
    credit_account: str = "",
    object_code: str = "",
    object_name: str = "",
    description: str = "",
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None = None,
    object_purpose_defaults: dict[str, str] | None = None,
    entities: ExtractedEntities | None = None,
    object_name_purposes: list[tuple[str, str]] | None = None,
) -> str:
    account = _business_account(flow, debit_account, credit_account)
    if (flow, account) == ("bao_no", "331"):
        return _payable_reason(
            object_code, object_name, description, purposes, object_purpose_defaults, entities, object_name_purposes
        )
    if (flow, account) == ("bao_co", "131"):
        return _receivable_reason(
            object_code, object_name, description, purposes, object_purpose_defaults, entities, object_name_purposes
        )

    template = TEMPLATES.get((flow, account), "")
    if not template:
        return ""
    if OBJECT_CODE_PLACEHOLDER not in template:
        return template

    cleaned_object_code = clean_reason_value(object_code)
    if not cleaned_object_code or cleaned_object_code == "ERROR":
        return ""
    return template.format(object_code=cleaned_object_code)


def reason_requires_object_code(flow: str, debit_account: str = "", credit_account: str = "") -> bool:
    account = _business_account(flow, debit_account, credit_account)
    template = TEMPLATES.get((flow, account), "")
    return OBJECT_CODE_PLACEHOLDER in template


def has_usable_object_code(object_code: str) -> bool:
    cleaned_object_code = clean_reason_value(object_code)
    return bool(cleaned_object_code and cleaned_object_code != "ERROR")


def clean_reason_value(value: str) -> str:
    text = clean_display_text(value)
    return re.sub(r"\s+", " ", text)


def _payable_reason(
    object_code: str,
    object_name: str,
    description: str,
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None,
    object_purpose_defaults: dict[str, str] | None,
    entities: ExtractedEntities | None,
    object_name_purposes: list[tuple[str, str]] | None = None,
) -> str:
    party = _reason_party(object_code, object_name)
    if not party:
        return ""
    purpose = _resolve_purpose(
        object_code, object_name, description, purposes, object_purpose_defaults, object_name_purposes
    )
    if not purpose:
        # Nhà cung cấp đã match chắc chắn nhưng nội dung CK thiếu mục đích; sổ VACOM thường hạch toán fallback là tiền hàng.
        return f"TT tiền hàng ({party})"
    return f"TT {_format_purpose_label(purpose, entities)} ({party})"


def _receivable_reason(
    object_code: str,
    object_name: str,
    description: str,
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None,
    object_purpose_defaults: dict[str, str] | None,
    entities: ExtractedEntities | None,
    object_name_purposes: list[tuple[str, str]] | None = None,
) -> str:
    party = _reason_party(object_code, object_name)
    if not party:
        return ""
    purpose = _resolve_purpose(
        object_code, object_name, description, purposes, object_purpose_defaults, object_name_purposes
    )
    if not purpose:
        return f"Thanh toán ({party})"
    return f"TT {_format_purpose_label(purpose, entities)} ({party})"


def _resolve_purpose(
    object_code: str,
    object_name: str,
    description: str,
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None,
    object_purpose_defaults: dict[str, str] | None,
    object_name_purposes: list[tuple[str, str]] | None,
) -> ReasonPurpose | None:
    # 1) Mục đích nêu rõ trong nội dung CK  ->  2) default riêng theo Mã ĐT
    # ->  3) suy theo LOẠI đối tượng (tên danh mục)  ->  (rỗng: fallback tiền hàng).
    return (
        match_reason_purpose(description, purposes)
        or _default_purpose_for_object(object_code, purposes, object_purpose_defaults)
        or _category_purpose_for_object(object_name, purposes, object_name_purposes)
    )


def _category_purpose_for_object(
    object_name: str,
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None,
    object_name_purposes: list[tuple[str, str]] | None,
) -> ReasonPurpose | None:
    if not purposes or not object_name_purposes:
        return None
    purpose_code = match_object_name_purpose(object_name, object_name_purposes)
    if not purpose_code:
        return None
    purpose_by_code = {purpose.code: purpose for purpose in purposes}
    return purpose_by_code.get(purpose_code)


def _default_purpose_for_object(
    object_code: str,
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None,
    object_purpose_defaults: dict[str, str] | None,
) -> ReasonPurpose | None:
    if not purposes or not object_purpose_defaults:
        return None
    purpose_code = object_purpose_defaults.get(normalize_text(object_code))
    if not purpose_code:
        return None
    purpose_by_code = {purpose.code: purpose for purpose in purposes}
    return purpose_by_code.get(purpose_code)


def _format_purpose_label(purpose: ReasonPurpose, entities: ExtractedEntities | None) -> str:
    values = {
        "vessel": clean_reason_value(entities.vessel if entities else ""),
        "invoice_no": clean_reason_value(entities.invoice_no if entities else ""),
    }
    label = clean_reason_value(purpose.label)
    for key, value in values.items():
        label = label.replace("{" + key + "}", value)
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"\s+([,.;:])", r"\1", label)
    return re.sub(r"\s*:\s*$", "", label).strip()


def _reason_party(object_code: str, object_name: str) -> str:
    cleaned_object_name = clean_reason_value(object_name)
    if cleaned_object_name:
        return cleaned_object_name
    cleaned_object_code = clean_reason_value(object_code)
    if not cleaned_object_code or cleaned_object_code == "ERROR":
        return ""
    return cleaned_object_code


def _business_account(flow: str, debit_account: str, credit_account: str) -> str:
    if flow == "bao_no":
        return _reason_account_key(debit_account)
    if flow == "bao_co":
        return _reason_account_key(credit_account)
    if flow == FLOW_THU_TIEN_MAT:
        return _reason_account_key(debit_account)
    if flow == FLOW_CHI_TIEN_MAT:
        return _reason_account_key(credit_account)
    return ""


def _reason_account_key(account: str) -> str:
    value = str(account or "").strip().upper()
    if value.startswith("1122"):
        return "1122"
    return value
