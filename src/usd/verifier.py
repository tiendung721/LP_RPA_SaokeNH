from __future__ import annotations

from .classifier import (
    RULE_CASH_WITHDRAWAL,
    RULE_CREDIT_DEFAULT,
    RULE_DEBIT_DEFAULT,
    RULE_DEBIT_PORT_PAYMENT,
)
from .models import AccountingEntry, USDSourceTransaction
from .profile import USDProfile


class USDAccountingVerifier:
    def __init__(self, profile: USDProfile):
        self.profile = profile

    def verify(self, source: USDSourceTransaction, entries: list[AccountingEntry]) -> list[str]:
        errors: list[str] = []
        expected_count = 2 if source.classification == RULE_CASH_WITHDRAWAL else 1
        if len(entries) != expected_count:
            errors.append(f"Rule {source.classification} phải sinh {expected_count} chứng từ")
        if source.exchange_rate is None or source.exchange_rate <= 0:
            errors.append("Tỷ giá USD không hợp lệ")

        expected_accounts = {
            RULE_CREDIT_DEFAULT: [(self.profile.bank_usd_account, self.profile.receivable_offset_account)],
            RULE_DEBIT_PORT_PAYMENT: [(self.profile.advance_account, self.profile.bank_usd_account)],
            RULE_DEBIT_DEFAULT: [(self.profile.advance_account, self.profile.bank_usd_account)],
            RULE_CASH_WITHDRAWAL: [
                (self.profile.cash_account, self.profile.bank_usd_account),
                (self.profile.advance_account, self.profile.cash_account),
            ],
        }.get(source.classification, [])
        actual_accounts = [(item.debit_account, item.credit_account) for item in entries]
        if actual_accounts != expected_accounts:
            errors.append(f"Tài khoản USD không đúng cho rule {source.classification}")

        for item in entries:
            if item.source_transaction_uid != source.source_transaction_uid:
                errors.append("Accounting entry không liên kết đúng transaction nguồn")
            if item.exchange_rate != source.exchange_rate:
                errors.append("Các chứng từ không dùng chung tỷ giá transaction nguồn")
            if item.foreign_amount != source.foreign_amount:
                errors.append("Các chứng từ không dùng đúng số USD transaction nguồn")
            if item.amount != source.foreign_amount * item.exchange_rate:
                errors.append("Thành tiền USD quy đổi không chính xác")
        if source.classification == RULE_CASH_WITHDRAWAL and len(entries) == 2:
            if not entries[0].payer_name:
                errors.append("Phiếu Thu thiếu người nộp tiền")
            if entries[1].receiver_name != self.profile.cash_payment_receiver:
                errors.append("Phiếu Chi không đúng người nhận tiền")
        return list(dict.fromkeys(errors))
