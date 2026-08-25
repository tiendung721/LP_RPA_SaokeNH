from __future__ import annotations

import logging

import pytest

from src import excel_io
from src.excel_io import atomic_output_path
from src.logger_setup import setup_logger


def test_atomic_output_keeps_old_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "workbook.xlsx"
    target.write_bytes(b"old workbook")

    def fail_replace(source, destination):
        raise PermissionError("Excel is locking the file")

    monkeypatch.setattr(excel_io.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="locking"):
        with atomic_output_path(target) as temporary:
            temporary.write_bytes(b"new workbook")

    assert target.read_bytes() == b"old workbook"
    assert list(tmp_path.glob(".workbook.*.xlsx")) == []


def test_logger_is_console_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = setup_logger()

    assert logger.handlers
    assert all(isinstance(handler, logging.StreamHandler) for handler in logger.handlers)
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers)
    assert not (tmp_path / "agent_run.log").exists()
