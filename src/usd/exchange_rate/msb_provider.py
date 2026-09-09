from __future__ import annotations

import json
import socket
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..profile import USDProfile
from .models import ExchangeRateResult


Transport = Callable[[str, float], tuple[int, bytes | str]]


class MsbExchangeRateProvider:
    def __init__(self, profile: USDProfile, transport: Transport | None = None):
        self.profile = profile
        self.transport = transport or _urllib_transport

    def get_rate(self, transaction_date: date) -> ExchangeRateResult:
        query = urlencode(
            {
                "boardDate": transaction_date.strftime("%d/%m/%Y"),
                "boardNumber": self.profile.board_number,
            }
        )
        url = f"{self.profile.exchange_rate_endpoint}?{query}"
        try:
            status, payload = self.transport(url, self.profile.timeout_seconds)
        except TimeoutError:
            return _failure(transaction_date, "TIMEOUT", "MSB exchange-rate request timed out")
        except (HTTPError, URLError, socket.timeout, OSError) as exc:
            return _failure(transaction_date, "HTTP_ERROR", f"MSB exchange-rate request failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - transport is injectable and must not abort a batch
            return _failure(transaction_date, "HTTP_ERROR", f"MSB exchange-rate request failed: {exc}")

        try:
            http_status = int(status)
        except (TypeError, ValueError):
            return _failure(transaction_date, "HTTP_ERROR", f"Invalid MSB exchange-rate HTTP status: {status}")
        if http_status < 200 or http_status >= 300:
            return _failure(transaction_date, "HTTP_ERROR", f"MSB exchange-rate HTTP status {status}")
        try:
            data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            return _failure(transaction_date, "INVALID_JSON", f"Invalid MSB exchange-rate JSON: {exc}")
        if not isinstance(data, dict):
            return _failure(transaction_date, "INVALID_JSON", "MSB exchange-rate response must be an object")

        overview = data.get("currencyOverview")
        if not isinstance(overview, list) or not overview:
            return _failure(transaction_date, "EMPTY_OVERVIEW", "currencyOverview is empty")
        currency = next(
            (
                item
                for item in overview
                if isinstance(item, dict) and str(item.get("currencyCode", "")).strip().upper() == self.profile.currency
            ),
            None,
        )
        if currency is None:
            return _failure(transaction_date, "CURRENCY_MISSING", f"Currency {self.profile.currency} is missing")
        rates = currency.get("exchangeRatesData")
        if not isinstance(rates, list):
            return _failure(transaction_date, "MARKET_MISSING", "exchangeRatesData is missing")
        market = next(
            (
                item
                for item in rates
                if isinstance(item, dict) and _same_number(item.get("currencyMarket"), self.profile.currency_market)
            ),
            None,
        )
        if market is None:
            return _failure(transaction_date, "MARKET_MISSING", f"currencyMarket {self.profile.currency_market} is missing")
        try:
            rate = normalize_rate(market.get(self.profile.rate_field))
        except ValueError as exc:
            return _failure(transaction_date, "RATE_INVALID", str(exc))
        return ExchangeRateResult.success(transaction_date, rate)


def normalize_rate(value: Any) -> Decimal:
    text = str(value or "").strip().replace(" ", "")
    if not text or text in {"-", "--"}:
        raise ValueError("Exchange rate is empty")
    text = text.replace(",", "")
    try:
        rate = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid exchange rate: {value}") from exc
    if not rate.is_finite() or rate <= 0:
        raise ValueError(f"Invalid exchange rate: {value}")
    return rate


def _same_number(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _failure(transaction_date: date, code: str, message: str) -> ExchangeRateResult:
    return ExchangeRateResult.failure(transaction_date, code, message)


def _urllib_transport(url: str, timeout_seconds: float) -> tuple[int, bytes]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - endpoint is controlled by config
        return int(getattr(response, "status", 200)), response.read()
