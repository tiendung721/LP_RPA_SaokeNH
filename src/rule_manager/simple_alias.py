from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import uuid
from typing import Any


@dataclass(frozen=True)
class ManagedTextAlias:
    record_id: str
    value: str
    active: bool = True
    deleted: bool = False
    source: str = "user"
    original_value: str = ""
    previous_values: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagedTextAlias":
        text = str(value.get("value", "") or "").strip()
        return cls(
            record_id=str(value.get("record_id", "") or f"user:{uuid.uuid4().hex}"),
            value=text,
            active=bool(value.get("active", True)),
            deleted=bool(value.get("deleted", False)),
            source=str(value.get("source", "user") or "user"),
            original_value=str(value.get("original_value", "") or text).strip(),
            previous_values=tuple(
                str(item).strip() for item in value.get("previous_values", []) or [] if str(item).strip()
            ),
        )

    @classmethod
    def from_config(cls, parent_key: str, value: str) -> "ManagedTextAlias":
        text = str(value or "").strip()
        payload = f"{parent_key}|{text}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
        return cls(
            record_id=f"config:{digest}",
            value=text,
            source="config",
            original_value=text,
        )

    @classmethod
    def new_user(cls, value: str) -> "ManagedTextAlias":
        text = str(value or "").strip()
        return cls(
            record_id=f"user:{uuid.uuid4().hex}",
            value=text,
            source="user",
            original_value=text,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def active_value(self) -> str:
        return self.value.strip() if self.active and not self.deleted else ""
