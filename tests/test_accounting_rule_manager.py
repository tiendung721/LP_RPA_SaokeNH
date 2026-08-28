from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest
import yaml

from src.config_loader import load_rules
from src.rule_engine import RuleEngine
from src.rule_manager.accounting_models import CASH_FLOWS
from src.rule_manager.accounting_publisher import _object_policy
from src.rule_manager.accounting_service import AccountingRuleManagerService, AccountingValidationError
from src.rule_manager.paths import RuleManagerPaths
from src.rule_manager.simple_alias import ManagedTextAlias


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> AccountingRuleManagerService:
    (tmp_path / "config").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "config" / "default_rules.yaml", tmp_path / "config" / "default_rules.yaml")
    return AccountingRuleManagerService(RuleManagerPaths.from_project_root(tmp_path))


def test_lists_68_builtin_rules_as_read_only(tmp_path):
    service = _service(tmp_path)
    rows = service.list_rules()
    assert len(rows) == 68
    assert all(not row.editable for row in rows)


def test_add_user_rule_and_publish_backend_schema(tmp_path):
    service = _service(tmp_path)
    record = service.new_record(
        "Trả phí thử nghiệm",
        "331",
        "bao_no",
        (ManagedTextAlias.new_user("PHI THU NGHIEM KE TOAN DOC NHAT"),),
    )

    result = service.apply(record)

    rules, _ = load_rules(None, service.paths.default_rules_path)
    published = next(rule for rule in rules if rule.rule_id == record.rule_id)
    assert published.flow == "bao_no"
    assert published.account == "331"
    assert published.priority == 5
    assert published.direction == "money_out"
    assert published.requires_object is True
    assert published.object_catalog == "payable"
    assert Path(result.backup_dir, "config", "default_rules.yaml").exists()


def test_user_rule_wins_before_generic_but_not_priority_two(tmp_path):
    service = _service(tmp_path)
    record = service.new_record(
        "Trả phí thử nghiệm riêng",
        "331",
        "bao_no",
        (ManagedTextAlias.new_user("NGHIEP VU DOC NHAT 2026"),),
    )
    service.apply(record)
    rules, _ = load_rules(None, service.paths.default_rules_path)

    match = RuleEngine(rules).match("bao_no", "ACB", "THANH TOAN NGHIEP VU DOC NHAT 2026")
    assert match is not None
    assert match.rule.rule_id == record.rule_id


def test_alias_can_repeat_across_flows_but_not_within_same_flow(tmp_path):
    service = _service(tmp_path)
    alias = "ALIAS HAI CHIEU DOC NHAT"
    outgoing = service.new_record("Nghiệp vụ đi", "331", "bao_no", (ManagedTextAlias.new_user(alias),))
    service.apply(outgoing)
    incoming = service.new_record("Nghiệp vụ về", "131", "bao_co", (ManagedTextAlias.new_user(alias),))
    duplicate = service.new_record("Nghiệp vụ trùng", "331", "bao_no", (ManagedTextAlias.new_user(alias),))

    assert not any(issue.is_error for issue in service.validate(incoming))
    assert any(issue.code == "ALIAS_COLLISION" for issue in service.validate(duplicate))
    with pytest.raises(AccountingValidationError):
        service.apply(duplicate)


@pytest.mark.parametrize(
    ("account", "expected"),
    [("331", (True, "payable")), ("131", (True, "receivable")), ("141", (True, "internal")), ("642", (False, "none"))],
)
def test_object_policy(account, expected):
    assert _object_policy(account) == expected


@pytest.mark.parametrize("flow", sorted(CASH_FLOWS))
def test_cash_flow_forces_account_1111(tmp_path, flow):
    service = _service(tmp_path)
    record = service.new_record("Tiền mặt thử nghiệm", "999", flow, (ManagedTextAlias.new_user(f"ALIAS {flow}"),))
    service.apply(record)
    stored = next(item for item in service.repository.records() if item.rule_id == record.rule_id)
    assert stored.account == "1111"


def test_accounting_publish_failure_restores_files(tmp_path, monkeypatch):
    service = _service(tmp_path)
    original_yaml = service.paths.default_rules_path.read_bytes()
    record = service.new_record(
        "Nghiệp vụ rollback",
        "642",
        "bao_no",
        (ManagedTextAlias.new_user("ALIAS ROLLBACK KE TOAN"),),
    )

    monkeypatch.setattr(service.publisher, "publish", lambda _records: (_ for _ in ()).throw(RuntimeError("fail")))
    with pytest.raises(RuntimeError):
        service.apply(record)

    assert service.paths.default_rules_path.read_bytes() == original_yaml
    assert not service.paths.accounting_rules_path.exists()


def test_pause_and_reactivate_builtin_rule_without_losing_its_config(tmp_path):
    service = _service(tmp_path)
    builtin = service.list_rules()[0]
    before = yaml.safe_load(service.paths.default_rules_path.read_text(encoding="utf-8"))
    original = next(item for item in before["rules"] if item.get("rule_id") == builtin.rule_id)

    service.set_active(builtin, False)

    after_pause = yaml.safe_load(service.paths.default_rules_path.read_text(encoding="utf-8"))
    assert next(item for item in after_pause["rules"] if item.get("rule_id") == builtin.rule_id) == original
    assert builtin.rule_id in after_pause["disabled_rule_ids"]
    loaded, _ = load_rules(None, service.paths.default_rules_path)
    assert all(rule.rule_id != builtin.rule_id for rule in loaded)
    paused = next(item for item in service.list_rules() if item.rule_id == builtin.rule_id)
    assert paused.active is False
    assert paused.editable is False

    service.set_active(paused, True)

    after_active = yaml.safe_load(service.paths.default_rules_path.read_text(encoding="utf-8"))
    assert builtin.rule_id not in after_active.get("disabled_rule_ids", [])
    loaded, _ = load_rules(None, service.paths.default_rules_path)
    assert any(rule.rule_id == builtin.rule_id for rule in loaded)


def test_delete_user_created_accounting_rule(tmp_path):
    service = _service(tmp_path)
    record = service.new_record(
        "Loại tài khoản sẽ xóa",
        "642",
        "bao_no",
        (ManagedTextAlias.new_user("ALIAS LOAI TAI KHOAN SE XOA"),),
    )
    service.apply(record)

    service.apply(replace(record, active=False, deleted=True))

    loaded, _ = load_rules(None, service.paths.default_rules_path)
    assert all(rule.rule_id != record.rule_id for rule in loaded)
    assert all(item.rule_id != record.rule_id for item in service.list_rules())
    tombstone = next(item for item in service.repository.records() if item.rule_id == record.rule_id)
    assert tombstone.deleted is True


def test_pause_builtin_rule_without_configured_rule_id(tmp_path):
    service = _service(tmp_path)
    builtin = next(item for item in service.list_rules() if item.rule_id.startswith("builtin:"))
    before, _ = load_rules(None, service.paths.default_rules_path)

    service.set_active(builtin, False)

    loaded, _ = load_rules(None, service.paths.default_rules_path)
    assert len(loaded) == len(before) - 1
    paused = next(item for item in service.list_rules() if item.rule_id == builtin.rule_id)
    assert paused.active is False

    service.set_active(paused, True)

    loaded, _ = load_rules(None, service.paths.default_rules_path)
    assert len(loaded) == len(before)
