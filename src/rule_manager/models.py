from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    catalog: str
    object_code: str
    alias: str
    match_type: str = MATCH_EXACT_PHRASE
    active: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagedAlias":
        return cls(
            catalog=str(value.get("catalog", "") or "").strip(),
            object_code=str(value.get("object_code", "") or "").strip(),
            alias=str(value.get("alias", "") or "").strip(),
            match_type=str(value.get("match_type", MATCH_EXACT_PHRASE) or MATCH_EXACT_PHRASE).strip(),
            active=bool(value.get("active", True)),
            created_at=str(value.get("created_at", "") or "").strip(),
            updated_at=str(value.get("updated_at", "") or "").strip(),
        )

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

