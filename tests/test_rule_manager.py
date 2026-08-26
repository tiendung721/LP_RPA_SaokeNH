from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.normalizer import normalize_text
from src.rule_manager.models import MATCH_ALIAS, MATCH_EXACT_PHRASE, AliasInput, ObjectChangeRequest
from src.rule_manager.paths import RuleManagerPaths
from src.rule_manager.service import ObjectRuleManagerService, RuleManagerValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path: Path) -> RuleManagerPaths:
    for relative in (
        "input/R_DMDT1 1.xlsx",
        "input/R_DMDT1.xlsx",
        "input/MA NOI BO CTY.xlsx",
        "config/object_aliases.yaml",
        "config/object_overrides.yaml",
        "config/own_company.yaml",
    ):
        source = PROJECT_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return RuleManagerPaths.from_project_root(tmp_path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_add_exact_alias_to_existing_object_and_publish_with_backup(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    existing = service.catalogs.find("payable", "199")
    assert existing is not None

    request = ObjectChangeRequest(
        catalog="payable",
        code=existing.code,
        name=existing.name,
        tax_code=existing.tax_code,
        aliases=(AliasInput("RULE MANAGER EXACT SAMPLE", MATCH_EXACT_PHRASE),),
    )
    result = service.apply(request)

    assert result.object_created is False
    assert result.aliases_changed == 1
    assert Path(result.backup_dir, "config", "object_overrides.yaml").exists()
    user_data = json.loads(paths.user_rules_path.read_text(encoding="utf-8"))
    assert user_data["aliases"][0]["alias"] == "RULE MANAGER EXACT SAMPLE"
    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    assert overrides["payable"]["exact_phrases"]["RULE MANAGER EXACT SAMPLE"] == "199"


def test_add_new_object_to_catalog_and_flexible_alias(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    request = ObjectChangeRequest(
        catalog="payable",
        code="RULEMGR2026",
        name="Công ty thử nghiệm Rule Manager",
        tax_code="0200999999",
        address="Hải Phòng",
        confirmed_in_vacom=True,
        aliases=(AliasInput("CT CHO RULE MANAGER 2026", MATCH_ALIAS),),
    )

    result = service.apply(request)

    assert result.object_created is True
    created = service.catalogs.find("payable", "RULEMGR2026")
    assert created is not None
    assert created.name == "Công ty thử nghiệm Rule Manager"
    aliases = yaml.safe_load(paths.object_aliases_path.read_text(encoding="utf-8"))
    assert "CT CHO RULE MANAGER 2026" in aliases["payable"]["RULEMGR2026"]
    stored_objects = service.repository.objects()
    assert any(item.code == "RULEMGR2026" and item.confirmed_in_vacom for item in stored_objects)


def test_new_object_requires_vacom_confirmation(tmp_path):
    service = ObjectRuleManagerService(_workspace(tmp_path))
    request = ObjectChangeRequest(
        catalog="receivable",
        code="NOTCONFIRMED",
        name="Đối tượng chưa tạo VACOM",
        confirmed_in_vacom=False,
    )

    issues = service.validate(request)

    assert any(issue.code == "VACOM_NOT_CONFIRMED" and issue.is_error for issue in issues)
    with pytest.raises(RuleManagerValidationError):
        service.apply(request)


def test_alias_collision_is_rejected(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    targets = service.publisher.alias_targets()["payable"]
    collision_alias, collision_records = next(
        (alias, records)
        for alias, records in targets.items()
        if records and normalize_text(records[0]["object_code"]) != normalize_text("199")
    )
    existing = service.catalogs.find("payable", "199")
    assert existing is not None
    request = ObjectChangeRequest(
        catalog="payable",
        code=existing.code,
        name=existing.name,
        aliases=(AliasInput(collision_alias, MATCH_EXACT_PHRASE),),
    )

    issues = service.validate(request)

    assert any(issue.code in {"ALIAS_COLLISION", "ALIAS_ALREADY_EXISTS"} and issue.is_error for issue in issues)


def test_failure_after_catalog_write_restores_all_files(tmp_path, monkeypatch):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    catalog_path = paths.catalog_path("internal")
    original_hash = _sha256(catalog_path)

    def fail_publish(_records):
        raise RuntimeError("simulated yaml failure")

    monkeypatch.setattr(service.publisher, "publish", fail_publish)
    request = ObjectChangeRequest(
        catalog="internal",
        code="RULEMANAGERPERSON",
        name="Nguyễn Văn Kiểm Thử",
        confirmed_in_vacom=True,
        aliases=(AliasInput("NGUYEN VAN KIEM THU", MATCH_EXACT_PHRASE),),
    )

    with pytest.raises(RuntimeError, match="simulated yaml failure"):
        service.apply(request)

    assert _sha256(catalog_path) == original_hash
    assert not paths.user_rules_path.exists()
    assert service.catalogs.find("internal", "RULEMANAGERPERSON") is None


def test_deactivate_user_alias_removes_it_from_generated_yaml(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    existing = service.catalogs.find("receivable", "001")
    assert existing is not None
    alias = "RULE MANAGER DEACTIVATE SAMPLE"
    service.apply(
        ObjectChangeRequest(
            catalog="receivable",
            code=existing.code,
            name=existing.name,
            aliases=(AliasInput(alias, MATCH_EXACT_PHRASE),),
        )
    )

    service.deactivate_alias("receivable", alias)

    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    exact = overrides["receivable"].get("exact_phrases", {})
    assert all(normalize_text(phrase) != normalize_text(alias) for phrase in exact)
    record = next(item for item in service.repository.aliases() if normalize_text(item.alias) == normalize_text(alias))
    assert record.active is False
