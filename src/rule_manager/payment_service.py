from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from src.normalizer import normalize_text

from .backup import ChangeBackup
from .models import ValidationIssue
from .paths import RuleManagerPaths
from .payment_models import ManagedPaymentPurpose, PaymentPublishResult
from .payment_publisher import PaymentYamlPublisher
from .payment_repository import PaymentRuleRepository
from .simple_alias import ManagedTextAlias


BLOCKED_PAYMENT_ALIASES = {
    "TT",
    "THANH TOAN",
    "THANH TOAN TIEN",
    "CHUYEN TIEN",
    "THU",
    "THU TIEN",
    "PHI",
    "TIEN",
    "CUOC",
    "HD",
    "HOA DON",
    "CONG NO",
}


class PaymentValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues if issue.is_error))


class PaymentRuleManagerService:
    def __init__(self, paths: RuleManagerPaths):
        self.paths = paths
        self.repository = PaymentRuleRepository(paths.payment_rules_path)
        self.publisher = PaymentYamlPublisher(paths.reason_aliases_path)
        self.backup = ChangeBackup(paths.project_root, paths.backup_dir)

    def list_purposes(self, include_deleted: bool = False) -> list[ManagedPaymentPurpose]:
        managed = self.repository.records()
        by_code = {record.code: record for record in managed}
        rows: list[ManagedPaymentPurpose] = []
        seen: set[str] = set()
        for config_record in self.publisher.config_records():
            record = by_code.get(config_record.code, config_record)
            seen.add(record.code)
            if include_deleted or not record.deleted:
                rows.append(record)
        for record in managed:
            if record.code in seen:
                continue
            if include_deleted or not record.deleted:
                rows.append(record)
        return sorted(rows, key=lambda item: (not item.active, normalize_text(item.label)))

    def new_record(self, label: str, aliases: tuple[ManagedTextAlias, ...]) -> ManagedPaymentPurpose:
        code = self._new_code(label)
        return ManagedPaymentPurpose.new_user(code, label.strip(), aliases)

    def validate(self, record: ManagedPaymentPurpose) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        label_norm = normalize_text(record.label)
        if not record.label.strip():
            issues.append(ValidationIssue("error", "MISSING_LABEL", "Tên loại thanh toán không được để trống"))
        if not record.code.strip():
            issues.append(ValidationIssue("error", "MISSING_CODE", "Không tạo được mã kỹ thuật cho loại thanh toán"))

        aliases = [alias for alias in record.aliases if alias.active and not alias.deleted]
        if record.active and not record.deleted and not aliases:
            issues.append(ValidationIssue("error", "MISSING_ALIAS", "Loại thanh toán phải có ít nhất một alias"))

        own_values: set[str] = set()
        for alias in aliases:
            alias_norm = normalize_text(alias.value)
            if not alias_norm:
                issues.append(ValidationIssue("error", "EMPTY_ALIAS", "Alias không được để trống"))
                continue
            if alias_norm in own_values:
                issues.append(ValidationIssue("error", "DUPLICATE_ALIAS", f"Alias bị nhập trùng: {alias.value}"))
            own_values.add(alias_norm)
            if alias_norm in BLOCKED_PAYMENT_ALIASES:
                issues.append(ValidationIssue("error", "BLOCKED_ALIAS", f"Alias quá chung: {alias.value}"))

        tokens = {label_norm, *own_values} - {""}
        for other in self.list_purposes():
            if other.record_id == record.record_id or other.deleted or not other.active:
                continue
            if label_norm and label_norm == normalize_text(other.label):
                issues.append(ValidationIssue("error", "DUPLICATE_LABEL", f"Tên loại đã tồn tại: {other.label}"))
            other_tokens = {normalize_text(other.label)} | {normalize_text(value) for value in other.active_aliases}
            collision = tokens & other_tokens
            if collision:
                issues.append(
                    ValidationIssue(
                        "error",
                        "ALIAS_COLLISION",
                        f"Alias/tên nhận diện đang thuộc loại “{other.label}”: {sorted(collision)[0]}",
                    )
                )

        if record.deleted and self._is_referenced(record.code):
            issues.append(
                ValidationIssue(
                    "error",
                    "PURPOSE_IN_USE",
                    "Loại thanh toán đang được cấu hình hệ thống tham chiếu; hãy tạm ngưng thay vì xóa",
                )
            )
        return issues

    def apply(self, record: ManagedPaymentPurpose) -> PaymentPublishResult:
        issues = self.validate(record)
        if any(issue.is_error for issue in issues):
            raise PaymentValidationError(issues)
        backup_dir = self.backup.create(
            [self.paths.payment_rules_path, self.paths.reason_aliases_path],
            metadata={"action": "apply_payment_purpose", "code": record.code, "label": record.label},
        )
        try:
            self.repository.upsert(record)
            self.publisher.publish(self.repository.records())
        except Exception:
            self.backup.restore(backup_dir)
            raise
        return PaymentPublishResult(
            backup_dir=str(backup_dir),
            changed_files=(str(self.paths.payment_rules_path), str(self.paths.reason_aliases_path)),
            warnings=tuple(issue.message for issue in issues if issue.severity == "warning"),
        )

    def _new_code(self, label: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", normalize_text(label).lower()).strip("_") or "payment_type"
        existing = {record.code for record in self.list_purposes(include_deleted=True)}
        code = base
        suffix = 2
        while code in existing:
            code = f"{base}_{suffix}"
            suffix += 1
        return code

    def _is_referenced(self, code: str) -> bool:
        data = self.publisher.load_mapping()
        if code in {str(value or "").strip() for value in (data.get("object_purpose_defaults", {}) or {}).values()}:
            return True
        return any(
            isinstance(item, dict) and str(item.get("purpose", "") or "").strip() == code
            for item in data.get("object_name_purposes", []) or []
        )
