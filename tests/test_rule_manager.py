from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from src.normalizer import normalize_text
from src.object_matcher import ObjectMatcher
from src.object_overrides import load_object_overrides
from src.rule_manager.models import MATCH_ALIAS, MATCH_EXACT_PHRASE, AliasInput, ManagedObject, ObjectChangeRequest
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
        aliases=(AliasInput("CT CHO RULE MANAGER EXACT SAMPLE", MATCH_ALIAS),),
    )
    result = service.apply(request)

    assert result.object_created is False
    assert result.aliases_changed == 1
    assert Path(result.backup_dir, "config", "object_overrides.yaml").exists()
    user_data = json.loads(paths.user_rules_path.read_text(encoding="utf-8"))
    assert user_data["aliases"][0]["alias"] == "CT CHO RULE MANAGER EXACT SAMPLE"
    assert user_data["aliases"][0]["match_type"] == MATCH_EXACT_PHRASE
    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    assert overrides["payable"]["exact_phrases"]["CT CHO RULE MANAGER EXACT SAMPLE"] == "199"


def test_add_new_object_to_catalog_and_flexible_alias(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    request = ObjectChangeRequest(
        catalog="payable",
        code="RULEMGR2026",
        name="Công ty TNHH Sao Biển Logistics",
        aliases=(AliasInput("SAO BIEN LOGISTICS", MATCH_EXACT_PHRASE),),
    )

    result = service.apply(request)

    assert result.object_created is True
    created = service.catalogs.find("payable", "RULEMGR2026")
    assert created is not None
    assert created.name == "Công ty TNHH Sao Biển Logistics"
    aliases = yaml.safe_load(paths.object_aliases_path.read_text(encoding="utf-8"))
    assert "SAO BIEN LOGISTICS" in aliases["payable"]["RULEMGR2026"]
    stored_alias = next(item for item in service.repository.aliases() if item.object_code == "RULEMGR2026")
    assert stored_alias.match_type == MATCH_ALIAS
    stored_objects = service.repository.objects()
    assert any(item.code == "RULEMGR2026" for item in stored_objects)


def test_new_object_does_not_require_vacom_confirmation(tmp_path):
    service = ObjectRuleManagerService(_workspace(tmp_path))
    request = ObjectChangeRequest(
        catalog="receivable",
        code="NOTCONFIRMED",
        name="Đối tượng chưa tạo VACOM",
        confirmed_in_vacom=False,
    )

    issues = service.validate(request)

    assert not any(issue.code == "VACOM_NOT_CONFIRMED" for issue in issues)
    assert not any(issue.is_error for issue in issues)


def test_alias_type_is_inferred_from_content(tmp_path):
    service = ObjectRuleManagerService(_workspace(tmp_path))

    assert (
        service.classify_alias(
            "payable",
            "AUTOALIAS",
            "Công ty TNHH Sao Biển Logistics",
            "SAO BIEN LOGISTICS",
        )
        == MATCH_ALIAS
    )
    assert (
        service.classify_alias(
            "payable",
            "AUTOALIAS",
            "Công ty TNHH Sao Biển Logistics",
            "CT CHO SAO BIEN HD 12",
        )
        == MATCH_EXACT_PHRASE
    )
    assert (
        service.classify_alias(
            "payable",
            "AUTOALIAS",
            "Công ty TNHH Sao Biển Logistics",
            "ILS",
        )
        == MATCH_EXACT_PHRASE
    )


def test_ambiguous_flexible_alias_is_downgraded_to_exact_phrase(tmp_path, monkeypatch):
    service = ObjectRuleManagerService(_workspace(tmp_path))
    monkeypatch.setattr(
        service.catalogs,
        "list_objects",
        lambda _catalog: [
            ManagedObject("payable", "VINACTL_HP", "Công ty Vinacontrol Hải Phòng"),
            ManagedObject("payable", "VINACTL_HCM", "Công ty Vinacontrol Hồ Chí Minh"),
        ],
    )

    assert (
        service.classify_alias(
            "payable",
            "VINACTL_HP",
            "Công ty Vinacontrol Hải Phòng",
            "VINACONTROL",
        )
        == MATCH_EXACT_PHRASE
    )


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

    def fail_publish(_records, _objects):
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


def test_edit_configuration_alias_replaces_old_value(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    existing = service.catalogs.find("payable", "199")
    assert existing is not None
    base = next(item for item in service.aliases_for_object("payable", existing.code) if item.source == "config")
    new_alias = "ALIAS CHINH SUA TU GIAO DIEN"
    change = replace(
        base,
        alias=new_alias,
        match_type=MATCH_EXACT_PHRASE,
        previous_aliases=(base.alias,),
    )

    service.apply(
        ObjectChangeRequest(
            catalog="payable",
            code=existing.code,
            name=existing.name,
            alias_changes=(change,),
        )
    )

    targets = service.publisher.alias_targets()["payable"]
    assert normalize_text(base.alias) not in targets
    assert targets[normalize_text(new_alias)][0]["object_code"] == existing.code
    stored = next(item for item in service.repository.aliases() if item.record_id == base.record_id)
    assert stored.alias == new_alias
    assert stored.source == "config"


def test_pause_reactivate_and_delete_configuration_alias(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    existing = service.catalogs.find("receivable", "001")
    assert existing is not None
    base = next(item for item in service.aliases_for_object("receivable", existing.code) if item.source == "config")

    service.apply(
        ObjectChangeRequest(
            catalog="receivable",
            code=existing.code,
            name=existing.name,
            alias_changes=(replace(base, active=False),),
        )
    )
    assert normalize_text(base.alias) not in service.publisher.alias_targets()["receivable"]
    paused = next(item for item in service.aliases_for_object("receivable", existing.code) if item.record_id == base.record_id)
    assert paused.active is False

    service.apply(
        ObjectChangeRequest(
            catalog="receivable",
            code=existing.code,
            name=existing.name,
            alias_changes=(replace(paused, active=True),),
        )
    )
    assert normalize_text(base.alias) in service.publisher.alias_targets()["receivable"]

    active = next(item for item in service.aliases_for_object("receivable", existing.code) if item.record_id == base.record_id)
    service.apply(
        ObjectChangeRequest(
            catalog="receivable",
            code=existing.code,
            name=existing.name,
            alias_changes=(replace(active, active=False, deleted=True),),
        )
    )
    assert normalize_text(base.alias) not in service.publisher.alias_targets()["receivable"]
    tombstone = next(item for item in service.repository.aliases() if item.record_id == base.record_id)
    assert tombstone.deleted is True


def test_pause_and_reactivate_any_catalog_object(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    existing = service.catalogs.find("payable", "199")
    assert existing is not None

    service.set_object_active("payable", existing.code, False)

    paused = next(row for row in service.list_objects("payable") if row.object.code == existing.code)
    assert paused.active is False
    assert paused.deletable is False
    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    assert existing.code in overrides["payable"]["disabled_object_codes"]
    runtime_overrides = load_object_overrides(paths.object_overrides_path)["payable"]
    matcher = ObjectMatcher.from_excel(
        paths.catalog_path("payable"),
        disabled_object_codes=runtime_overrides["disabled_object_codes"],
    )
    assert all(normalize_text(item.code) != normalize_text(existing.code) for item in matcher.objects)

    service.set_object_active("payable", existing.code, True)

    active = next(row for row in service.list_objects("payable") if row.object.code == existing.code)
    assert active.active is True
    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    assert existing.code not in overrides["payable"].get("disabled_object_codes", [])


def test_delete_only_newly_added_object_and_its_aliases(tmp_path):
    paths = _workspace(tmp_path)
    service = ObjectRuleManagerService(paths)
    code = "DELETE_UI_2026"
    service.apply(
        ObjectChangeRequest(
            catalog="payable",
            code=code,
            name="Đối tượng chỉ dùng để kiểm thử xóa",
            aliases=(AliasInput("DOI TUONG DELETE UI 2026"),),
        )
    )
    created = next(row for row in service.list_objects("payable") if row.object.code == code)
    assert created.deletable is True

    result = service.delete_object("payable", code)

    assert service.catalogs.find("payable", code) is None
    tombstone = next(item for item in service.repository.objects() if item.code == code)
    assert tombstone.deleted is True
    assert tombstone.active is False
    assert all(item.object_code != code for item in service.repository.aliases())
    assert normalize_text(code) not in {
        normalize_text(target["object_code"])
        for targets in service.publisher.alias_targets()["payable"].values()
        for target in targets
    }
    overrides = yaml.safe_load(paths.object_overrides_path.read_text(encoding="utf-8"))
    assert code in overrides["payable"]["disabled_object_codes"]
    assert Path(result.backup_dir, "input", "R_DMDT1.xlsx").exists()


def test_existing_catalog_object_cannot_be_deleted(tmp_path):
    service = ObjectRuleManagerService(_workspace(tmp_path))

    with pytest.raises(RuleManagerValidationError) as exc_info:
        service.delete_object("payable", "199")

    assert any(issue.code == "BUILTIN_OBJECT_READ_ONLY" for issue in exc_info.value.issues)
