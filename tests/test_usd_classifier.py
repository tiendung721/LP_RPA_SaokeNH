from __future__ import annotations

from datetime import date

import pytest

from src.models import Transaction
from src.usd.classifier import (
    RULE_BANK_FEE,
    RULE_CASH_WITHDRAWAL,
    RULE_CREDIT_DEFAULT,
    RULE_DEBIT_DEFAULT,
    RULE_DEBIT_PORT_PAYMENT,
    RULE_FOREIGN_CURRENCY_SALE,
    RULE_INVALID_DIRECTION,
    RULE_INVALID_WITHDRAWAL,
    USDClassifier,
)


def _transaction(description: str, debit: float = 100, credit: float = 0) -> Transaction:
    return Transaction(
        source_file="usd.xlsx",
        bank="MSB",
        transaction_date=date(2026, 6, 27),
        doc_no="REF1",
        description=description,
        counterparty_raw="",
        debit_amount=debit,
        credit_amount=credit,
        original_row_index=14,
        source_sheet="Sheet1",
    )


def test_foreign_currency_sale_has_highest_priority():
    result = USDClassifier().classify(_transaction("BAN NGOAI TE PHI RTM LE VAN AN CCCD 1"))
    assert (result.rule_id, result.action) == (RULE_FOREIGN_CURRENCY_SALE, "SKIP")


@pytest.mark.parametrize(
    "description",
    ["PHI", "PHI CHUYEN TIEN", "THU PHI DIEN", "VAT PHI CHUYEN TIEN"],
)
def test_all_approved_fee_prefixes_are_skipped_without_amount_limit(description):
    result = USDClassifier().classify(_transaction(description, debit=999_999_999))
    assert (result.rule_id, result.action) == (RULE_BANK_FEE, "SKIP")


def test_fee_word_later_in_description_does_not_override_port_payment():
    result = USDClassifier().classify(_transaction("LE PHAM TT CANG PHI TAU"))
    assert (result.rule_id, result.action) == (RULE_DEBIT_PORT_PAYMENT, "ENTRY")


@pytest.mark.parametrize("marker", ["RTM", "RUT TM", "RUT TIEN MAT", "RUT TIEN"])
def test_cash_withdrawal_markers_extract_name_before_cccd(marker):
    result = USDClassifier().classify(_transaction(f"{marker} NGUYEN VAN AN CCCD 012345"))
    assert (result.rule_id, result.action, result.employee_name) == (
        RULE_CASH_WITHDRAWAL,
        "ENTRY",
        "NGUYEN VAN AN",
    )


def test_cash_withdrawal_never_falls_back_when_direction_or_name_is_invalid():
    wrong_direction = USDClassifier().classify(
        _transaction("RTM NGUYEN VAN AN CCCD 1", debit=0, credit=100)
    )
    missing_name = USDClassifier().classify(_transaction("RTM THEO CCCD 1"))
    assert (wrong_direction.rule_id, wrong_direction.action) == (RULE_INVALID_WITHDRAWAL, "ERROR")
    assert (missing_name.rule_id, missing_name.action) == (RULE_INVALID_WITHDRAWAL, "ERROR")


def test_credit_port_and_default_debit_rules():
    classifier = USDClassifier()
    credit = classifier.classify(_transaction("THU TIEN TAU", debit=0, credit=12.5))
    port = classifier.classify(_transaction("LE PHAM THANH TOAN CANG CAT LAI"))
    default = classifier.classify(_transaction("THANH TOAN TIEN TAU"))
    assert credit.rule_id == RULE_CREDIT_DEFAULT
    assert port.rule_id == RULE_DEBIT_PORT_PAYMENT
    assert default.rule_id == RULE_DEBIT_DEFAULT


@pytest.mark.parametrize(("debit", "credit"), [(100, 200), (0, 0)])
def test_invalid_direction_is_an_error_without_fallback(debit, credit):
    result = USDClassifier().classify(_transaction("THANH TOAN", debit=debit, credit=credit))
    assert (result.rule_id, result.action) == (RULE_INVALID_DIRECTION, "ERROR")
