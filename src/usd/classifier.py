from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Transaction
from ..normalizer import normalize_text


RULE_FOREIGN_CURRENCY_SALE = "usd_foreign_currency_sale"
RULE_BANK_FEE = "usd_bank_fee"
RULE_CASH_WITHDRAWAL = "usd_cash_withdrawal"
RULE_CREDIT_DEFAULT = "usd_credit_default"
RULE_DEBIT_PORT_PAYMENT = "usd_debit_port_payment"
RULE_DEBIT_DEFAULT = "usd_debit_default"
RULE_INVALID_DIRECTION = "usd_invalid_direction"
RULE_INVALID_WITHDRAWAL = "usd_invalid_withdrawal"


@dataclass(frozen=True)
class USDClassification:
    rule_id: str
    action: str
    employee_name: str = ""
    error_note: str = ""

    @property
    def requires_rate(self) -> bool:
        return self.action == "ENTRY"


class USDClassifier:
    def classify(self, transaction: Transaction) -> USDClassification:
        text = normalize_text(transaction.description)

        if _contains_phrase(text, "BAN NGOAI TE"):
            return USDClassification(RULE_FOREIGN_CURRENCY_SALE, "SKIP")
        if _is_bank_fee(text):
            return USDClassification(RULE_BANK_FEE, "SKIP")

        has_withdrawal_signal = "CCCD" in text and _has_cash_withdrawal_marker(text)
        if has_withdrawal_signal:
            if not (transaction.debit_amount > 0 and transaction.credit_amount <= 0):
                return USDClassification(
                    RULE_INVALID_WITHDRAWAL,
                    "ERROR",
                    error_note="Giao dịch rút tiền có CCCD phải là Debit",
                )
            employee_name = extract_employee_before_cccd(text)
            if not employee_name:
                return USDClassification(
                    RULE_INVALID_WITHDRAWAL,
                    "ERROR",
                    error_note="Không lấy được tên nhân viên trước CCCD",
                )
            return USDClassification(RULE_CASH_WITHDRAWAL, "ENTRY", employee_name=employee_name)

        debit = float(transaction.debit_amount or 0)
        credit = float(transaction.credit_amount or 0)
        if (debit > 0 and credit > 0) or (debit <= 0 and credit <= 0):
            return USDClassification(
                RULE_INVALID_DIRECTION,
                "ERROR",
                error_note="Dòng USD phải có đúng một chiều Debit hoặc Credit",
            )
        if credit > 0:
            return USDClassification(RULE_CREDIT_DEFAULT, "ENTRY")
        if _is_port_payment(text):
            return USDClassification(RULE_DEBIT_PORT_PAYMENT, "ENTRY")
        return USDClassification(RULE_DEBIT_DEFAULT, "ENTRY")


def extract_employee_before_cccd(normalized_text: str) -> str:
    before_cccd = normalized_text.split("CCCD", 1)[0].strip()
    tokens = before_cccd.split()
    for start in range(max(0, len(tokens) - 6), len(tokens) - 1):
        candidate = tokens[start:]
        if candidate[0] in _VIETNAMESE_FAMILY_NAMES and 2 <= len(candidate) <= 6:
            return " ".join(candidate)
    return ""


def _is_bank_fee(text: str) -> bool:
    return (
        text == "PHI"
        or text.startswith("PHI ")
        or text == "THU PHI"
        or text.startswith("THU PHI ")
        or ((text == "VAT" or text.startswith("VAT ")) and _has_token(text, "PHI"))
    )


def _has_cash_withdrawal_marker(text: str) -> bool:
    return any(
        re.search(pattern, text) is not None
        for pattern in (
            r"(?<![A-Z0-9])RTM(?![A-Z0-9])",
            r"(?<![A-Z0-9])RUT\s+TM(?![A-Z0-9])",
            r"(?<![A-Z0-9])RUT\s+TIEN(?:\s+MAT)?(?![A-Z0-9])",
        )
    )


def _is_port_payment(text: str) -> bool:
    return _contains_phrase(text, "LE PHAM") and (_has_token(text, "TT") or _contains_phrase(text, "THANH TOAN")) and _has_token(text, "CANG")


def _has_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text) is not None


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![A-Z0-9])" + r"\s+".join(re.escape(token) for token in phrase.split()) + r"(?![A-Z0-9])"
    return re.search(pattern, text) is not None


_VIETNAMESE_FAMILY_NAMES = {
    "BUI", "CAO", "CHAU", "CHU", "DAO", "DANG", "DINH", "DO", "DUONG", "HA", "HO", "HOANG",
    "HUYNH", "KIEU", "LA", "LAM", "LE", "LUONG", "LY", "MAC", "MAI", "NGO", "NGUYEN", "PHAM",
    "PHAN", "QUACH", "TA", "THAI", "TO", "TON", "TRAN", "TRINH", "TRUONG", "VU", "VO",
}
