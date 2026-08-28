from __future__ import annotations

from pathlib import Path

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
