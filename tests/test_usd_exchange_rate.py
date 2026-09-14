from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from src.usd.exchange_rate.batch_resolver import BatchExchangeRateResolver
from src.usd.exchange_rate.models import ExchangeRateResult
from src.usd.exchange_rate.msb_provider import MsbExchangeRateProvider, normalize_rate
from src.usd.profile import load_usd_profile


def _response(rate="26,120", market=1, currency="USD") -> str:
    return json.dumps(
        {
            "currencyOverview": [
                {
                    "currencyCode": currency,
                    "exchangeRatesData": [
                        {"currencyMarket": market, "buyRateValue": rate, "sellRateValue": "27,000"}
                    ],
                }
            ]
        }
    )


def test_msb_provider_uses_approved_query_market_and_buy_rate():
    calls = []

    def transport(url, timeout):
        calls.append((url, timeout))
        return 200, _response()

    profile = load_usd_profile("config/usd_msb.yaml")
    result = MsbExchangeRateProvider(profile, transport=transport).get_rate(date(2026, 6, 27))

    assert result.ok
    assert result.rate == Decimal("26120")
    assert result.board_number == 2
    assert not result.used_fallback_board
    assert len(calls) == 1
    query = parse_qs(urlparse(calls[0][0]).query)
    assert query == {"boardDate": ["27/06/2026"], "boardNumber": ["2"]}
    assert calls[0][1] == 10
    assert profile.currency_market == 1
    assert profile.rate_field == "buyRateValue"
    assert profile.fallback_board_numbers == (1,)


def test_msb_provider_falls_back_to_board_one_only_when_board_two_is_not_published(caplog):
    calls = []

    def transport(url, timeout):
        calls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/board-info"):
            return 200, json.dumps([{"boardNumber": 1, "boardType": "NY"}])
        if query["boardNumber"] == ["2"]:
            return 200, json.dumps({"currencyOverview": []})
        return 200, _response(rate="26,110")

    caplog.set_level(logging.WARNING)
    provider = MsbExchangeRateProvider(load_usd_profile("config/usd_msb.yaml"), transport=transport)

    result = provider.get_rate(date(2026, 6, 17))

    assert result.ok
    assert result.rate == Decimal("26110")
    assert result.board_number == 1
    assert result.preferred_board_number == 2
    assert result.used_fallback_board
    assert len(calls) == 3
    assert "sử dụng board 1 cùng ngày" in caplog.text


def test_msb_provider_does_not_fallback_when_board_two_is_published_but_overview_is_empty():
    calls = []

    def transport(url, timeout):
        calls.append(url)
        if urlparse(url).path.endswith("/board-info"):
            return 200, json.dumps([{"boardNumber": 2}, {"boardNumber": 1}])
        return 200, json.dumps({"currencyOverview": []})

    result = MsbExchangeRateProvider(
        load_usd_profile("config/usd_msb.yaml"), transport=transport
    ).get_rate(date(2026, 6, 17))

    assert not result.ok
    assert result.error_code == "EMPTY_OVERVIEW"
    assert "không fallback" in result.error_message
    assert len(calls) == 2


def test_msb_provider_reports_missing_same_day_fallback_board():
    def transport(url, timeout):
        if urlparse(url).path.endswith("/board-info"):
            return 200, json.dumps([])
        return 200, json.dumps({"currencyOverview": []})

    result = MsbExchangeRateProvider(
        load_usd_profile("config/usd_msb.yaml"), transport=transport
    ).get_rate(date(2026, 6, 17))

    assert result.error_code == "BOARD_UNAVAILABLE"


@pytest.mark.parametrize(
    ("status", "payload", "error_code"),
    [
        (500, _response(), "HTTP_ERROR"),
        ("invalid", _response(), "HTTP_ERROR"),
        (200, "not-json", "INVALID_JSON"),
        (200, json.dumps({"currencyOverview": []}), "EMPTY_OVERVIEW"),
        (200, _response(currency="EUR"), "CURRENCY_MISSING"),
        (200, _response(market=2), "MARKET_MISSING"),
        (200, _response(rate="--"), "RATE_INVALID"),
        (200, _response(rate="NaN"), "RATE_INVALID"),
        (200, _response(rate="0"), "RATE_INVALID"),
    ],
)
def test_msb_provider_returns_typed_failures(status, payload, error_code):
    profile = load_usd_profile("config/usd_msb.yaml")
    provider = MsbExchangeRateProvider(profile, transport=lambda url, timeout: (status, payload))

    result = provider.get_rate(date(2026, 6, 27))

    assert not result.ok
    assert result.error_code == error_code


def test_msb_provider_converts_timeout_to_failure():
    def timeout_transport(url, timeout):
        raise TimeoutError("slow")

    result = MsbExchangeRateProvider(
        load_usd_profile("config/usd_msb.yaml"), transport=timeout_transport
    ).get_rate(date(2026, 6, 27))
    assert result.error_code == "TIMEOUT"


def test_normalize_rate_keeps_decimal_value_without_rounding():
    assert normalize_rate("26,120.125") == Decimal("26120.125")


def test_batch_resolver_caches_success_and_failure_once_per_date():
    class Provider:
        def __init__(self):
            self.calls = []

        def get_rate(self, transaction_date):
            self.calls.append(transaction_date)
            if transaction_date.day == 2:
                return ExchangeRateResult.failure(transaction_date, "HTTP_ERROR", "failed")
            return ExchangeRateResult.success(transaction_date, Decimal("26120"))

    provider = Provider()
    resolver = BatchExchangeRateResolver(provider)
    first = date(2026, 6, 1)
    failed = date(2026, 6, 2)

    resolver.resolve([first, first, failed])
    resolver.resolve([failed, first])

    assert provider.calls == [first, failed]
    assert resolver.cache[failed].error_code == "HTTP_ERROR"
