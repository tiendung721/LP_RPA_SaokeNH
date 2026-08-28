from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest
import yaml

from src.rule_manager.paths import RuleManagerPaths
from src.rule_manager.payment_service import PaymentRuleManagerService, PaymentValidationError
from src.rule_manager.simple_alias import ManagedTextAlias


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> PaymentRuleManagerService:
    (tmp_path / "config").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "config" / "reason_aliases.yaml", tmp_path / "config" / "reason_aliases.yaml")
    return PaymentRuleManagerService(RuleManagerPaths.from_project_root(tmp_path))


def test_loads_all_current_payment_purposes(tmp_path):
    service = _service(tmp_path)
    assert len(service.list_purposes()) == 52


def test_edit_existing_payment_purpose_preserves_code_and_hidden_sections(tmp_path):
    service = _service(tmp_path)
    current = service.list_purposes()[0]
    before = yaml.safe_load(service.paths.reason_aliases_path.read_text(encoding="utf-8"))
    edited = replace(
        current,
        label=current.label + " cập nhật",
        aliases=current.aliases + (ManagedTextAlias.new_user("ALIAS THANH TOAN DOC NHAT"),),
    )

    result = service.apply(edited)

    after = yaml.safe_load(service.paths.reason_aliases_path.read_text(encoding="utf-8"))
    stored = next(item for item in service.list_purposes() if item.code == current.code)
    assert stored.code == current.code
    assert stored.label.endswith("cập nhật")
    assert "ALIAS THANH TOAN DOC NHAT" in stored.active_aliases
    assert after["object_name_purposes"] == before["object_name_purposes"]
    assert after["object_purpose_defaults"] == before["object_purpose_defaults"]
    assert Path(result.backup_dir, "config", "reason_aliases.yaml").exists()


def test_new_payment_purpose_gets_stable_unique_code(tmp_path):
    service = _service(tmp_path)
    first = service.new_record("Phí thử nghiệm", (ManagedTextAlias.new_user("PHI THU NGHIEM MOT"),))
    service.apply(first)
    second = service.new_record("Phí thử nghiệm", (ManagedTextAlias.new_user("PHI THU NGHIEM HAI"),))

    assert first.code == "phi_thu_nghiem"
    assert second.code == "phi_thu_nghiem_2"


def test_payment_alias_collision_and_generic_alias_are_blocked(tmp_path):
    service = _service(tmp_path)
    current = service.list_purposes()[0]
    collision = service.new_record("Loại mới", (ManagedTextAlias.new_user(current.active_aliases[0]),))
    generic = service.new_record("Loại khác", (ManagedTextAlias.new_user("PHI"),))

    assert any(issue.code == "ALIAS_COLLISION" for issue in service.validate(collision))
    assert any(issue.code == "BLOCKED_ALIAS" for issue in service.validate(generic))
    with pytest.raises(PaymentValidationError):
        service.apply(generic)


def test_payment_publish_failure_restores_files(tmp_path, monkeypatch):
    service = _service(tmp_path)
    original_yaml = service.paths.reason_aliases_path.read_bytes()
    record = service.new_record("Phí rollback", (ManagedTextAlias.new_user("PHI ROLLBACK DOC NHAT"),))

    def fail_publish(_records):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(service.publisher, "publish", fail_publish)
    with pytest.raises(RuntimeError):
        service.apply(record)

    assert service.paths.reason_aliases_path.read_bytes() == original_yaml
    assert not service.paths.payment_rules_path.exists()
