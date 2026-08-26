from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from src.normalizer import normalize_text

from .backup import ChangeBackup
from .catalogs import ObjectCatalogStore
from .models import (
    CATALOG_DEFINITIONS,
    CATALOG_KEYS,
    MATCH_TYPES,
    AliasInput,
    ManagedAlias,
    ManagedObject,
    ObjectChangeRequest,
    PublishResult,
    StoredObject,
    ValidationIssue,
)
from .paths import RuleManagerPaths
from .publisher import ObjectYamlPublisher
from .repository import UserRuleRepository


BLOCKED_ALIASES = {
    "CTY",
    "CONG TY",
    "THANH TOAN",
    "THANH TOAN TIEN",
    "TIEN",
    "PHI",
    "HD",
    "HOA DON",
    "CONG NO",
}


class RuleManagerValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues if issue.is_error))


@dataclass(frozen=True)
class ObjectListRow:
    object: ManagedObject
    alias_count: int


class ObjectRuleManagerService:
    def __init__(self, paths: RuleManagerPaths):
        self.paths = paths
        self.catalogs = ObjectCatalogStore(paths)
        self.repository = UserRuleRepository(paths.user_rules_path)
        self.publisher = ObjectYamlPublisher(paths)
        self.backup = ChangeBackup(paths.project_root, paths.backup_dir)

    def list_objects(self, catalog: str) -> list[ObjectListRow]:
        aliases = self.publisher.alias_targets().get(catalog, {})
        counts: dict[str, int] = {}
        for targets in aliases.values():
            for target in targets:
                key = normalize_text(target["object_code"])
                counts[key] = counts.get(key, 0) + 1
        return [
            ObjectListRow(item, counts.get(normalize_text(item.code), 0))
            for item in self.catalogs.list_objects(catalog)
        ]

    def aliases_for_object(self, catalog: str, object_code: str) -> list[dict[str, object]]:
        managed_by_key = {
            (record.catalog, normalize_text(record.alias)): record
            for record in self.repository.aliases()
        }
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for row in self.publisher.aliases_for_object(catalog, object_code):
            key = (catalog, row["alias_norm"])
            managed = managed_by_key.get(key)
            rows.append(
                {
                    "alias": row["alias"],
                    "match_type": row["match_type"],
                    "active": True if managed is None else managed.active,
                    "managed": managed is not None,
                }
            )
            seen.add(key)
        for key, managed in managed_by_key.items():
            if key in seen or managed.catalog != catalog:
                continue
            if normalize_text(managed.object_code) != normalize_text(object_code):
                continue
            rows.append(
                {
                    "alias": managed.alias,
                    "match_type": managed.match_type,
                    "active": managed.active,
                    "managed": True,
                }
            )
        return sorted(rows, key=lambda row: (not bool(row["active"]), str(row["alias"])))

    def validate(self, request: ObjectChangeRequest) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        catalog = request.catalog.strip()
        code = request.code.strip()
        name = request.name.strip()
        if catalog not in CATALOG_KEYS:
            issues.append(ValidationIssue("error", "INVALID_CATALOG", "Chưa chọn danh mục hợp lệ"))
            return issues
        if not code:
            issues.append(ValidationIssue("error", "MISSING_CODE", "Mã ĐT không được để trống"))
        if not name:
            issues.append(ValidationIssue("error", "MISSING_NAME", "Tên đối tượng không được để trống"))
        if any(char in code for char in "\r\n\t"):
            issues.append(ValidationIssue("error", "INVALID_CODE", "Mã ĐT chứa ký tự không hợp lệ"))
        if not code or not name:
            return issues

        existing = self.catalogs.find(catalog, code)
        if existing and normalize_text(existing.name) != normalize_text(name):
            issues.append(
                ValidationIssue(
                    "error",
                    "EXISTING_NAME_MISMATCH",
                    f"Mã {existing.code} đã tồn tại với tên: {existing.name}",
                )
            )
        if not existing and not request.confirmed_in_vacom:
            issues.append(
                ValidationIssue(
                    "error",
                    "VACOM_NOT_CONFIRMED",
                    "Mã ĐT mới phải được xác nhận đã tạo trong VACOM",
                )
            )

        own_codes, own_names = self._own_company_values()
        if normalize_text(code) in own_codes or normalize_text(name) in own_names:
            issues.append(
                ValidationIssue(
                    "error",
                    "OWN_COMPANY",
                    "Không được thêm công ty mình làm Mã ĐT giao dịch",
                )
            )

        request_aliases: set[str] = set()
        targets = self.publisher.alias_targets()
        for alias_input in request.aliases:
            alias = alias_input.value.strip()
            alias_norm = normalize_text(alias)
            if alias_input.match_type not in MATCH_TYPES:
                issues.append(ValidationIssue("error", "INVALID_MATCH_TYPE", f"Kiểu alias không hợp lệ: {alias_input.match_type}"))
                continue
            if not alias_norm:
                issues.append(ValidationIssue("error", "EMPTY_ALIAS", "Alias không được để trống"))
                continue
            if alias_norm in request_aliases:
                issues.append(ValidationIssue("error", "DUPLICATE_ALIAS", f"Alias bị nhập trùng: {alias}"))
                continue
            request_aliases.add(alias_norm)
            if alias_norm in BLOCKED_ALIASES:
                issues.append(ValidationIssue("error", "BLOCKED_ALIAS", f"Alias quá chung và không được sử dụng: {alias}"))
            elif len(alias_norm.replace(" ", "")) <= 3:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "SHORT_ALIAS",
                        f"Alias “{alias}” ngắn, nên dùng một cụm từ đặc trưng hơn",
                    )
                )

            current_targets = targets.get(catalog, {}).get(alias_norm, [])
            for target in current_targets:
                if normalize_text(target["object_code"]) == normalize_text(code):
                    issues.append(
                        ValidationIssue(
                            "error",
                            "ALIAS_ALREADY_EXISTS",
                            f"Alias “{alias}” đã tồn tại cho Mã ĐT {target['object_code']}",
                        )
                    )
                else:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "ALIAS_COLLISION",
                            f"Alias “{alias}” đang trỏ tới Mã ĐT {target['object_code']} trong {CATALOG_DEFINITIONS[catalog].label}",
                        )
                    )
            for other_catalog in CATALOG_KEYS:
                if other_catalog == catalog:
                    continue
                other_targets = targets.get(other_catalog, {}).get(alias_norm, [])
                if other_targets:
                    codes = ", ".join(sorted({target["object_code"] for target in other_targets}))
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "CROSS_CATALOG_ALIAS",
                            f"Alias “{alias}” cũng tồn tại trong {CATALOG_DEFINITIONS[other_catalog].label}: {codes}",
                        )
                    )

        if existing and not request.aliases:
            issues.append(ValidationIssue("error", "NO_CHANGE", "Chưa nhập alias mới để áp dụng"))
        return issues

    def apply(self, request: ObjectChangeRequest) -> PublishResult:
        issues = self.validate(request)
        if any(issue.is_error for issue in issues):
            raise RuleManagerValidationError(issues)

        existing = self.catalogs.find(request.catalog, request.code)
        touched = [
            self.paths.user_rules_path,
            self.paths.object_aliases_path,
            self.paths.object_overrides_path,
        ]
        if not existing:
            touched.append(self.paths.catalog_path(request.catalog))
        backup_dir = self.backup.create(
            touched,
            metadata={
                "action": "apply_object_change",
                "catalog": request.catalog,
                "object_code": request.code,
                "object_name": request.name,
            },
        )

        changed_files: list[str] = []
        try:
            object_created = existing is None
            if object_created:
                item = ManagedObject(
                    catalog=request.catalog,
                    code=request.code.strip(),
                    name=request.name.strip(),
                    tax_code=request.tax_code.strip(),
                    address=request.address.strip(),
                    group_code=CATALOG_DEFINITIONS[request.catalog].group_code,
                )
                self.catalogs.append(item)
                changed_files.append(str(self.paths.catalog_path(request.catalog)))
                self.repository.upsert_object(
                    StoredObject(
                        catalog=request.catalog,
                        code=request.code.strip(),
                        name=request.name.strip(),
                        tax_code=request.tax_code.strip(),
                        address=request.address.strip(),
                        confirmed_in_vacom=request.confirmed_in_vacom,
                    )
                )

            for alias_input in request.aliases:
                self.repository.upsert_alias(
                    ManagedAlias(
                        catalog=request.catalog,
                        object_code=request.code.strip(),
                        alias=alias_input.value.strip(),
                        match_type=alias_input.match_type,
                        active=True,
                    )
                )
            if object_created or request.aliases:
                changed_files.append(str(self.paths.user_rules_path))
            yaml_paths = self.publisher.publish(self.repository.aliases())
            changed_files.extend(str(path) for path in yaml_paths)
        except Exception:
            self.backup.restore(backup_dir)
            raise

        return PublishResult(
            object_created=existing is None,
            aliases_changed=len(request.aliases),
            backup_dir=str(backup_dir),
            changed_files=tuple(dict.fromkeys(changed_files)),
            warnings=tuple(issue.message for issue in issues if issue.severity == "warning"),
        )

    def deactivate_alias(self, catalog: str, alias: str) -> PublishResult:
        records = self.repository.aliases()
        target = next(
            (
                record
                for record in records
                if record.catalog == catalog and normalize_text(record.alias) == normalize_text(alias)
            ),
            None,
        )
        if target is None:
            raise ValueError("Chỉ có thể ngừng alias được tạo bằng Rule Manager")
        backup_dir = self.backup.create(
            [self.paths.user_rules_path, self.paths.object_aliases_path, self.paths.object_overrides_path],
            metadata={"action": "deactivate_alias", "catalog": catalog, "alias": alias},
        )
        try:
            self.repository.upsert_alias(
                ManagedAlias(
                    catalog=target.catalog,
                    object_code=target.object_code,
                    alias=target.alias,
                    match_type=target.match_type,
                    active=False,
                    created_at=target.created_at,
                )
            )
            yaml_paths = self.publisher.publish(self.repository.aliases())
        except Exception:
            self.backup.restore(backup_dir)
            raise
        return PublishResult(
            object_created=False,
            aliases_changed=1,
            backup_dir=str(backup_dir),
            changed_files=(str(self.paths.user_rules_path), *(str(path) for path in yaml_paths)),
        )

    def restore_backup(self, backup_dir: str | Path) -> Path:
        source = Path(backup_dir)
        safety_backup = self.backup.create(
            self.backup.target_paths(source),
            metadata={"action": "before_restore", "restore_source": str(source)},
        )
        self.backup.restore(source)
        return safety_backup

    def _own_company_values(self) -> tuple[set[str], set[str]]:
        if not self.paths.own_company_path.exists():
            return set(), set()
        with self.paths.own_company_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        section = data.get("own_company", {}) if isinstance(data, dict) else {}
        codes = {normalize_text(value) for value in section.get("object_codes", []) or []}
        names = {normalize_text(value) for value in section.get("aliases", []) or []}
        return codes, names
