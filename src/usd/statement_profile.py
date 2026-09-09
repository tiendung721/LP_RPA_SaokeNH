from __future__ import annotations

import re
from pathlib import Path

from ..file_utils import get_sheet_names, read_excel_rows
from ..normalizer import normalize_text


SUPPORTED_CURRENCIES = ("USD", "VND")


def detect_statement_currency(path: str | Path) -> str:
    """Read only statement metadata rows; never infer currency from transactions."""
    for sheet_name in get_sheet_names(path):
        sample = read_excel_rows(path, sheet_name=sheet_name, nrows=12)
        for _, row in sample.iterrows():
            cells = [normalize_text(value) for value in row.tolist()]
            if not any("LOAI TIEN" in cell or "CURRENCY" in cell for cell in cells):
                continue
            joined = " ".join(cell for cell in cells if cell)
            matches = [currency for currency in SUPPORTED_CURRENCIES if _contains_token(joined, currency)]
            if len(matches) == 1:
                return matches[0]
    return ""


def _contains_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text) is not None
