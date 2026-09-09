from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..flows import FLOW_BAO_CO, FLOW_BAO_NO, FLOW_CHI_TIEN_MAT, FLOW_THU_TIEN_MAT
from ..models import Transaction
from .classifier import (
    RULE_BANK_FEE,
    RULE_CASH_WITHDRAWAL,
    RULE_CREDIT_DEFAULT,
    RULE_DEBIT_DEFAULT,
    RULE_DEBIT_PORT_PAYMENT,
    RULE_FOREIGN_CURRENCY_SALE,
    USDClassification,
    USDClassifier,
)
from .exchange_rate.batch_resolver import BatchExchangeRateResolver
from .exchange_rate.msb_provider import MsbExchangeRateProvider, Transport
from .identity import assign_source_transaction_uids, entry_uid
from .models import (
    AccountingEntry,
    STATUS_ERROR,
    STATUS_MISSING_EXCHANGE_RATE,
    STATUS_READY,
    STATUS_SKIPPED,
    USDProcessingOutcome,
    USDSourceTransaction,
)
from .profile import USDProfile
from .verifier import USDAccountingVerifier


class USDProcessor:
    def __init__(self, profile: USDProfile, transport: Transport | None = None):
        self.profile = profile
        self.classifier = USDClassifier()
        self.resolver = BatchExchangeRateResolver(MsbExchangeRateProvider(profile, transport=transport))
        self.verifier = USDAccountingVerifier(profile)

    def process_batch(self, transactions: list[Transaction]) -> list[USDProcessingOutcome]:
        source_uids = assign_source_transaction_uids(transactions)
        sources: list[tuple[USDSourceTransaction, USDClassification]] = []
        outcomes: dict[str, USDProcessingOutcome] = {}

        for transaction, source_uid in zip(transactions, source_uids):
            classification = self.classifier.classify(transaction)
            source = USDSourceTransaction(
                transaction=transaction,
                source_transaction_uid=source_uid,
                foreign_amount=_source_amount(transaction),
                classification=classification.rule_id,
            )
            sources.append((source, classification))
            if classification.action == "SKIP":
                reason = "FOREIGN_CURRENCY_SALE" if classification.rule_id == RULE_FOREIGN_CURRENCY_SALE else "BANK_FEE"
                outcomes[source_uid] = USDProcessingOutcome(source=source, status=STATUS_SKIPPED, skip_reason=reason)
            elif classification.action == "ERROR":
                outcomes[source_uid] = USDProcessingOutcome(
                    source=source,
                    status=STATUS_ERROR,
                    error_note=classification.error_note,
                )
            elif transaction.transaction_date is None:
                outcomes[source_uid] = USDProcessingOutcome(
                    source=source,
                    status=STATUS_ERROR,
                    error_note="Không parse được ngày giao dịch USD",
                )

        required_dates = {
            source.transaction.transaction_date
            for source, classification in sources
            if classification.requires_rate
            and source.source_transaction_uid not in outcomes
            and source.transaction.transaction_date is not None
        }
        rate_results = self.resolver.resolve(required_dates)

        for source, classification in sources:
            if source.source_transaction_uid in outcomes:
                continue
            transaction_date = source.transaction.transaction_date
            if transaction_date is None:
                continue
            rate_result = rate_results[transaction_date]
            if not rate_result.ok:
                source.rate_error = rate_result.error_code
                outcomes[source.source_transaction_uid] = USDProcessingOutcome(
                    source=source,
                    status=STATUS_MISSING_EXCHANGE_RATE,
                    error_note=(
                        f"MISSING_EXCHANGE_RATE [{rate_result.error_code}]: "
                        f"{rate_result.error_message}"
                    ),
                )
                continue
            source.exchange_rate = rate_result.rate
            entries = self._create_entries(source, classification)
            verification_errors = self.verifier.verify(source, entries)
            if verification_errors:
                outcomes[source.source_transaction_uid] = USDProcessingOutcome(
                    source=source,
                    status=STATUS_ERROR,
                    error_note="; ".join(verification_errors),
                )
            else:
                outcomes[source.source_transaction_uid] = USDProcessingOutcome(
                    source=source,
                    status=STATUS_READY,
                    entries=entries,
                )

        return [outcomes[source_uid] for source_uid in source_uids]

    def _create_entries(self, source: USDSourceTransaction, classification: USDClassification) -> list[AccountingEntry]:
        transaction_date = source.transaction.transaction_date
        exchange_rate = source.exchange_rate
        if transaction_date is None or exchange_rate is None:
            return []
        common = {
            "source_transaction_uid": source.source_transaction_uid,
            "transaction_date": transaction_date,
            "foreign_currency": self.profile.currency,
            "foreign_amount": source.foreign_amount,
            "exchange_rate": exchange_rate,
            "rule_id": classification.rule_id,
        }
        if classification.rule_id == RULE_CASH_WITHDRAWAL:
            return [
                AccountingEntry(
                    entry_uid=entry_uid(source.source_transaction_uid, "THU_TM"),
                    flow=FLOW_THU_TIEN_MAT,
                    debit_account=self.profile.cash_account,
                    credit_account=self.profile.bank_usd_account,
                    reason=self.profile.cash_receipt_reason,
                    payer_name=classification.employee_name,
                    **common,
                ),
                AccountingEntry(
                    entry_uid=entry_uid(source.source_transaction_uid, "CHI_TM"),
                    flow=FLOW_CHI_TIEN_MAT,
                    debit_account=self.profile.advance_account,
                    credit_account=self.profile.cash_account,
                    reason=self.profile.cash_payment_reason,
                    receiver_name=self.profile.cash_payment_receiver,
                    **common,
                ),
            ]
        if classification.rule_id == RULE_CREDIT_DEFAULT:
            return [
                AccountingEntry(
                    entry_uid=entry_uid(source.source_transaction_uid),
                    flow=FLOW_BAO_CO,
                    debit_account=self.profile.bank_usd_account,
                    credit_account=self.profile.receivable_offset_account,
                    reason=self.profile.vessel_reason,
                    **common,
                )
            ]
        reason = self.profile.port_reason if classification.rule_id == RULE_DEBIT_PORT_PAYMENT else self.profile.vessel_reason
        return [
            AccountingEntry(
                entry_uid=entry_uid(source.source_transaction_uid),
                flow=FLOW_BAO_NO,
                debit_account=self.profile.advance_account,
                credit_account=self.profile.bank_usd_account,
                reason=reason,
                **common,
            )
        ]


def _source_amount(transaction: Transaction) -> Decimal:
    amount = transaction.debit_amount if transaction.debit_amount > 0 else transaction.credit_amount
    return Decimal(str(amount or 0))
