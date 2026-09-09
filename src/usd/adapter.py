from __future__ import annotations

from decimal import Decimal

from ..flows import FLOW_BAO_CO, FLOW_BAO_NO, FLOW_THU_TIEN_MAT, MONEY_IN, MONEY_OUT, MONEY_UNKNOWN
from ..models import ExtractedEntities, ProcessedTransaction, Transaction
from ..normalizer import normalize_text
from .classifier import RULE_CASH_WITHDRAWAL, RULE_CREDIT_DEFAULT, RULE_DEBIT_DEFAULT, RULE_DEBIT_PORT_PAYMENT
from .models import STATUS_ERROR, STATUS_READY, USDProcessingOutcome, USDSourceTransaction
from .identity import assign_source_transaction_uids


def outcomes_to_processed(outcomes: list[USDProcessingOutcome]) -> list[ProcessedTransaction]:
    processed: list[ProcessedTransaction] = []
    for outcome in outcomes:
        if outcome.status == STATUS_READY:
            processed.extend(_entry_record(outcome, index) for index in range(len(outcome.entries)))
        else:
            processed.append(_outcome_record(outcome))
    return processed


def configuration_error_records(transactions: list[Transaction], error_note: str) -> list[ProcessedTransaction]:
    outcomes = [
        USDProcessingOutcome(
            source=USDSourceTransaction(
                transaction=transaction,
                source_transaction_uid=source_uid,
                foreign_amount=Decimal(str(transaction.debit_amount or transaction.credit_amount or 0)),
                classification="usd_configuration_error",
            ),
            status=STATUS_ERROR,
            error_note=f"USD_CONFIGURATION_ERROR: {error_note}",
        )
        for transaction, source_uid in zip(transactions, assign_source_transaction_uids(transactions))
    ]
    return outcomes_to_processed(outcomes)


def _entry_record(outcome: USDProcessingOutcome, index: int) -> ProcessedTransaction:
    source = outcome.source
    transaction = source.transaction
    entry = outcome.entries[index]
    cash_person = entry.payer_name or entry.receiver_name
    return ProcessedTransaction(
        source_file=transaction.source_file,
        original_row_index=transaction.original_row_index,
        bank=transaction.bank,
        flow=entry.flow,
        transaction_date=entry.transaction_date,
        object_code="",
        object_name="",
        reason=entry.reason,
        debit_account=entry.debit_account,
        credit_account=entry.credit_account,
        amount=entry.amount,
        use_case=entry.rule_id,
        original_content=transaction.description,
        counterparty_raw=transaction.counterparty_raw,
        doc_no=transaction.doc_no,
        status="OK",
        error_note="",
        confidence=1.0,
        normalized_content=normalize_text(transaction.description),
        normalized_counterparty=normalize_text(transaction.counterparty_raw),
        matched_rule=entry.rule_id,
        raw_data=transaction.raw_data,
        entities=ExtractedEntities(cash_person_name=cash_person, cash_person_source="usd_rule" if cash_person else ""),
        transaction_uid=entry.entry_uid,
        source_sheet=transaction.source_sheet,
        bank_direction=_bank_direction(transaction.debit_amount, transaction.credit_amount),
        foreign_currency=entry.foreign_currency,
        foreign_amount=entry.foreign_amount,
        exchange_rate=entry.exchange_rate,
        source_transaction_uid=entry.source_transaction_uid,
        entry_uid=entry.entry_uid,
        payer_name=entry.payer_name,
        receiver_name=entry.receiver_name,
    )


def _outcome_record(outcome: USDProcessingOutcome) -> ProcessedTransaction:
    source = outcome.source
    transaction = source.transaction
    flow = {
        RULE_CREDIT_DEFAULT: FLOW_BAO_CO,
        RULE_DEBIT_DEFAULT: FLOW_BAO_NO,
        RULE_DEBIT_PORT_PAYMENT: FLOW_BAO_NO,
        RULE_CASH_WITHDRAWAL: FLOW_THU_TIEN_MAT,
    }.get(source.classification, "")
    return ProcessedTransaction(
        source_file=transaction.source_file,
        original_row_index=transaction.original_row_index,
        bank=transaction.bank,
        flow=flow,
        transaction_date=transaction.transaction_date,
        object_code="",
        object_name="",
        reason="",
        debit_account="",
        credit_account="",
        amount=Decimal("0"),
        use_case=source.classification,
        original_content=transaction.description,
        counterparty_raw=transaction.counterparty_raw,
        doc_no=transaction.doc_no,
        status=outcome.status,
        error_note=outcome.error_note,
        confidence=1.0,
        normalized_content=normalize_text(transaction.description),
        normalized_counterparty=normalize_text(transaction.counterparty_raw),
        matched_rule=source.classification,
        raw_data=transaction.raw_data,
        transaction_uid=source.source_transaction_uid,
        source_sheet=transaction.source_sheet,
        bank_direction=_bank_direction(transaction.debit_amount, transaction.credit_amount),
        foreign_currency="USD",
        foreign_amount=source.foreign_amount,
        exchange_rate=Decimal("0"),
        source_transaction_uid=source.source_transaction_uid,
        entry_uid="",
        skip_reason=outcome.skip_reason,
    )


def _bank_direction(debit: float, credit: float) -> str:
    if debit > 0 and credit <= 0:
        return MONEY_OUT
    if credit > 0 and debit <= 0:
        return MONEY_IN
    return MONEY_UNKNOWN
