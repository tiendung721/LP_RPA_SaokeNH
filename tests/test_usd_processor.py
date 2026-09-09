from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from src.flows import FLOW_BAO_CO, FLOW_BAO_NO, FLOW_CHI_TIEN_MAT, FLOW_THU_TIEN_MAT
from src.models import Transaction
from src.usd.adapter import outcomes_to_processed
from src.usd.models import STATUS_ERROR, STATUS_MISSING_EXCHANGE_RATE, STATUS_READY, STATUS_SKIPPED
from src.usd.processor import USDProcessor
from src.usd.profile import load_usd_profile


def _transaction(
    description: str,
    *,
    debit: float = 0,
    credit: float = 0,
    day: int = 27,
    row: int = 14,
) -> Transaction:
    return Transaction(
        source_file="usd.xlsx",
        bank="MSB",
        transaction_date=date(2026, 6, day),
        doc_no=f"REF-{row}",
        description=description,
        counterparty_raw="",
        debit_amount=debit,
        credit_amount=credit,
        original_row_index=row,
        source_sheet="Sheet1",
    )


def _body(rate: str = "26,120") -> str:
    return json.dumps(
        {
            "currencyOverview": [
                {
                    "currencyCode": "USD",
                    "exchangeRatesData": [{"currencyMarket": 1, "buyRateValue": rate}],
                }
            ]
        }
    )


def test_rtm_produces_exactly_two_independent_entries_with_exact_decimal_amount():
    calls = []

    def transport(url, timeout):
        calls.append(url)
        return 200, _body("26,120.125")

    transaction = _transaction("RTM NGUYEN VAN AN CCCD 0123", debit=0.125)
    outcome = USDProcessor(load_usd_profile("config/usd_msb.yaml"), transport=transport).process_batch(
        [transaction]
    )[0]

    assert outcome.status == STATUS_READY
    assert len(calls) == 1
    assert len(outcome.entries) == 2
    receipt, payment = outcome.entries
    assert (receipt.flow, receipt.debit_account, receipt.credit_account) == (
        FLOW_THU_TIEN_MAT,
        "1111",
        "1122HB",
    )
    assert (payment.flow, payment.debit_account, payment.credit_account) == (
        FLOW_CHI_TIEN_MAT,
        "13882",
        "1111",
    )
    assert receipt.payer_name == "NGUYEN VAN AN"
    assert payment.receiver_name == "Lê Minh Tâm"
    assert receipt.foreign_amount == payment.foreign_amount == Decimal("0.125")
    assert receipt.exchange_rate == payment.exchange_rate == Decimal("26120.125")
    assert receipt.amount == payment.amount == Decimal("0.125") * Decimal("26120.125")
    assert receipt.entry_uid == f"{outcome.source.source_transaction_uid}:THU_TM"
    assert payment.entry_uid == f"{outcome.source.source_transaction_uid}:CHI_TM"

    adapted = outcomes_to_processed([outcome])
    assert [item.transaction_uid for item in adapted] == [receipt.entry_uid, payment.entry_uid]
    assert adapted[0].object_code == adapted[1].object_code == ""


def test_one_entry_rules_use_source_uid_accounts_and_reasons():
    transactions = [
        _transaction("THU TIEN TAU", credit=10, row=14),
        _transaction("LE PHAM TT CANG CAT LAI", debit=20, row=15),
        _transaction("THANH TOAN TAU", debit=30, row=16),
    ]
    processor = USDProcessor(
        load_usd_profile("config/usd_msb.yaml"), transport=lambda url, timeout: (200, _body())
    )
    outcomes = processor.process_batch(transactions)
    entries = [outcome.entries[0] for outcome in outcomes]

    assert [entry.flow for entry in entries] == [FLOW_BAO_CO, FLOW_BAO_NO, FLOW_BAO_NO]
    assert [(entry.debit_account, entry.credit_account) for entry in entries] == [
        ("1122HB", "12882"),
        ("13882", "1122HB"),
        ("13882", "1122HB"),
    ]
    assert [entry.reason for entry in entries] == ["TT tiền tàu", "TT tiền cảng phí", "TT tiền tàu"]
    assert all(entry.entry_uid == entry.source_transaction_uid for entry in entries)


def test_skip_and_invalid_rows_do_not_call_exchange_rate_api():
    def unexpected_transport(url, timeout):
        raise AssertionError("exchange-rate API must not be called")

    transactions = [
        _transaction("BAN NGOAI TE", debit=10, row=14),
        _transaction("THU PHI CHUYEN TIEN", debit=5, row=15),
        _transaction("RTM THEO CCCD 1", debit=20, row=16),
    ]
    outcomes = USDProcessor(
        load_usd_profile("config/usd_msb.yaml"), transport=unexpected_transport
    ).process_batch(transactions)
    assert [outcome.status for outcome in outcomes] == [STATUS_SKIPPED, STATUS_SKIPPED, STATUS_ERROR]
    assert not any(outcome.entries for outcome in outcomes)


def test_unique_dates_are_requested_once_and_failed_date_is_isolated_and_cached():
    calls = []

    def transport(url, timeout):
        calls.append(url)
        if "02%2F06%2F2026" in url:
            return 503, ""
        return 200, _body()

    processor = USDProcessor(load_usd_profile("config/usd_msb.yaml"), transport=transport)
    transactions = [
        _transaction("THU 1", credit=10, day=1, row=14),
        _transaction("THU 2", credit=20, day=1, row=15),
        _transaction("THU 3", credit=30, day=2, row=16),
    ]
    first = processor.process_batch(transactions)
    second = processor.process_batch([_transaction("THU 4", credit=40, day=2, row=17)])

    assert [outcome.status for outcome in first] == [STATUS_READY, STATUS_READY, STATUS_MISSING_EXCHANGE_RATE]
    assert second[0].status == STATUS_MISSING_EXCHANGE_RATE
    assert len(calls) == 2
    assert len(processor.resolver.cache) == 2
    missing = outcomes_to_processed([first[2]])[0]
    assert missing.foreign_amount == Decimal("30")
    assert missing.amount == Decimal("0")
    assert missing.exchange_rate == Decimal("0")
