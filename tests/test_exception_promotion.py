from __future__ import annotations

import sys
from datetime import date

from openpyxl import Workbook, load_workbook

import promote_reviewed_exceptions as promote_cli
from src.exception_promotion import (
    EXCEPTION_SHEET_NAME,
    EXCEPTION_STATUS_COLUMN,
    FLOW_COLUMN,
    MISSING_ERROR_COLUMN,
    PROMOTED_SHEET_COLUMN,
    PROMOTED_TO_INPUT_COLUMN,
    STATUS_INVALID_FLOW,
    STATUS_MISSING_DATA,
    STATUS_PROMOTED,
    promote_reviewed_exceptions,
)
from src.flows import FLOW_BAO_NO, FLOW_CHI_TIEN_MAT, FLOW_THU_TIEN_MAT
from src.models import ProcessedTransaction
from src.output_writer import (
    EXCEPTION_COLUMNS,
    EXCEPTION_REVIEW_COLUMNS,
    RPA_BUSINESS_COLUMNS,
    RPA_CHI_TIEN_MAT_COLUMNS,
    RPA_REASON_UNICODE_COLUMN,
    RPA_THU_TIEN_MAT_COLUMNS,
    write_excel,
)
from src.rpa_input_status import (
    INPUT_MESSAGE_COLUMN,
    INPUT_STATUS_COLUMN,
    INPUT_UPDATED_AT_COLUMN,
    RPA_INPUT_SHEETS,
)
from src.rpa_tracking import STATUS_PENDING


def _input_columns(sheet_name: str) -> list[str]:
    if sheet_name == "THU_TIEN_MAT_INPUT":
        columns = list(RPA_THU_TIEN_MAT_COLUMNS)
    elif sheet_name == "CHI_TIEN_MAT_INPUT":
        columns = list(RPA_CHI_TIEN_MAT_COLUMNS)
    else:
        columns = list(RPA_BUSINESS_COLUMNS)
    if RPA_REASON_UNICODE_COLUMN not in columns:
        columns.insert(columns.index("Lí do") + 1, RPA_REASON_UNICODE_COLUMN)
    return columns


def _make_workbook(path) -> None:
    workbook = Workbook()
    for index, sheet_name in enumerate(RPA_INPUT_SHEETS):
        ws = workbook.active if index == 0 else workbook.create_sheet(sheet_name)
        ws.title = sheet_name
        ws.append(_input_columns(sheet_name))
    exception_ws = workbook.create_sheet(EXCEPTION_SHEET_NAME)
    exception_ws.append(EXCEPTION_COLUMNS)
    workbook.save(path)


def _append_exception(path, **overrides) -> None:
    workbook = load_workbook(path)
    ws = workbook[EXCEPTION_SHEET_NAME]
    headers = [cell.value for cell in ws[1]]
    row = {header: "" for header in headers}
    row.update(
        {
            "Mã định danh": "uid_exception",
            "File gốc": "statement.xlsx",
            "Sheet gốc": "Sheet1",
            "Dòng gốc": 2,
            "Ngân hàng": "ACB",
            "Luồng": FLOW_BAO_NO,
            FLOW_COLUMN: FLOW_BAO_NO,
            "Ngày CT": date(2026, 6, 20),
            "Nội dung giao dịch gốc": "TT ABC",
            "Người hưởng/Người chuyển": "ABC",
            "Người nhận tiền": "Nguyen Van B",
            "Người nộp tiền": "Nguyen Van A",
            "Mã ĐT": "ABC",
            "Tên ĐT suy luận": "ABC",
            "Lí do": "",
            RPA_REASON_UNICODE_COLUMN: "Thanh toán ABC",
            "TK nợ": "331",
            "TK có": "1121CT",
            "Thành tiền": 1000,
            "Tỷ giá": "",
            "transaction_uid": "uid_exception",
            "run_id": "run1",
            "Duyệt nhập RPA": "yes",
        }
    )
    row.update(overrides)
    ws.append([row.get(header, "") for header in headers])
    workbook.save(path)


def _rows(path, sheet_name: str) -> list[dict[str, object]]:
    workbook = load_workbook(path, data_only=True)
    ws = workbook[sheet_name]
    headers = [cell.value for cell in ws[1]]
    return [dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)]


def _exception_row(path) -> dict[str, object]:
    return _rows(path, EXCEPTION_SHEET_NAME)[0]


def test_generated_exception_sheet_has_review_promotion_columns(tmp_path):
    output_file = tmp_path / "rpa_input.xlsx"
    item = ProcessedTransaction(
        source_file="statement.xlsx",
        original_row_index=2,
        bank="ACB",
        flow=FLOW_BAO_NO,
        transaction_date=date(2026, 6, 20),
        object_code="ERROR",
        object_name="",
        reason="Cần bổ sung thông tin",
        debit_account="",
        credit_account="1121CT",
        amount=1000,
        use_case="",
        original_content="TT ABC",
        counterparty_raw="ABC",
        doc_no="REF1",
        status="ERROR",
        error_note="Thiếu mã đối tượng",
        confidence=0,
        transaction_uid="uid_error",
        source_sheet="Sheet1",
    )

    write_excel([item], output_file, run_id="run1", rpa_reason_encoding="tcvn3")

    workbook = load_workbook(output_file, data_only=True)
    headers = [cell.value for cell in workbook[EXCEPTION_SHEET_NAME][1]]
    for column_name in [
        "Lí do",
        RPA_REASON_UNICODE_COLUMN,
        "Người nhận tiền",
        "Người nộp tiền",
        "run_id",
        *EXCEPTION_REVIEW_COLUMNS,
    ]:
        assert headers.count(column_name) == 1


def test_promotes_reviewed_bao_no_exception_and_marks_original_row(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(input_file)

    summary = promote_reviewed_exceptions(input_file)

    assert summary.promoted == 1
    bao_no_rows = _rows(input_file, "BAO_NO_INPUT")
    assert len(bao_no_rows) == 1
    assert bao_no_rows[0]["Mã ĐT"] == "ABC"
    assert bao_no_rows[0]["transaction_uid"] == "uid_exception"
    assert bao_no_rows[0][INPUT_STATUS_COLUMN] == STATUS_PENDING
    assert bao_no_rows[0][INPUT_MESSAGE_COLUMN] in ("", None)
    assert bao_no_rows[0][INPUT_UPDATED_AT_COLUMN] in ("", None)

    exception_row = _exception_row(input_file)
    assert exception_row[PROMOTED_TO_INPUT_COLUMN] == "yes"
    assert exception_row[PROMOTED_SHEET_COLUMN] == "BAO_NO_INPUT"
    assert exception_row[EXCEPTION_STATUS_COLUMN] == STATUS_PROMOTED


def test_promote_is_idempotent_for_already_promoted_exception(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(input_file)

    promote_reviewed_exceptions(input_file)
    second_summary = promote_reviewed_exceptions(input_file)

    assert second_summary.promoted == 0
    assert second_summary.skipped_already_promoted == 1
    assert len(_rows(input_file, "BAO_NO_INPUT")) == 1


def test_missing_required_object_code_records_validation_error_and_cli_can_fail(tmp_path, monkeypatch, capsys):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(input_file, **{"Mã ĐT": "", "transaction_uid": "uid_missing_object", "Mã định danh": "uid_missing_object"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "promote_reviewed_exceptions.py",
            "--input-file",
            str(input_file),
            "--fail-on-validation-error",
        ],
    )

    assert promote_cli.main() == 2
    captured = capsys.readouterr()
    assert "Failed validation 1 rows." in captured.out
    assert "Validation failed for 1 reviewed exception rows" in captured.err

    exception_row = _exception_row(input_file)
    assert exception_row[EXCEPTION_STATUS_COLUMN] == STATUS_MISSING_DATA
    assert "Thiếu Mã ĐT" in exception_row[MISSING_ERROR_COLUMN]
    assert _rows(input_file, "BAO_NO_INPUT") == []


def test_thu_tien_mat_promotes_with_nguoi_nhan_tien(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(
        input_file,
        **{
            "Mã định danh": "uid_thu",
            "transaction_uid": "uid_thu",
            FLOW_COLUMN: FLOW_THU_TIEN_MAT,
            "TK nợ": "1111",
            "TK có": "1121CT",
            "Người nhận tiền": "Tran Thi Thu",
        },
    )

    summary = promote_reviewed_exceptions(input_file)

    assert summary.promoted == 1
    thu_rows = _rows(input_file, "THU_TIEN_MAT_INPUT")
    assert len(thu_rows) == 1
    assert thu_rows[0]["Người nhận tiền"] == "Tran Thi Thu"


def test_chi_tien_mat_promotes_with_nguoi_nop_tien(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(
        input_file,
        **{
            "Mã định danh": "uid_chi",
            "transaction_uid": "uid_chi",
            FLOW_COLUMN: FLOW_CHI_TIEN_MAT,
            "TK nợ": "1121CT",
            "TK có": "1111",
            "Người nộp tiền": "Tran Van Chi",
        },
    )

    summary = promote_reviewed_exceptions(input_file)

    assert summary.promoted == 1
    chi_rows = _rows(input_file, "CHI_TIEN_MAT_INPUT")
    assert len(chi_rows) == 1
    assert chi_rows[0]["Người nộp tiền"] == "Tran Van Chi"


def test_approval_yes_is_case_insensitive(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    for approval in ("YES", "Yes", "yes"):
        _append_exception(
            input_file,
            **{
                "Mã định danh": f"uid_{approval}",
                "transaction_uid": f"uid_{approval}",
                "Duyệt nhập RPA": approval,
            },
        )

    summary = promote_reviewed_exceptions(input_file)

    assert summary.promoted == 3
    assert len(_rows(input_file, "BAO_NO_INPUT")) == 3


def test_invalid_flow_records_error_without_copying(tmp_path):
    input_file = tmp_path / "rpa_input.xlsx"
    _make_workbook(input_file)
    _append_exception(input_file, **{FLOW_COLUMN: "khong_hop_le"})

    summary = promote_reviewed_exceptions(input_file)

    assert summary.failed_validation == 1
    exception_row = _exception_row(input_file)
    assert exception_row[EXCEPTION_STATUS_COLUMN] == STATUS_INVALID_FLOW
    assert "Luồng nhập RPA không hợp lệ" in exception_row[MISSING_ERROR_COLUMN]
    assert _rows(input_file, "BAO_NO_INPUT") == []
