from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import pytest
from openpyxl import Workbook

import src.processor as processor_module
from src.config_loader import load_config
from src.parsers.msb_parser import MSBParser
from src.processor import process_all
from src.usd.processor import USDProcessor
from src.usd.profile import load_usd_profile
from src.usd.statement_profile import detect_statement_currency


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _rate_body() -> str:
    return json.dumps(
        {
            "currencyOverview": [
                {
                    "currencyCode": "USD",
                    "exchangeRatesData": [{"currencyMarket": 1, "buyRateValue": "26,120"}],
                }
            ]
        }
    )


def _write_msb_statement(path: Path, currency: str | None = "USD") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    if currency:
        sheet.append([f"Loại tiền/Currency: {currency}"])
    else:
        sheet.append(["Sao kê tài khoản"])
    sheet.append([])
    sheet.append(
        [
            "STT/NO",
            "Ngày giao dịch/Transaction Date",
            "Số bút toán/Reference No",
            "Người hưởng/Người chuyển Payee/Payer",
            "Diễn giải/Transaction Description",
            "Nợ/Debit",
            "Có/Credit",
        ]
    )
    rows = [
        (1, "01/06/2026 08:00", "R1", "", "BAN NGOAI TE", 10, 0),
        (2, "01/06/2026 09:00", "R2", "", "THU PHI CHUYEN TIEN", 0.5, 0),
        (3, "01/06/2026 10:00", "R3", "", "RTM NGUYEN VAN AN CCCD 1", 20.25, 0),
        (4, "01/06/2026 11:00", "R4", "", "THU TIEN TAU", 0, 30.75),
        (5, "02/06/2026 12:00", "R5", "", "LE PHAM TT CANG", 40, 0),
    ]
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _config():
    config = load_config(PROJECT_ROOT / "config" / "config.yaml")
    config["historical_memory"] = {"enabled": False}
    return config


def test_synthetic_msb_fixture_detects_currency_and_parser_keeps_decimal_usd(tmp_path):
    statement = tmp_path / "ReportIBS_synthetic.xlsx"
    vnd_statement = tmp_path / "ReportIBS_vnd.xlsx"
    _write_msb_statement(statement)
    _write_msb_statement(vnd_statement, currency="VND")

    transactions = MSBParser().parse(statement)

    assert detect_statement_currency(statement) == "USD"
    assert detect_statement_currency(vnd_statement) == "VND"
    assert len(transactions) == 5
    assert transactions[1].debit_amount == 0.5
    assert transactions[2].debit_amount == 20.25
    assert transactions[3].credit_amount == 30.75


def test_process_all_routes_explicit_usd_to_new_processor(tmp_path, monkeypatch):
    statements = tmp_path / "statements"
    statements.mkdir()
    _write_msb_statement(statements / "ReportIBS_synthetic.xlsx")
    real_processor = USDProcessor
    monkeypatch.setattr(
        processor_module,
        "USDProcessor",
        lambda profile: real_processor(profile, transport=lambda url, timeout: (200, _rate_body())),
    )
    config = _config()

    processed = process_all(
        statements_dir=statements,
        receivable_path=PROJECT_ROOT / "input" / "R_DMDT1 1.xlsx",
        payable_path=PROJECT_ROOT / "input" / "R_DMDT1.xlsx",
        rules_path=None,
        default_rules_path=PROJECT_ROOT / "config" / "default_rules.yaml",
        config=config,
        logger=logging.getLogger("test-usd-route"),
    )

    assert len(processed) == 6
    assert Counter(item.status for item in processed) == {"SKIPPED": 2, "OK": 4}
    assert Counter(item.flow for item in processed if item.status == "OK") == {
        "thu_tien_mat": 1,
        "chi_tien_mat": 1,
        "bao_co": 1,
        "bao_no": 1,
    }
    assert config["_run_stats"]["input_transaction_count"] == 5
    assert config["_run_stats"]["usd_source_transaction_count"] == 5
    assert config["_run_stats"]["usd_accounting_entry_count"] == 4
    assert config["_run_stats"]["usd_skipped_count"] == 2


def test_missing_currency_preserves_legacy_vnd_route_and_warns(tmp_path, monkeypatch, caplog):
    statements = tmp_path / "statements"
    statements.mkdir()
    statement = statements / "ReportIBS_no_currency.xlsx"
    _write_msb_statement(statement, currency=None)

    class UnexpectedUSDProcessor:
        def __init__(self, profile):
            raise AssertionError("missing currency must not enter USD processor")

    monkeypatch.setattr(processor_module, "USDProcessor", UnexpectedUSDProcessor)
    caplog.set_level(logging.WARNING)
    processed = process_all(
        statements_dir=statements,
        receivable_path=PROJECT_ROOT / "input" / "R_DMDT1 1.xlsx",
        payable_path=PROJECT_ROOT / "input" / "R_DMDT1.xlsx",
        rules_path=None,
        default_rules_path=PROJECT_ROOT / "config" / "default_rules.yaml",
        config=_config(),
        logger=logging.getLogger("test-vnd-fallback"),
    )

    assert len(processed) == 5
    assert all(not item.source_transaction_uid for item in processed)
    assert "Không tìm thấy loại tiền" in caplog.text


def test_local_real_usd_statement_matches_approved_acceptance_counts():
    sample = next(
        (
            path
            for path in (
                PROJECT_ROOT / "input" / "ReportIBSCorpAccountStatement_20260903144134.xlsx",
                PROJECT_ROOT / "input" / "statements" / "ReportIBSCorpAccountStatement_20260903144134.xlsx",
            )
            if path.exists()
        ),
        None,
    )
    if sample is None:
        pytest.skip("User-owned local acceptance file is not available")

    transactions = MSBParser().parse(sample)
    processor = USDProcessor(
        load_usd_profile(PROJECT_ROOT / "config" / "usd_msb.yaml"),
        transport=lambda url, timeout: (200, _rate_body()),
    )
    outcomes = processor.process_batch(transactions)
    classes = Counter(outcome.source.classification for outcome in outcomes)
    flows = Counter(entry.flow for outcome in outcomes for entry in outcome.entries)

    assert detect_statement_currency(sample) == "USD"
    assert len(transactions) == 72
    assert classes["usd_foreign_currency_sale"] == 3
    assert classes["usd_bank_fee"] == 34
    assert classes["usd_cash_withdrawal"] == 8
    assert classes["usd_credit_default"] == 26
    assert classes["usd_debit_port_payment"] == 1
    assert classes["usd_debit_default"] == 0
    assert flows == {"bao_co": 26, "thu_tien_mat": 8, "chi_tien_mat": 8, "bao_no": 1}
    assert sum(len(outcome.entries) for outcome in outcomes) == 43
