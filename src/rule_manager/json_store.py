from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AtomicJsonStore:
    def __init__(self, path: str | Path, collection: str):
        self.path = Path(path)
        self.collection = collection

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, self.collection: []}
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError(f"Dữ liệu quản lý không hợp lệ: {self.path}")
        return {
            "version": int(raw.get("version", 1) or 1),
            self.collection: list(raw.get(self.collection, []) or []),
        }

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.stem}.", suffix=self.path.suffix, dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
