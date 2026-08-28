from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from src.config_loader import rule_config_id
from src.normalizer import normalize_text

from .accounting_models import (
    CASH_FLOWS,
    FLOW_KEYS,
    AccountingPublishResult,
    AccountingRuleView,
    ManagedAccountingRule,
)
from .accounting_publisher import AccountingYamlPublisher
from .accounting_repository import AccountingRuleRepository
from .backup import ChangeBackup
from .models import ValidationIssue
from .paths import RuleManagerPaths
from .simple_alias import ManagedTextAlias


BLOCKED_ACCOUNTING_ALIASES = {
    "TT",
    "THANH TOAN",
    "THANH TOAN TIEN",
    "CHUYEN TIEN",
    "TIEN",
    "PHI",
    "HD",
    "HOA DON",
    "CONG NO",
}


class AccountingValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues if issue.is_error))


class AccountingRuleManagerService:
    def __init__(self, paths: RuleManagerPaths):
        self.paths = paths
        self.repository = AccountingRuleRepository(paths.accounting_rules_path)
        self.publisher = AccountingYamlPublisher(paths.default_rules_path)
        self.backup = ChangeBackup(paths.project_root, paths.backup_dir)

    def list_rules(self) -> list[AccountingRuleView]:
        user_records = self.repository.records()
        user_ids = {record.rule_id for record in user_records if record.source == "user"}
        overrides = {record.rule_id: record for record in user_records if record.source == "override"}
        rows: list[AccountingRuleView] = []
        for index, item in enumerate(self.publisher.load_mapping().get("rules", []) or []):
            if not isinstance(item, dict):
                continue
            rule_id = rule_config_id(item, index)
            if rule_id in user_ids:
                continue
            aliases = tuple(
                ManagedTextAlias.from_config(f"builtin:{index}", str(alias))
                for alias in item.get("include_keywords", []) or []
            )
            override = overrides.get(rule_id)
            rows.append(
                AccountingRuleView(
                    record_id=override.record_id if override else rule_id,
                    rule_id=rule_id,
                    use_case=str(item.get("use_case", "") or "").strip(),
                    account=str(item.get("account", "") or "").strip(),
                    flow=str(item.get("flow", "") or "").strip(),
                    aliases=aliases,
                    active=override.active if override else True,
                    source="override" if override else "builtin",
                )
            )
        rows.extend(record for record in user_records if record.source == "user" and not record.deleted)
        return sorted(rows, key=lambda item: (item.flow, normalize_text(item.use_case), item.account))

    def new_record(
        self,
        use_case: str,
        account: str,
        flow: str,
        aliases: tuple[ManagedTextAlias, ...],
    ) -> ManagedAccountingRule:
        if flow in CASH_FLOWS:
            account = "1111"
        return ManagedAccountingRule.new_user(use_case.strip(), account.strip(), flow, aliases)

    def validate(self, record: ManagedAccountingRule) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if record.source not in {"user", "override"}:
            issues.append(ValidationIssue("error", "BUILTIN_READ_ONLY", "Nghiệp vụ có sẵn chỉ được xem"))
            return issues
        if record.source == "override":
            return issues
        if not record.use_case.strip():
            issues.append(ValidationIssue("error", "MISSING_USE_CASE", "Tên nghiệp vụ không được để trống"))
        if record.flow not in FLOW_KEYS:
            issues.append(ValidationIssue("error", "INVALID_FLOW", "Chưa chọn luồng hợp lệ"))
        account = "1111" if record.flow in CASH_FLOWS else record.account.strip()
        if not account:
            issues.append(ValidationIssue("error", "MISSING_ACCOUNT", "Tài khoản không được để trống"))
        elif not re.fullmatch(r"[A-Za-z0-9._-]+", account):
            issues.append(ValidationIssue("error", "INVALID_ACCOUNT", "Tài khoản chứa ký tự không hợp lệ"))

        aliases = [alias for alias in record.aliases if alias.active and not alias.deleted]
        if record.active and not record.deleted and not aliases:
            issues.append(ValidationIssue("error", "MISSING_ALIAS", "Nghiệp vụ phải có ít nhất một alias"))
        own: set[str] = set()
        for alias in aliases:
            alias_norm = normalize_text(alias.value)
            if not alias_norm:
                issues.append(ValidationIssue("error", "EMPTY_ALIAS", "Alias không được để trống"))
                continue
            if alias_norm in own:
                issues.append(ValidationIssue("error", "DUPLICATE_ALIAS", f"Alias bị nhập trùng: {alias.value}"))
            own.add(alias_norm)
            if alias_norm in BLOCKED_ACCOUNTING_ALIASES:
                issues.append(ValidationIssue("error", "BLOCKED_ALIAS", f"Alias quá chung: {alias.value}"))

        for other in self.list_rules():
            if (
                other.record_id == record.record_id
                or other.rule_id == record.rule_id
                or other.flow != record.flow
                or other.deleted
                or not other.active
            ):
                continue
            other_aliases = {normalize_text(value) for value in other.active_aliases}
            collision = own & other_aliases
            if collision:
                issues.append(
                    ValidationIssue(
                        "error",
                        "ALIAS_COLLISION",
                        f"Alias đã thuộc nghiệp vụ “{other.use_case}” trong cùng luồng: {sorted(collision)[0]}",
                    )
                )
            elif any(_phrase_overlap(left, right) for left in own for right in other_aliases):
                issues.append(
                    ValidationIssue(
                        "warning",
                        "ALIAS_OVERLAP",
                        f"Alias có thể giao với nghiệp vụ “{other.use_case}”; hệ thống sẽ ưu tiên alias cụ thể hơn",
                    )
                )
        return issues

    def apply(self, record: ManagedAccountingRule) -> AccountingPublishResult:
        if record.flow in CASH_FLOWS and record.account != "1111":
            record = replace(record, account="1111")
        issues = self.validate(record)
        if any(issue.is_error for issue in issues):
            raise AccountingValidationError(issues)
        backup_dir = self.backup.create(
            [self.paths.accounting_rules_path, self.paths.default_rules_path],
            metadata={"action": "apply_accounting_rule", "rule_id": record.rule_id},
        )
        try:
            self.repository.upsert(record)
            self.publisher.publish(self.repository.records())
        except Exception:
            self.backup.restore(backup_dir)
            raise
        return AccountingPublishResult(
            backup_dir=str(backup_dir),
            changed_files=(str(self.paths.accounting_rules_path), str(self.paths.default_rules_path)),
            warnings=tuple(issue.message for issue in issues if issue.severity == "warning"),
        )

    def set_active(self, record: AccountingRuleView, active: bool) -> AccountingPublishResult:
        if record.active == active:
            raise ValueError("Loại tài khoản đã ở trạng thái yêu cầu")
        if isinstance(record, ManagedAccountingRule) and record.source == "user":
            managed = replace(record, active=active, deleted=False)
        else:
            existing = next(
                (
                    item
                    for item in self.repository.records()
                    if item.source == "override" and item.rule_id == record.rule_id
                ),
                None,
            )
            if existing:
                managed = replace(existing, active=active, deleted=False)
            else:
                managed = ManagedAccountingRule(
                    record_id=f"override:{record.rule_id}",
                    rule_id=record.rule_id,
                    use_case=record.use_case,
                    account=record.account,
                    flow=record.flow,
                    aliases=record.aliases,
                    active=active,
                    deleted=False,
                    source="override",
                )
        return self.apply(managed)


def _phrase_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return f" {left} " in f" {right} " or f" {right} " in f" {left} "
