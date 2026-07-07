from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None

from .flows import FLOW_BAO_CO, FLOW_BAO_NO
from .normalizer import clean_display_text, clean_string, normalize_text, parse_amount, parse_date


@dataclass(frozen=True)
class HistoricalMemoryMatch:
    code: str
    name: str
    reason: str
    flow: str
    account: str
    source: str
    source_file: str
    source_row: str
    score: float
    description_score: float
    hint_score: float


@dataclass(frozen=True)
class _HistoricalRecord:
    code: str
    name: str
    reason: str
    flow: str
    date_key: str
    amount_key: str
    account: str
    source: str
    source_file: str
    source_row: str
    description_norm: str
    reason_norm: str
    name_norm: str
    inferred_norm: str


class HistoricalMemoryMatcher:
    def __init__(
        self,
        records: list[_HistoricalRecord],
        min_unique_similarity: float = 35.0,
        min_ambiguous_similarity: float = 70.0,
        min_ambiguous_gap: float = 8.0,
    ):
        self.records = records
        self.min_unique_similarity = min_unique_similarity
        self.min_ambiguous_similarity = min_ambiguous_similarity
        self.min_ambiguous_gap = min_ambiguous_gap
        self._by_key: dict[tuple[str, str, str], list[_HistoricalRecord]] = {}
        for record in records:
            self._by_key.setdefault((record.flow, record.date_key, record.amount_key), []).append(record)

    @classmethod
    def from_excel(
        cls,
        path: str | Path,
        min_unique_similarity: float = 35.0,
        min_ambiguous_similarity: float = 70.0,
        min_ambiguous_gap: float = 8.0,
    ) -> "HistoricalMemoryMatcher":
        path = Path(path)
        if not path.exists():
            return cls([], min_unique_similarity, min_ambiguous_similarity, min_ambiguous_gap)
        try:
            detail = pd.read_excel(path, sheet_name="03_Chi_tiet", dtype=object)
        except Exception:  # noqa: BLE001
            return cls([], min_unique_similarity, min_ambiguous_similarity, min_ambiguous_gap)
        return cls(
            _records_from_detail_sheet(detail),
            min_unique_similarity,
            min_ambiguous_similarity,
            min_ambiguous_gap,
        )

    def match(self, transaction: Any, flow: str, amount: float, counterparty_hint: str = "") -> HistoricalMemoryMatch | None:
        date_key = _date_key(getattr(transaction, "transaction_date", None))
        amount_key = _amount_key(amount)
        candidates = self._by_key.get((flow, date_key, amount_key), [])
        if not candidates:
            return None

        description_norm = normalize_text(getattr(transaction, "description", ""))
        counterparty_norm = normalize_text(getattr(transaction, "counterparty_raw", ""))
        hint_norm = normalize_text(counterparty_hint)
        ranked = sorted(
            (_score_record(record, description_norm, counterparty_norm, hint_norm) for record in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best_description_score, best_hint_score, best = ranked[0]
        distinct_answers = {(record.code, record.account, record.reason) for record in candidates}

        if len(distinct_answers) == 1:
            if best_score < self.min_unique_similarity:
                return None
            return _to_match(best, best_score, best_description_score, best_hint_score)

        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < self.min_ambiguous_similarity or best_score - second_score < self.min_ambiguous_gap:
            return None
        return _to_match(best, best_score, best_description_score, best_hint_score)


def _records_from_detail_sheet(detail: pd.DataFrame) -> list[_HistoricalRecord]:
    if detail.empty or len(detail.columns) < 22:
        return []
    cols = list(detail.columns)
    records: list[_HistoricalRecord] = []
    for _, row in detail.iterrows():
        flow = _flow_key(row[cols[14]])
        if flow not in {FLOW_BAO_NO, FLOW_BAO_CO}:
            continue
        amount = parse_amount(row[cols[20]] if flow == FLOW_BAO_NO else row[cols[19]])
        if amount <= 0:
            continue
        code = clean_string(row[cols[6]])
        reason = clean_display_text(row[cols[9]])
        account = _counter_account(row, cols, flow)
        if not code or not reason or not account:
            continue
        records.append(
            _HistoricalRecord(
                code=code,
                name=clean_display_text(row[cols[7]]),
                reason=reason,
                flow=flow,
                date_key=_date_key(parse_date(row[cols[4]])),
                amount_key=_amount_key(amount),
                account=account,
                source=clean_string(row[cols[0]]),
                source_file=clean_string(row[cols[1]]),
                source_row=clean_string(row[cols[3]]),
                description_norm=normalize_text(row[cols[10]]),
                reason_norm=normalize_text(row[cols[9]]),
                name_norm=normalize_text(row[cols[7]]),
                inferred_norm=normalize_text(row[cols[11]]),
            )
        )
    return records


def _counter_account(row: pd.Series, cols: list[Any], flow: str) -> str:
    tk_du = clean_string(row[cols[16]])
    if tk_du:
        return tk_du
    fallback_idx = 17 if flow == FLOW_BAO_NO else 18
    return clean_string(row[cols[fallback_idx]])


def _score_record(
    record: _HistoricalRecord,
    description_norm: str,
    counterparty_norm: str,
    hint_norm: str,
) -> tuple[float, float, float, _HistoricalRecord]:
    history_fields = [
        record.description_norm,
        record.reason_norm,
        record.name_norm,
        record.inferred_norm,
        normalize_text(record.code),
    ]
    description_score = max(_similarity(description_norm, field) for field in history_fields)
    if counterparty_norm:
        description_score = max(description_score, max(_similarity(counterparty_norm, field) for field in history_fields))
    hint_score = max(_similarity(hint_norm, field) for field in history_fields) if hint_norm else 0.0
    return max(description_score, hint_score), description_score, hint_score, record


def _to_match(
    record: _HistoricalRecord,
    score: float,
    description_score: float,
    hint_score: float,
) -> HistoricalMemoryMatch:
    return HistoricalMemoryMatch(
        code=record.code,
        name=record.name,
        reason=record.reason,
        flow=record.flow,
        account=record.account,
        source=f"historical_memory:{record.source}",
        source_file=record.source_file,
        source_row=record.source_row,
        score=score,
        description_score=description_score,
        hint_score=hint_score,
    )


def _flow_key(value: Any) -> str:
    normalized = normalize_text(value)
    if normalized == "CHI BAO NO":
        return FLOW_BAO_NO
    if normalized == "THU BAO CO":
        return FLOW_BAO_CO
    return ""


def _date_key(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


def _amount_key(value: Any) -> str:
    amount = parse_amount(value)
    return f"{amount:.2f}"


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 100.0
    if fuzz:
        return float(fuzz.token_set_ratio(left, right))
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return 100.0 * len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
