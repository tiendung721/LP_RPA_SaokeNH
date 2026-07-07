from __future__ import annotations

from ..models import Transaction
from ..normalizer import normalize_text
from .base_parser import BaseBankParser


class MSBParser(BaseBankParser):
    bank = "MSB"
    preferred_sheets = ("Sheet1",)
    field_aliases = {
        "transaction_date": ["NGAY GIAO DICH TRANSACTION DATE", "TRANSACTION DATE"],
        "doc_no": ["SO BUT TOAN REFERENCE NO", "REFERENCE NO"],
        "counterparty_raw": [
            "NGUOI HUONG NGUOI CHUYEN PAYEE PAYER",
            "NGUOI HUONG NGUOI CHUYEN",
            "NGUOI HUONG",
            "NGUOI CHUYEN",
            "NGUOI THU HUONG",
            "TEN NGUOI THU HUONG",
            "BENEFICIARY",
            "PAYEE",
            "PAYER",
            "PAYEE PAYER",
        ],
        "description": ["DIEN GIAI TRANSACTION DESCRIPTION", "TRANSACTION DESCRIPTION"],
        "debit_amount": ["NO DEBIT"],
        "credit_amount": ["CO CREDIT"],
    }

    def _should_keep(self, transaction: Transaction) -> bool:
        raw_text = normalize_text(" ".join(str(value) for value in transaction.raw_data.values()))
        if any(
            marker in raw_text
            for marker in (
                "SO DU DAU KY",
                "OPENING BALANCE",
                "TONG PHAT SINH",
                "TOTAL DEBIT CREDIT AMOUNT",
                "SO DU CUOI KY",
                "CLOSING BALANCE",
                "THONG TIN NAY DUOC IN",
                "PRINTED ON",
            )
        ):
            return False
        if transaction.transaction_date is None:
            return False
        return super()._should_keep(transaction)
