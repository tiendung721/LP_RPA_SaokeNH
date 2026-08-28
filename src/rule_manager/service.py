from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import yaml

from src.normalizer import normalize_text
from src.object_matcher import ObjectMatcher

from .backup import ChangeBackup
from .catalogs import ObjectCatalogStore
from .models import (
    CATALOG_DEFINITIONS,
    CATALOG_KEYS,
    MATCH_ALIAS,
    MATCH_EXACT_PHRASE,
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

_TRANSACTION_ALIAS_PHRASES = (
    "CT CHO",
    "CK CHO",
    "CHUYEN CHO",
    "THANH TOAN",
    "TRA TIEN",
    "NOP TIEN",
    "TAM UNG",
    "HOAN UNG",
    "CONG NO",
    "HOA DON",
    "TAX CODE",
    "PAYMENT",
    "INVOICE",
)


class RuleManagerValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues if issue.is_error))


@dataclass(frozen=True)
class ObjectListRow:
    object: ManagedObject
    alias_count: int
    active: bool = True
    deletable: bool = False


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
        stored = {
            normalize_text(item.code): item
            for item in self.repository.objects()
            if item.catalog == catalog
        }
        return [
            ObjectListRow(
                item,
                counts.get(normalize_text(item.code), 0),
                active=stored.get(normalize_text(item.code), StoredObject(catalog, item.code, item.name)).active,
                deletable=bool(
                    stored.get(normalize_text(item.code))
                    and stored[normalize_text(item.code)].created_by_user
                ),
            )
            for item in self.catalogs.list_objects(catalog)
        ]

    def aliases_for_object(self, catalog: str, object_code: str) -> list[ManagedAlias]:
        """Return both configuration aliases and aliases managed by the UI."""
        code_norm = normalize_text(object_code)
        managed = [
            record
            for record in self.repository.aliases()
            if record.catalog == catalog and normalize_text(record.object_code) == code_norm
        ]
        rows: list[ManagedAlias] = []
        seen_ids: set[str] = set()

        for row in self.publisher.aliases_for_object(catalog, object_code):
            alias_norm = row["alias_norm"]
            record = next(
                (
                    item
                    for item in managed
                    if not item.deleted
                    and any(normalize_text(value) == alias_norm for value in item.aliases_to_remove)
                ),
                None,
            )
            if record is None:
                record = ManagedAlias.from_config(
                    catalog,
                    object_code,
                    row["alias"],
                    row["match_type"],
                )
            if record.record_id in seen_ids:
                continue
            rows.append(record)
            seen_ids.add(record.record_id)

        for record in managed:
            if record.record_id in seen_ids or record.deleted:
                continue
            rows.append(record)
            seen_ids.add(record.record_id)

        return sorted(rows, key=lambda row: (not row.active, normalize_text(row.alias)))

    def classify_alias(self, catalog: str, object_code: str, object_name: str, alias: str) -> str:
        """Choose the safest backend match type without exposing it in the UI."""
        alias_norm = normalize_text(alias)
        compact = alias_norm.replace(" ", "")
        if (
            not alias_norm
            or len(compact) <= 4
            or any(char.isdigit() for char in compact)
            or any(_contains_phrase(alias_norm, phrase) for phrase in _TRANSACTION_ALIAS_PHRASES)
        ):
            return MATCH_EXACT_PHRASE

        objects = self.catalogs.list_objects(catalog)
        if not any(normalize_text(item.code) == normalize_text(object_code) for item in objects):
            objects.append(
                ManagedObject(
                    catalog=catalog,
                    code=object_code,
                    name=object_name,
                )
            )
        matcher = ObjectMatcher.from_records(
            [
                {
                    "code": item.code,
                    "name": item.name,
                    "tax_code": item.tax_code,
                    "address": item.address,
                    "group_code": item.group_code,
                }
                for item in objects
            ],
            aliases={object_code: [alias_norm]},
        )
        audit = matcher.alias_audit_records(catalog)
        if not audit or audit[0]["risk"] != "ok":
            return MATCH_EXACT_PHRASE
        hit_codes = {
            normalize_text(code)
            for code in str(audit[0]["hit_codes"]).split(", ")
            if code.strip()
        }
        if normalize_text(object_code) not in hit_codes:
            return MATCH_EXACT_PHRASE
        return MATCH_ALIAS

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

        own_codes, own_names = self._own_company_values()
        if normalize_text(code) in own_codes or normalize_text(name) in own_names:
            issues.append(
                ValidationIssue(
                    "error",
                    "OWN_COMPANY",
                    "Không được thêm công ty mình làm Mã ĐT giao dịch",
                )
            )

        candidates: list[tuple[str, ManagedAlias | None]] = [
            (item.value.strip(), None) for item in request.aliases
        ]
        for record in request.alias_changes:
            if record.catalog != catalog or normalize_text(record.object_code) != normalize_text(code):
                issues.append(
                    ValidationIssue(
                        "error",
                        "INVALID_ALIAS_TARGET",
                        f"Alias “{record.alias}” không thuộc Mã ĐT đang chọn",
                    )
                )
                continue
            if not record.deleted and record.active:
                candidates.append((record.alias.strip(), record))

        requested_aliases: set[str] = set()
        targets = self.publisher.alias_targets()
        for alias, managed_change in candidates:
            alias_norm = normalize_text(alias)
            if not alias_norm:
                issues.append(ValidationIssue("error", "EMPTY_ALIAS", "Alias không được để trống"))
                continue
            if alias_norm in requested_aliases:
                issues.append(ValidationIssue("error", "DUPLICATE_ALIAS", f"Alias bị nhập trùng: {alias}"))
                continue
            requested_aliases.add(alias_norm)
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

            removable = {
                normalize_text(value)
                for value in (
                    (managed_change.original_alias, *managed_change.previous_aliases)
                    if managed_change
                    else ()
                )
            }
            for target in targets.get(catalog, {}).get(alias_norm, []):
                same_object = normalize_text(target["object_code"]) == normalize_text(code)
                if managed_change is not None and same_object and alias_norm in removable:
                    continue
                issue_code = "ALIAS_ALREADY_EXISTS" if same_object else "ALIAS_COLLISION"
                if same_object:
                    message = f"Alias “{alias}” đã tồn tại cho Mã ĐT {target['object_code']}"
                else:
                    message = (
                        f"Alias “{alias}” đang trỏ tới Mã ĐT {target['object_code']} "
                        f"trong {CATALOG_DEFINITIONS[catalog].label}"
                    )
                issues.append(ValidationIssue("error", issue_code, message))

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

        if existing and not request.aliases and not request.alias_changes:
            issues.append(ValidationIssue("error", "NO_CHANGE", "Chưa có thay đổi để áp dụng"))
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
                    group_code=CATALOG_DEFINITIONS[request.catalog].group_code,
                )
                self.catalogs.append(item)
                changed_files.append(str(self.paths.catalog_path(request.catalog)))
                self.repository.upsert_object(
                    StoredObject(
                        catalog=request.catalog,
                        code=request.code.strip(),
                        name=request.name.strip(),
                        deleted=False,
                        created_by_user=True,
                    )
                )

            for alias_input in request.aliases:
                match_type = self.classify_alias(
                    request.catalog,
                    request.code.strip(),
                    request.name.strip(),
                    alias_input.value,
                )
                self.repository.upsert_alias(
                    ManagedAlias.new_user(
                        request.catalog,
                        request.code.strip(),
                        alias_input.value.strip(),
                        match_type,
                    )
                )
            for record in request.alias_changes:
                if record.active and not record.deleted:
                    record = replace(
                        record,
                        match_type=self.classify_alias(
                            request.catalog,
                            request.code.strip(),
                            request.name.strip(),
                            record.alias,
                        ),
                    )
                self.repository.upsert_alias(record)

            if object_created or request.aliases or request.alias_changes:
                changed_files.append(str(self.paths.user_rules_path))
            yaml_paths = self.publisher.publish(self.repository.aliases(), self.repository.objects())
            changed_files.extend(str(path) for path in yaml_paths)
        except Exception:
            self.backup.restore(backup_dir)
            raise

        return PublishResult(
            object_created=existing is None,
            aliases_changed=len(request.aliases) + len(request.alias_changes),
            backup_dir=str(backup_dir),
            changed_files=tuple(dict.fromkeys(changed_files)),
            warnings=tuple(issue.message for issue in issues if issue.severity == "warning"),
        )

    def set_object_active(self, catalog: str, code: str, active: bool) -> PublishResult:
        existing = self.catalogs.find(catalog, code)
        if existing is None:
            raise ValueError(f"Không tìm thấy Mã ĐT {code}")
        current = next(
            (
                item
                for item in self.repository.objects()
                if item.catalog == catalog and normalize_text(item.code) == normalize_text(code)
            ),
            None,
        )
        if current and current.active == active:
            raise ValueError("Mã ĐT đã ở trạng thái yêu cầu")

        backup_dir = self.backup.create(
            [self.paths.user_rules_path, self.paths.object_overrides_path],
            metadata={
                "action": "set_object_active",
                "catalog": catalog,
                "object_code": existing.code,
                "active": active,
            },
        )
        try:
            self.repository.upsert_object(
                StoredObject(
                    catalog=catalog,
                    code=existing.code,
                    name=existing.name,
                    tax_code=existing.tax_code,
                    address=existing.address,
                    active=active,
                    deleted=False,
                    created_by_user=current.created_by_user if current else False,
                    created_at=current.created_at if current else "",
                )
            )
            self.publisher.publish(self.repository.aliases(), self.repository.objects())
        except Exception:
            self.backup.restore(backup_dir)
            raise
        return PublishResult(
            object_created=False,
            aliases_changed=0,
            backup_dir=str(backup_dir),
            changed_files=(str(self.paths.user_rules_path), str(self.paths.object_overrides_path)),
        )

    def delete_object(self, catalog: str, code: str) -> PublishResult:
        existing = self.catalogs.find(catalog, code)
        if existing is None:
            raise ValueError(f"Không tìm thấy Mã ĐT {code}")
        stored = next(
            (
                item
                for item in self.repository.objects()
                if item.catalog == catalog and normalize_text(item.code) == normalize_text(code)
            ),
            None,
        )
        if stored is None or not stored.created_by_user:
            raise RuleManagerValidationError(
                [ValidationIssue("error", "BUILTIN_OBJECT_READ_ONLY", "Chỉ được xóa Mã ĐT được thêm từ màn hình này")]
            )
        references = self._object_references(code)
        if references:
            raise RuleManagerValidationError(
                [
                    ValidationIssue(
                        "error",
                        "OBJECT_IN_USE",
                        "Mã ĐT đang được cấu hình tham chiếu tại: " + ", ".join(references),
                    )
                ]
            )

        matching_aliases = [
            item
            for item in self.repository.aliases()
            if item.catalog == catalog and normalize_text(item.object_code) == normalize_text(code)
        ]
        touched = [
            self.paths.user_rules_path,
            self.paths.object_aliases_path,
            self.paths.object_overrides_path,
            self.paths.catalog_path(catalog),
        ]
        backup_dir = self.backup.create(
            touched,
            metadata={"action": "delete_object", "catalog": catalog, "object_code": existing.code},
        )
        try:
            self.catalogs.remove(catalog, existing.code)
            self.repository.remove_object(catalog, existing.code)
            self.repository.upsert_object(
                StoredObject(
                    catalog=catalog,
                    code=existing.code,
                    name=existing.name,
                    tax_code=existing.tax_code,
                    address=existing.address,
                    active=False,
                    deleted=True,
                    created_by_user=True,
                    created_at=stored.created_at,
                )
            )
            self.publisher.publish(
                self.repository.aliases(),
                self.repository.objects(),
                removed_objects=((catalog, existing.code),),
            )
        except Exception:
            self.backup.restore(backup_dir)
            raise
        return PublishResult(
            object_created=False,
            aliases_changed=len(matching_aliases),
            backup_dir=str(backup_dir),
            changed_files=tuple(str(path) for path in touched),
        )

    def _object_references(self, code: str) -> list[str]:
        code_norm = normalize_text(code)
        references: list[str] = []
        config_path = self.paths.config_dir / "config.yaml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if any(normalize_text(value) == code_norm for value in (data.get("bank_object_codes", {}) or {}).values()):
                references.append("config/config.yaml → bank_object_codes")
        if self.paths.default_rules_path.exists():
            data = yaml.safe_load(self.paths.default_rules_path.read_text(encoding="utf-8")) or {}
            for item in data.get("rules", []) or []:
                if not isinstance(item, dict):
                    continue
                if any(normalize_text(item.get(key)) == code_norm for key in ("default_object_code", "forced_object_code")):
                    references.append("config/default_rules.yaml")
                    break
        if self.paths.reason_aliases_path.exists():
            data = yaml.safe_load(self.paths.reason_aliases_path.read_text(encoding="utf-8")) or {}
            if any(normalize_text(key) == code_norm for key in (data.get("object_purpose_defaults", {}) or {})):
                references.append("config/reason_aliases.yaml → object_purpose_defaults")
        if self.paths.own_company_path.exists():
            data = yaml.safe_load(self.paths.own_company_path.read_text(encoding="utf-8")) or {}
            own = data.get("own_company", {}) if isinstance(data, dict) else {}
            if any(normalize_text(value) == code_norm for value in own.get("object_codes", []) or []):
                references.append("config/own_company.yaml")
        return references

    def deactivate_alias(self, catalog: str, alias: str) -> PublishResult:
        """Compatibility helper for callers predating the batch UI."""
        target = next(
            (
                record
                for record in self.repository.aliases()
                if record.catalog == catalog and normalize_text(record.alias) == normalize_text(alias)
            ),
            None,
        )
        if target is None:
            raise ValueError("Không tìm thấy alias do người dùng quản lý")
        existing = self.catalogs.find(catalog, target.object_code)
        if existing is None:
            raise ValueError(f"Không tìm thấy Mã ĐT {target.object_code}")
        return self.apply(
            ObjectChangeRequest(
                catalog=catalog,
                code=existing.code,
                name=existing.name,
                alias_changes=(replace(target, active=False, deleted=False),),
            )
        )

    def restore_backup(self, backup_dir: str | Path) -> Path:
        return self.backup.restore_with_safety_backup(backup_dir)

    def _own_company_values(self) -> tuple[set[str], set[str]]:
        if not self.paths.own_company_path.exists():
            return set(), set()
        with self.paths.own_company_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        section = data.get("own_company", {}) if isinstance(data, dict) else {}
        codes = {normalize_text(value) for value in section.get("object_codes", []) or []}
        names = {normalize_text(value) for value in section.get("aliases", []) or []}
        return codes, names


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "
