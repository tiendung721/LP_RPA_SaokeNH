from __future__ import annotations

from .entity_extractor import OwnCompanyConfig
from .flows import CASH_ACCOUNT, FLOW_CHI_TIEN_MAT, FLOW_THU_TIEN_MAT
from .models import ProcessedTransaction, Rule, VerificationResult


class AccountingVerifier:
    def __init__(self, bank_accounts: dict[str, str], own_company: OwnCompanyConfig):
        self.bank_accounts = bank_accounts
        self.own_company = own_company

    def verify(self, item: ProcessedTransaction, rule: Rule | None = None) -> VerificationResult:
        errors: list[str] = []
        bank_account = self.bank_accounts.get(item.bank, "")
        checks = {
            "bank_account": bank_account,
            "not_own_company": True,
            "flow_accounts_valid": True,
        }

        if item.object_code and self.own_company.is_own_code(item.object_code):
            checks["not_own_company"] = False
            errors.append("Mã đối tượng là công ty mình")
        if item.object_name and self.own_company.is_own_name(item.object_name):
            checks["not_own_company"] = False
            errors.append("Tên đối tượng là công ty mình")

        if item.flow == "bao_no" and bank_account and item.credit_account != bank_account:
            checks["flow_accounts_valid"] = False
            errors.append("Báo nợ phải có TK có là tài khoản ngân hàng")
        if item.flow == "bao_co" and bank_account and item.debit_account != bank_account:
            checks["flow_accounts_valid"] = False
            errors.append("Báo có phải có TK nợ là tài khoản ngân hàng")
        if item.flow == FLOW_THU_TIEN_MAT and bank_account:
            if item.debit_account != CASH_ACCOUNT or item.credit_account != bank_account:
                checks["flow_accounts_valid"] = False
                errors.append("Phiếu thu tiền mặt phải Nợ 1111/Có tài khoản ngân hàng")
        if item.flow == FLOW_CHI_TIEN_MAT and bank_account:
            if item.debit_account != bank_account or item.credit_account != CASH_ACCOUNT:
                checks["flow_accounts_valid"] = False
                errors.append("Phiếu chi tiền mặt phải Nợ tài khoản ngân hàng/Có 1111")

        if rule and not rule.auto_process:
            errors.append(rule.error_note or "Rule không xử lý tự động")

        if rule and rule.requires_object:
            if not item.object_code or item.object_code == "ERROR":
                errors.append("Nghiệp vụ bắt buộc mã đối tượng nhưng chưa có mã hợp lệ")
            object_score = 0.0 if _uses_forced_object_code(rule, item) else _matched_object_score(item)
            if object_score and object_score < 80:
                errors.append("Độ tin cậy mã đối tượng thấp")

        status = "ERROR" if errors else "OK"
        return VerificationResult(status=status, error_note="; ".join(dict.fromkeys(errors)), checks=checks)


def _matched_object_score(item: ProcessedTransaction) -> float:
    if not item.object_code or item.object_code == "ERROR":
        return 0.0
    for candidate in item.matched_candidates:
        if candidate.code == item.object_code:
            return candidate.score
    if item.matched_candidates:
        return item.matched_candidates[0].score
    return 0.0


def _uses_forced_object_code(rule: Rule, item: ProcessedTransaction) -> bool:
    return bool(rule.forced_object_code and item.object_code == rule.forced_object_code)
