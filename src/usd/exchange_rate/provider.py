from __future__ import annotations

from datetime import date
from typing import Protocol

from .models import ExchangeRateResult


class ExchangeRateProvider(Protocol):
    def get_rate(self, transaction_date: date) -> ExchangeRateResult:
        ...
