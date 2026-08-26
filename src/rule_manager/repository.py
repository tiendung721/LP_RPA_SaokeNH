from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.normalizer import normalize_text

from .models import ManagedAlias, StoredObject


SCHEMA_VERSION = 1


class UserRuleRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError(f"Dữ liệu rule user không hợp lệ: {self.path}")
        return {
            "version": int(raw.get("version", SCHEMA_VERSION) or SCHEMA_VERSION),
            "objects": list(raw.get("objects", []) or []),
            "aliases": list(raw.get("aliases", []) or []),
        }

    def objects(self) -> list[StoredObject]:
        return [StoredObject.from_dict(item) for item in self.load()["objects"] if isinstance(item, dict)]

    def aliases(self) -> list[ManagedAlias]:
        return [ManagedAlias.from_dict(item) for item in self.load()["aliases"] if isinstance(item, dict)]

    def upsert_object(self, record: StoredObject) -> None:
        data = self.load()
        records = [StoredObject.from_dict(item) for item in data["objects"] if isinstance(item, dict)]
        key = self._object_key(record.catalog, record.code)
        now = self._now()
        updated: list[StoredObject] = []
        found = False
        for current in records:
            if self._object_key(current.catalog, current.code) != key:
                updated.append(current)
                continue
            found = True
            updated.append(
                StoredObject(
                    catalog=record.catalog,
                    code=record.code,
                    name=record.name,
                    tax_code=record.tax_code,
                    address=record.address,
                    confirmed_in_vacom=record.confirmed_in_vacom,
                    active=record.active,
                    created_at=current.created_at or now,
                    updated_at=now,
                )
            )
        if not found:
            updated.append(
                StoredObject(
                    **{
                        **record.to_dict(),
                        "created_at": record.created_at or now,
                        "updated_at": now,
                    }
                )
            )
        data["objects"] = [item.to_dict() for item in updated]
        self.save(data)

    def upsert_alias(self, record: ManagedAlias) -> None:
        data = self.load()
        records = [ManagedAlias.from_dict(item) for item in data["aliases"] if isinstance(item, dict)]
        key = self._alias_key(record.catalog, record.alias)
        now = self._now()
        updated: list[ManagedAlias] = []
        found = False
        for current in records:
            if self._alias_key(current.catalog, current.alias) != key:
                updated.append(current)
                continue
            found = True
            updated.append(
                ManagedAlias(
                    catalog=record.catalog,
                    object_code=record.object_code,
                    alias=record.alias,
                    match_type=record.match_type,
                    active=record.active,
                    created_at=current.created_at or now,
                    updated_at=now,
                )
            )
        if not found:
            updated.append(
                ManagedAlias(
                    **{
                        **record.to_dict(),
                        "created_at": record.created_at or now,
                        "updated_at": now,
                    }
                )
            )
        data["aliases"] = [item.to_dict() for item in updated]
        self.save(data)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.stem}.",
            suffix=self.path.suffix,
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"version": SCHEMA_VERSION, "objects": [], "aliases": []}

    @staticmethod
    def _object_key(catalog: str, code: str) -> tuple[str, str]:
        return catalog.strip(), normalize_text(code)

    @staticmethod
    def _alias_key(catalog: str, alias: str) -> tuple[str, str]:
        return catalog.strip(), normalize_text(alias)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
