from src.object_aliases import load_object_aliases
from src.object_overrides import load_object_overrides


def test_loader_does_not_auto_add_short_generic_code_alias(tmp_path):
    alias_file = tmp_path / "aliases.yaml"
    alias_file.write_text(
        """
payable:
  TCT:
    - "TIEN DIEN"
  KBB:
    - "KBB"
receivable: {}
internal:
  DUC:
    - "LE NGOC DUC"
""",
        encoding="utf-8",
    )

    aliases = load_object_aliases(alias_file)

    assert aliases["payable"]["TCT"] == ["TIEN DIEN"]
    assert aliases["payable"]["KBB"] == ["KBB"]
    assert aliases["internal"]["DUC"] == ["LE NGOC DUC"]


def test_project_alias_fixes_for_known_collisions():
    aliases = load_object_aliases("config/object_aliases.yaml")
    payable = aliases["payable"]
    internal = aliases["internal"]

    assert "CANG QT VINH TAN" not in payable["CANG-HA"]
    assert "CANG QT VINH TAN" in payable["QTVINHTAN"]
    assert "HOA TIEU MB" in payable["HOATIEU2"]
    assert "HOA TIEU MB" not in payable["HOATIEU3"]
    assert "HOANG ANH" in internal["HOANGANH"]


def test_project_overrides_use_exact_phrase_for_ils():
    overrides = load_object_overrides("config/object_overrides.yaml")

    assert overrides["payable"]["exact_phrases"]["ILS"] == "VATCACH"
    assert overrides["payable"]["exact_phrases"]["PIL VIETNAM"] == "S5 VIET NAM"
    assert overrides["payable"]["exact_phrases"]["BAO HIEM AAA"] == "BAOHIEMAAA"
    assert overrides["receivable"]["exact_phrases"]["PIL VIETNAM CO LTD"] == "S5 VIET NAM"
    assert overrides["receivable"]["exact_phrases"]["TAU BIEN SAI GON"] == "TAUBIENSAIGON"
    assert overrides["internal"]["exact_phrases"]["HOANG ANH"] == "HOANGANH"
    assert any(obj.code == "HOANGANH" for obj in overrides["internal"]["supplemental_objects"])


def test_confirmed_june_2026_aliases_use_vacom_object_codes():
    overrides = load_object_overrides("config/object_overrides.yaml")

    assert overrides["receivable"]["exact_phrases"]["CTY HB68"] == "HOABINH68"
    assert overrides["receivable"]["exact_phrases"]["GN VA VT QT CHAU LUC"] == "CHAULUC"
    assert overrides["receivable"]["exact_phrases"]["AGRIS GL"] == "GIALAI"
    assert overrides["payable"]["exact_phrases"]["CT CHO PHB"] == "HAIBINH"
    assert overrides["payable"]["exact_phrases"]["TAN PHAT HD 164"] == "TANPHAT"
    assert overrides["payable"]["exact_phrases"]["DUC LONG HD 441"] == "DUCLONG"
    assert overrides["payable"]["exact_phrases"]["CUOC DUONG BO VETC"] == "VETC"
