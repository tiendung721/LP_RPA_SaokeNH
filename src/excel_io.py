from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


@contextmanager
def atomic_output_path(path: str | Path) -> Iterator[Path]:
    """Yield a sibling temporary .xlsx path and atomically replace the target."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=target.suffix,
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def backup_legacy_workbook_once(path: str | Path, backup_dir: str | Path) -> Path | None:
    """Create the single pre-simplification backup used by summary migration."""
    source = Path(path)
    if not source.exists():
        return None

    destination_dir = Path(backup_dir)
    existing = sorted(destination_dir.glob("rpa_summary_before_simplify_*.xlsx")) if destination_dir.exists() else []
    if existing:
        return existing[0]

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"rpa_summary_before_simplify_{timestamp}.xlsx"
    shutil.copy2(source, destination)
    return destination
