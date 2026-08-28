from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import uuid
from typing import Any


CATALOG_RECEIVABLE = "receivable"
CATALOG_PAYABLE = "payable"
CATALOG_INTERNAL = "internal"
CATALOG_KEYS = (CATALOG_RECEIVABLE, CATALOG_PAYABLE, CATALOG_INTERNAL)

MATCH_ALIAS = "alias"
MATCH_EXACT_PHRASE = "exact_phrase"
MATCH_TYPES = (MATCH_EXACT_PHRASE, MATCH_ALIAS)


@dataclass(frozen=True)
class CatalogDefinition:
    key: str
    label: str
    filename: str
    group_code: str
    group_name: str
    unit: str = "VP"
    tcvn3_text: bool = False


CATALOG_DEFINITIONS: dict[str, CatalogDefinition] = {
    CATALOG_RECEIVABLE: CatalogDefinition(
        key=CATALOG_RECEIVABLE,
        label="Phải thu",
        filename="R_DMDT1 1.xlsx",
        group_code="PHAITHU",
        group_name="Phải thu của khách hàng",
    ),
    CATALOG_PAYABLE: CatalogDefinition(
        key=CATALOG_PAYABLE,
        label="Phải trả",
        filename="R_DMDT1.xlsx",
        group_code="PHAITRA",
        group_name="Phải trả nhà cung cấp",
    ),
    CATALOG_INTERNAL: CatalogDefinition(
        key=CATALOG_INTERNAL,
        label="Nội bộ",
        filename="MA NOI BO CTY.xlsx",
        group_code="NB",
        group_name="Nội bộ công ty",
        tcvn3_text=True,
    ),
}


@dataclass(frozen=True)
class ManagedObject:
    catalog: str
    code: str
    name: str
    tax_code: str = ""
    address: str = ""
    group_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AliasInput:
    value: str
    match_type: str = MATCH_EXACT_PHRASE


@dataclass(frozen=True)
class ManagedAlias:
    record_id: str
    catalog: str
    object_code: str
    alias: str
    match_type: str = MATCH_EXACT_PHRASE
    active: bool = True
    deleted: bool = False
    source: str = "user"
    original_alias: str = ""
    previous_aliases: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagedAlias":
        catalog = str(value.get("catalog", "") or "").strip()
        object_code = str(value.get("object_code", "") or "").strip()
        alias = str(value.get("alias", "") or "").strip()
        match_type = str(value.get("match_type", MATCH_EXACT_PHRASE) or MATCH_EXACT_PHRASE).strip()
        source = str(value.get("source", "user") or "user").strip()
        record_id = str(value.get("record_id", "") or "").strip()
        if not record_id:
            record_id = cls.make_record_id(source, catalog, object_code, alias, match_type)
        return cls(
            record_id=record_id,
            catalog=catalog,
            object_code=object_code,
            alias=alias,
            match_type=match_type,
            active=bool(value.get("active", True)),
            deleted=bool(value.get("deleted", False)),
            source=source,
            original_alias=str(value.get("original_alias", "") or alias).strip(),
            previous_aliases=tuple(str(item).strip() for item in value.get("previous_aliases", []) or [] if str(item).strip()),
            created_at=str(value.get("created_at", "") or "").strip(),
            updated_at=str(value.get("updated_at", "") or "").strip(),
        )

    @classmethod
    def new_user(cls, catalog: str, object_code: str, alias: str, match_type: str) -> "ManagedAlias":
        return cls(
            record_id=f"user:{uuid.uuid4().hex}",
            catalog=catalog,
            object_code=object_code,
            alias=alias,
            match_type=match_type,
            active=True,
            deleted=False,
            source="user",
            original_alias=alias,
        )

    @classmethod
    def from_config(cls, catalog: str, object_code: str, alias: str, match_type: str) -> "ManagedAlias":
        return cls(
            record_id=cls.make_record_id("config", catalog, object_code, alias, match_type),
            catalog=catalog,
            object_code=object_code,
            alias=alias,
            match_type=match_type,
            active=True,
            deleted=False,
            source="config",
            original_alias=alias,
        )

    @staticmethod
    def make_record_id(source: str, catalog: str, object_code: str, alias: str, match_type: str) -> str:
        payload = "|".join((source, catalog, object_code, alias, match_type))
        return f"{source}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:20]}"

    @property
    def aliases_to_remove(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.original_alias, *self.previous_aliases, self.alias)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoredObject:
    catalog: str
    code: str
    name: str
    tax_code: str = ""
    address: str = ""
    confirmed_in_vacom: bool = False
    active: bool = True
    deleted: bool = False
    created_by_user: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StoredObject":
        return cls(
            catalog=str(value.get("catalog", "") or "").strip(),
            code=str(value.get("code", "") or "").strip(),
            name=str(value.get("name", "") or "").strip(),
            tax_code=str(value.get("tax_code", "") or "").strip(),
            address=str(value.get("address", "") or "").strip(),
            confirmed_in_vacom=bool(value.get("confirmed_in_vacom", False)),
            active=bool(value.get("active", True)),
            deleted=bool(value.get("deleted", False)),
            # Before object pausing existed, records were only written when the
            # user created a new object. Preserve that meaning for schema v2.
            created_by_user=bool(value.get("created_by_user", True)),
            created_at=str(value.get("created_at", "") or "").strip(),
            updated_at=str(value.get("updated_at", "") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObjectChangeRequest:
    catalog: str
    code: str
    name: str
    tax_code: str = ""
    address: str = ""
    confirmed_in_vacom: bool = False
    aliases: tuple[AliasInput, ...] = field(default_factory=tuple)
    alias_changes: tuple[ManagedAlias, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True)
class PublishResult:
    object_created: bool
    aliases_changed: int
    backup_dir: str
    changed_files: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
