from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


class ChangeBackup:
    def __init__(self, project_root: Path, backup_root: Path):
        self.project_root = project_root.resolve()
        self.backup_root = backup_root.resolve()

    def create(self, paths: Iterable[Path], metadata: dict | None = None) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = self.backup_root / timestamp
        destination.mkdir(parents=True, exist_ok=False)
        try:
            manifest: list[dict[str, object]] = []
            for source in dict.fromkeys(Path(path).resolve() for path in paths):
                relative = self._relative_path(source)
                existed = source.exists()
                backup_path = destination / relative
                if existed:
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, backup_path)
                manifest.append({"path": str(relative).replace("\\", "/"), "existed": existed})

            payload = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "files": manifest,
                "metadata": metadata or {},
            }
            (destination / "manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

        self._remove_older_backups(destination)
        return destination

    def restore_with_safety_backup(self, backup_dir: str | Path) -> Path:
        """Restore one snapshot while retaining only the pre-restore state."""
        source = Path(backup_dir).resolve()
        targets = self.target_paths(source)
        self.backup_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".rule_restore_", dir=self.backup_root.parent) as temporary_dir:
            preserved_source = Path(temporary_dir) / "source"
            shutil.copytree(source, preserved_source)
            safety_backup = self.create(
                targets,
                metadata={"action": "before_restore", "restore_source": str(source)},
            )
            try:
                self.restore(preserved_source)
            except Exception:
                self.restore(safety_backup)
                raise
        return safety_backup

    def restore(self, backup_dir: str | Path) -> None:
        backup_path = Path(backup_dir)
        manifest_path = backup_path / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in payload.get("files", []):
            relative = Path(str(item["path"]))
            target = (self.project_root / relative).resolve()
            self._assert_under_root(target)
            source = backup_path / relative
            if bool(item.get("existed", False)):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()

    def target_paths(self, backup_dir: str | Path) -> list[Path]:
        backup_path = Path(backup_dir)
        payload = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
        targets: list[Path] = []
        for item in payload.get("files", []):
            target = (self.project_root / Path(str(item["path"]))).resolve()
            self._assert_under_root(target)
            targets.append(target)
        return targets

    def _relative_path(self, path: Path) -> Path:
        self._assert_under_root(path)
        return path.relative_to(self.project_root)

    def _remove_older_backups(self, current: Path) -> None:
        for candidate in self.backup_root.iterdir():
            if candidate != current and candidate.is_dir():
                shutil.rmtree(candidate)

    def _assert_under_root(self, path: Path) -> None:
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Không được backup/restore file ngoài project: {path}") from exc
