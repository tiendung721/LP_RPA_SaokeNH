from pathlib import Path

from src.config_loader import load_rules
from src.rule_engine import RuleEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def engine() -> RuleEngine:
    rules, _ = load_rules(None, PROJECT_ROOT / "config/default_rules.yaml")
    return RuleEngine(rules)


def test_rule_gtgt():
    match = engine().match("bao_no", "VCB", "NOP THUE GTGT THANG 03 2026")
    assert match is not None
    assert match.rule.account == "3331"


def test_tndn_tncn_not_confused():
    rule_engine = engine()
    tndn = rule_engine.match("bao_no", "VCB", "NOP THUE TNDN TAM NOP")
    tncn = rule_engine.match("bao_no", "VCB", "NOP THUE TNCN")
    assert tndn is not None
    assert tncn is not None
    assert tndn.rule.account == "3334"
    assert tncn.rule.account == "3335"


def test_insurance_not_auto_processed():
    match = engine().match("bao_no", "VCB", "DONG BHXH THANG 03 2026")
    assert match is not None
    assert match.rule.auto_process is False


def test_insurance_fee_not_auto_processed():
    match = engine().match("bao_no", "ACB", "THANH TOAN PHI BAO HIEM CHO CTY BAO HIEM ABC")
    assert match is not None
    assert match.rule.use_case == "Bảo hiểm"
    assert match.rule.auto_process is False


def test_aaa_insurance_fee_is_auto_processed_before_generic_insurance():
    debit = engine().match("bao_no", "ACB", "THANH TOAN PHI BAO HIEM AAA")
    credit = engine().match("bao_co", "ACB", "BAO HIEM AAA HP THANH TOAN PHI BAO HIEM")

    assert debit is not None
    assert debit.rule.rule_id == "aaa_insurance_fee_out"
    assert debit.rule.account == "331"
    assert debit.rule.auto_process is True
    assert credit is not None
    assert credit.rule.rule_id == "aaa_insurance_fee_in"
    assert credit.rule.account == "131"


def test_acb_salary():
    match = engine().match("bao_no", "ACB", "LUONG THANG 3-2026")
    assert match is not None
    assert match.rule.account == "334"


def test_bank_interest_credit():
    match = engine().match("bao_co", "MSB", "LAI NHAP VON")
    assert match is not None
    assert match.rule.account == "515"


def test_bank_loan_interest_is_vcb_only():
    rule_engine = engine()
    vcb = rule_engine.match("bao_no", "VCB", "TRA LAI VAY")
    acb = rule_engine.match("bao_no", "ACB", "TRA LAI VAY")
    assert vcb is not None
    assert vcb.rule.rule_id == "bank_loan_interest"
    assert vcb.rule.default_object_code == "VCB"
    assert acb is None
