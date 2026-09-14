from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..models import Transaction


STATUS_READY = "READY"
STATUS_SKIPPED = "SKIPPED"
STATUS_MISSING_EXCHANGE_RATE = "MISSING_EXCHANGE_RATE"
STATUS_ERROR = "ERROR"


@dataclass
class USDSourceTransaction:
    transaction: Transaction
    source_transaction_uid: str
    foreign_amount: Decimal
    classification: str = ""
    exchange_rate: Decimal | None = None
    exchange_rate_board_number: int | None = None
    rate_error: str = ""


@dataclass(frozen=True)
class AccountingEntry:
    source_transaction_uid: str
    entry_uid: str
    flow: str
    transaction_date: date
    debit_account: str
    credit_account: str
    reason: str
    foreign_currency: str
    foreign_amount: Decimal
    exchange_rate: Decimal
    payer_name: str = ""
    receiver_name: str = ""
    rule_id: str = ""
    status: str = STATUS_READY
    skip_reason: str = ""

    @property
    def amount(self) -> Decimal:
        return self.foreign_amount * self.exchange_rate


@dataclass
class USDProcessingOutcome:
    source: USDSourceTransaction
    status: str
    skip_reason: str = ""
    error_note: str = ""
    entries: list[AccountingEntry] = field(default_factory=list)
