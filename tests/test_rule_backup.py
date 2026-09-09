from __future__ import annotations

from pathlib import Path
from datetime import datetime

import src.rule_manager.backup as backup_module
from src.rule_manager.backup import ChangeBackup


def test_new_backup_replaces_every_older_backup(tmp_path: Path) -> None:
    target = tmp_path / "config" / "rules.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("version: 1\n", encoding="utf-8")
    backup = ChangeBackup(tmp_path, tmp_path / "backup" / "rule_manager")

    first = backup.create([target])
    target.write_text("version: 2\n", encoding="utf-8")
    second = backup.create([target])

    assert not first.exists()
    assert [path for path in backup.backup_root.iterdir() if path.is_dir()] == [second]
    assert (second / "config" / "rules.yaml").read_text(encoding="utf-8") == "version: 2\n"


def test_restore_preserves_only_pre_restore_state_as_latest_backup(tmp_path: Path) -> None:
    target = tmp_path / "config" / "rules.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("version: 1\n", encoding="utf-8")
    backup = ChangeBackup(tmp_path, tmp_path / "backup" / "rule_manager")
    source = backup.create([target])
    target.write_text("version: 2\n", encoding="utf-8")

    safety = backup.restore_with_safety_backup(source)

    assert target.read_text(encoding="utf-8") == "version: 1\n"
    assert [path for path in backup.backup_root.iterdir() if path.is_dir()] == [safety]
    assert (safety / "config" / "rules.yaml").read_text(encoding="utf-8") == "version: 2\n"


def test_backup_names_do_not_collide_with_the_same_microsecond(tmp_path: Path, monkeypatch) -> None:
    class FrozenDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 6, 1, 8, 30, 15, 123456)

    monkeypatch.setattr(backup_module, "datetime", FrozenDateTime)
    target = tmp_path / "config" / "rules.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("version: 1\n", encoding="utf-8")
    backup = ChangeBackup(tmp_path, tmp_path / "backup" / "rule_manager")

    first = backup.create([target])
    second = backup.create([target])

    assert first.name == "20260601_083015_123456"
    assert second.name == "20260601_083015_123456_1"
    assert second.exists()
