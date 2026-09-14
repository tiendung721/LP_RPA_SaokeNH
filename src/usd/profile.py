from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class USDProfileError(ValueError):
    """Raised when the MSB USD profile is incomplete or invalid."""


@dataclass(frozen=True)
class USDProfile:
    bank: str
    currency: str
    bank_usd_account: str
    receivable_offset_account: str
    advance_account: str
    cash_account: str
    cash_payment_receiver: str
    cash_receipt_reason: str
    cash_payment_reason: str
    vessel_reason: str
    port_reason: str
    exchange_rate_endpoint: str
    board_info_endpoint: str
    board_number: int
    fallback_board_numbers: tuple[int, ...]
    currency_market: int
    rate_field: str
    timeout_seconds: float


def load_usd_profile(path: str | Path) -> USDProfile:
    path = Path(path)
    if not path.exists():
        raise USDProfileError(f"Không tìm thấy USD profile: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    profile = data.get("profile", {}) or {}
    accounts = profile.get("accounts", {}) or {}
    reasons = profile.get("reasons", {}) or {}
    cash = profile.get("cash_withdrawal", {}) or {}
    exchange = profile.get("exchange_rate", {}) or {}

    required = {
        "profile.bank": profile.get("bank"),
        "profile.currency": profile.get("currency"),
        "profile.accounts.bank_usd": accounts.get("bank_usd"),
        "profile.accounts.receivable_offset": accounts.get("receivable_offset"),
        "profile.accounts.advance": accounts.get("advance"),
        "profile.accounts.cash": accounts.get("cash"),
        "profile.cash_withdrawal.payment_receiver": cash.get("payment_receiver"),
        "profile.reasons.cash_receipt": reasons.get("cash_receipt"),
        "profile.reasons.cash_payment": reasons.get("cash_payment"),
        "profile.reasons.vessel": reasons.get("vessel"),
        "profile.reasons.port": reasons.get("port"),
        "profile.exchange_rate.endpoint": exchange.get("endpoint"),
        "profile.exchange_rate.board_info_endpoint": exchange.get("board_info_endpoint"),
        "profile.exchange_rate.board_number": exchange.get("board_number"),
        "profile.exchange_rate.currency_market": exchange.get("currency_market"),
        "profile.exchange_rate.rate_field": exchange.get("rate_field"),
        "profile.exchange_rate.timeout_seconds": exchange.get("timeout_seconds"),
    }
    missing = [name for name, value in required.items() if value is None or str(value).strip() == ""]
    if missing:
        raise USDProfileError("Thiếu cấu hình USD: " + ", ".join(missing))

    rate_field = str(exchange["rate_field"]).strip()
    if rate_field not in {"buyRateValue", "sellRateValue"}:
        raise USDProfileError("rate_field phải là buyRateValue hoặc sellRateValue")
    timeout = _positive_float(exchange["timeout_seconds"], "timeout_seconds")
    board_number = _positive_int(exchange["board_number"], "board_number")
    fallback_board_numbers = tuple(
        _positive_int(value, "fallback_board_numbers")
        for value in exchange.get("fallback_board_numbers", []) or []
    )
    if board_number in fallback_board_numbers:
        raise USDProfileError("fallback_board_numbers không được chứa board_number ưu tiên")

    return USDProfile(
        bank=str(profile["bank"]).strip().upper(),
        currency=str(profile["currency"]).strip().upper(),
        bank_usd_account=str(accounts["bank_usd"]).strip(),
        receivable_offset_account=str(accounts["receivable_offset"]).strip(),
        advance_account=str(accounts["advance"]).strip(),
        cash_account=str(accounts["cash"]).strip(),
        cash_payment_receiver=str(cash["payment_receiver"]).strip(),
        cash_receipt_reason=str(reasons["cash_receipt"]).strip(),
        cash_payment_reason=str(reasons["cash_payment"]).strip(),
        vessel_reason=str(reasons["vessel"]).strip(),
        port_reason=str(reasons["port"]).strip(),
        exchange_rate_endpoint=str(exchange["endpoint"]).strip(),
        board_info_endpoint=str(exchange["board_info_endpoint"]).strip(),
        board_number=board_number,
        fallback_board_numbers=fallback_board_numbers,
        currency_market=_positive_int(exchange["currency_market"], "currency_market"),
        rate_field=rate_field,
        timeout_seconds=timeout,
    )


def _positive_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise USDProfileError(f"{field} phải là số dương") from exc
    if number <= 0:
        raise USDProfileError(f"{field} phải là số dương")
    return number


def _positive_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise USDProfileError(f"{field} phải là số nguyên dương") from exc
    if number <= 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise USDProfileError(f"{field} phải là số nguyên dương")
    return number
