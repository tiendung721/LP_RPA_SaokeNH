from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import uuid
from typing import Any

from .simple_alias import ManagedTextAlias


@dataclass(frozen=True)
class ManagedPaymentPurpose:
    record_id: str
    code: str
    label: str
    aliases: tuple[ManagedTextAlias, ...] = field(default_factory=tuple)
    active: bool = True
    deleted: bool = False
    source: str = "user"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagedPaymentPurpose":
        return cls(
            record_id=str(value.get("record_id", "") or f"user:{uuid.uuid4().hex}"),
            code=str(value.get("code", "") or "").strip(),
            label=str(value.get("label", "") or "").strip(),
            aliases=tuple(
                ManagedTextAlias.from_dict(item)
                for item in value.get("aliases", []) or []
                if isinstance(item, dict)
            ),
            active=bool(value.get("active", True)),
            deleted=bool(value.get("deleted", False)),
            source=str(value.get("source", "user") or "user"),
            created_at=str(value.get("created_at", "") or ""),
            updated_at=str(value.get("updated_at", "") or ""),
        )

    @classmethod
    def from_config(cls, code: str, label: str, aliases: list[str]) -> "ManagedPaymentPurpose":
        clean_code = str(code or "").strip()
        digest = hashlib.sha1(clean_code.encode("utf-8")).hexdigest()[:20]
        return cls(
            record_id=f"config:{digest}",
            code=clean_code,
            label=str(label or "").strip(),
            aliases=tuple(ManagedTextAlias.from_config(clean_code, alias) for alias in aliases),
            source="config",
        )

    @classmethod
    def new_user(cls, code: str, label: str, aliases: tuple[ManagedTextAlias, ...]) -> "ManagedPaymentPurpose":
        return cls(
            record_id=f"user:{uuid.uuid4().hex}",
            code=code,
            label=label,
            aliases=aliases,
            source="user",
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["aliases"] = [alias.to_dict() for alias in self.aliases]
        return value

    @property
    def active_aliases(self) -> tuple[str, ...]:
        return tuple(value for alias in self.aliases if (value := alias.active_value))


@dataclass(frozen=True)
class PaymentPublishResult:
    backup_dir: str
    changed_files: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
