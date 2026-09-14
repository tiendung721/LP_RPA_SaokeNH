from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExchangeRateResult:
    transaction_date: date
    rate: Decimal | None = None
    board_number: int | None = None
    preferred_board_number: int | None = None
    error_code: str = ""
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.rate is not None and self.rate > 0 and not self.error_code

    @classmethod
    def success(
        cls,
        transaction_date: date,
        rate: Decimal,
        board_number: int | None = None,
        preferred_board_number: int | None = None,
    ) -> "ExchangeRateResult":
        return cls(
            transaction_date=transaction_date,
            rate=rate,
            board_number=board_number,
            preferred_board_number=preferred_board_number,
        )

    @property
    def used_fallback_board(self) -> bool:
        return (
            self.ok
            and self.board_number is not None
            and self.preferred_board_number is not None
            and self.board_number != self.preferred_board_number
        )

    @classmethod
    def failure(cls, transaction_date: date, code: str, message: str) -> "ExchangeRateResult":
        return cls(transaction_date=transaction_date, error_code=code, error_message=message)
