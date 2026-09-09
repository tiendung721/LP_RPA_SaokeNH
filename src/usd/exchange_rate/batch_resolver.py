from __future__ import annotations

from datetime import date

from .models import ExchangeRateResult
from .provider import ExchangeRateProvider


class BatchExchangeRateResolver:
    def __init__(self, provider: ExchangeRateProvider):
        self.provider = provider
        self._cache: dict[date, ExchangeRateResult] = {}

    def resolve(self, transaction_dates: list[date] | set[date]) -> dict[date, ExchangeRateResult]:
        for transaction_date in sorted(set(transaction_dates)):
            if transaction_date not in self._cache:
                self._cache[transaction_date] = self.provider.get_rate(transaction_date)
        return {transaction_date: self._cache[transaction_date] for transaction_date in set(transaction_dates)}

    @property
    def cache(self) -> dict[date, ExchangeRateResult]:
        return dict(self._cache)
