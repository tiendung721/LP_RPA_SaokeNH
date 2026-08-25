from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .accounting_verifier import AccountingVerifier
from .bank_detector import detect_bank
from .config_loader import load_rules
from .entity_extractor import EntityExtractor, OwnCompanyConfig
from .file_utils import list_statement_files
from .flows import (
    CASH_ACCOUNT,
    FLOW_BAO_CO,
    FLOW_BAO_NO,
    FLOW_CHI_TIEN_MAT,
    FLOW_THU_TIEN_MAT,
    MONEY_IN,
    MONEY_OUT,
    MONEY_UNKNOWN,
)
from .foreign_exchange import extract_foreign_exchange, format_foreign_exchange_reason
from .historical_memory import HistoricalMemoryMatch, HistoricalMemoryMatcher
from .models import CatalogObject, ExtractedEntities, ObjectCandidate, ObjectMatchResult, ProcessedTransaction, Rule, Transaction
from .normalizer import normalize_text
from .object_aliases import load_object_aliases
from .object_matcher import ObjectMatcher, load_catalog
from .object_overrides import load_object_overrides
from .parsers.acb_parser import ACBParser
from .parsers.msb_parser import MSBParser
from .parsers.vcb_parser import VCBParser
from .reason_aliases import ReasonPurpose, load_object_name_purposes, load_object_purpose_defaults, load_reason_purposes
from .reason_generator import clean_reason_value, generate_reason, has_usable_object_code, reason_requires_object_code
from .rule_engine import RuleEngine
from .transaction_identity import assign_transaction_uids, build_transaction_uid, transaction_fingerprint


PARSERS = {
    "ACB": ACBParser,
    "MSB": MSBParser,
    "VCB": VCBParser,
}

INTERNAL_OBJECT_CATALOG = "internal"


def process_all(
    statements_dir: str | Path,
    receivable_path: str | Path,
    payable_path: str | Path,
    rules_path: str | Path | None,
    default_rules_path: str | Path,
    config: dict[str, Any],
    logger: logging.Logger,
) -> list[ProcessedTransaction]:
    logger.info("Bắt đầu chạy bank statement processor")
    logger.info("Statements dir: %s", statements_dir)
    logger.info("Receivable catalog: %s", receivable_path)
    logger.info("Payable catalog: %s", payable_path)

    project_root = Path(default_rules_path).resolve().parents[1]
    matching_cfg = config.get("matching", {})
    min_score = float(matching_cfg.get("min_score", 80))
    min_gap = float(matching_cfg.get("min_gap", 8))
    ambiguous_min_score = float(matching_cfg.get("ambiguous_min_score", 90))

    own_company_path = _resolve_config_path(config.get("own_company_file", "config/own_company.yaml"), project_root)
    aliases_path = _resolve_config_path(config.get("object_aliases_file", "config/object_aliases.yaml"), project_root)
    reason_aliases_path = _resolve_config_path(config.get("reason_aliases_file", "config/reason_aliases.yaml"), project_root)
    own_company = OwnCompanyConfig.from_yaml(own_company_path)
    object_aliases = load_object_aliases(aliases_path)
    config["_reason_purposes"] = load_reason_purposes(reason_aliases_path)
    config["_object_purpose_defaults"] = load_object_purpose_defaults(reason_aliases_path)
    config["_object_name_purposes"] = load_object_name_purposes(reason_aliases_path)
    overrides_path = _resolve_config_path(config.get("object_overrides_file", "config/object_overrides.yaml"), project_root)
    object_overrides = load_object_overrides(overrides_path)
    entity_extractor = EntityExtractor(own_company)
    verifier = AccountingVerifier(config.get("bank_accounts", {}), own_company)

    receivable_matcher = _load_matcher(
        receivable_path,
        min_score,
        min_gap,
        ambiguous_min_score,
        "phải thu",
        logger,
        aliases=_merge_aliases(object_aliases.get("receivable", {}), object_overrides.get("receivable", {}).get("aliases", {})),
        exact_phrase_overrides=object_overrides.get("receivable", {}).get("exact_phrases", {}),
        supplemental_objects=object_overrides.get("receivable", {}).get("supplemental_objects", []),
        own_company=own_company,
    )
    payable_matcher = _load_matcher(
        payable_path,
        min_score,
        min_gap,
        ambiguous_min_score,
        "phải trả",
        logger,
        aliases=_merge_aliases(object_aliases.get("payable", {}), object_overrides.get("payable", {}).get("aliases", {})),
        exact_phrase_overrides=object_overrides.get("payable", {}).get("exact_phrases", {}),
        supplemental_objects=object_overrides.get("payable", {}).get("supplemental_objects", []),
        own_company=own_company,
    )
    internal_path = _resolve_config_path(config.get("internal_objects_file", "input/MA NOI BO CTY.xlsx"), project_root)
    internal_matcher = _load_internal_matcher(
        internal_path,
        min_score,
        min_gap,
        ambiguous_min_score,
        logger,
        aliases=_merge_aliases(
            object_aliases.get(INTERNAL_OBJECT_CATALOG, {}),
            object_overrides.get(INTERNAL_OBJECT_CATALOG, {}).get("aliases", {}),
        ),
        exact_phrase_overrides=object_overrides.get(INTERNAL_OBJECT_CATALOG, {}).get("exact_phrases", {}),
        supplemental_objects=object_overrides.get(INTERNAL_OBJECT_CATALOG, {}).get("supplemental_objects", []),
        own_company=own_company,
    )
    historical_memory = _load_historical_memory(config, project_root, logger)

    rules, rule_source = load_rules(rules_path, default_rules_path, logger=logger)
    logger.info("Rule source: %s", rule_source)
    rule_engine = RuleEngine(rules)

    statement_files = list_statement_files(statements_dir)
    logger.info("Đọc được %s file sao kê", len(statement_files))

    run_stats = config.setdefault("_run_stats", {})
    run_stats.update(
        {
            "input_transaction_count": 0,
            "skipped_non_transaction_rows": 0,
            "duplicate_count": 0,
            "parser_warnings": [],
        }
    )

    processed: list[ProcessedTransaction] = []
    for statement_file in statement_files:
        try:
            bank = detect_bank(statement_file, logger=logger)
            if not bank:
                logger.error("Không nhận diện được ngân hàng: %s", statement_file)
                continue
            logger.info("File %s được nhận diện là %s", statement_file.name, bank)
            parser = PARSERS[bank]()
            transactions = parser.parse(statement_file)
            run_stats["skipped_non_transaction_rows"] += int(getattr(parser, "skipped_row_count", 0) or 0)
            run_stats["parser_warnings"].extend(getattr(parser, "warnings", []) or [])
            logger.info("Parse được %s dòng giao dịch từ %s", len(transactions), statement_file.name)
        except Exception as exc:  # noqa: BLE001 - continue next file
            logger.exception("Lỗi đọc/parse file %s: %s", statement_file, exc)
            continue

        run_stats["input_transaction_count"] += len(transactions)
        for transaction in transactions:
            item = process_transaction(
                transaction=transaction,
                config=config,
                rule_engine=rule_engine,
                receivable_matcher=receivable_matcher,
                payable_matcher=payable_matcher,
                internal_matcher=internal_matcher,
                entity_extractor=entity_extractor,
                verifier=verifier,
                historical_memory=historical_memory,
            )
            processed.append(item)

    assign_transaction_uids(processed)
    duplicate_count = _mark_duplicate_transactions(processed)
    run_stats["duplicate_count"] = duplicate_count
    logger.info("Số dòng báo nợ: %s", sum(1 for item in processed if item.flow == FLOW_BAO_NO))
    logger.info("Số dòng báo có: %s", sum(1 for item in processed if item.flow == FLOW_BAO_CO))
    logger.info("Số dòng phiếu thu tiền mặt: %s", sum(1 for item in processed if item.flow == FLOW_THU_TIEN_MAT))
    logger.info("Số dòng phiếu chi tiền mặt: %s", sum(1 for item in processed if item.flow == FLOW_CHI_TIEN_MAT))
    logger.info("Số dòng trùng: %s", duplicate_count)
    logger.info("Số dòng OK: %s", sum(1 for item in processed if item.status == "OK"))
    logger.info("Số dòng EXCEPTION: %s", sum(1 for item in processed if item.status != "OK"))
    logger.info("Kết thúc chạy")
    return processed


def process_transaction(
    transaction: Transaction,
    config: dict[str, Any],
    rule_engine: RuleEngine,
    receivable_matcher: ObjectMatcher,
    payable_matcher: ObjectMatcher,
    internal_matcher: ObjectMatcher | None = None,
    entity_extractor: EntityExtractor | None = None,
    verifier: AccountingVerifier | None = None,
    historical_memory: HistoricalMemoryMatcher | None = None,
) -> ProcessedTransaction:
    errors: list[str] = []
    bank_direction, default_flow, amount, direction_errors = _detect_money_direction(transaction)
    errors.extend(direction_errors)
    flow = default_flow or MONEY_UNKNOWN

    if transaction.transaction_date is None:
        errors.append("Không parse được ngày chứng từ")

    bank_account = config.get("bank_accounts", {}).get(transaction.bank, "")
    if not bank_account:
        errors.append("Không tìm thấy tài khoản ngân hàng cấu hình")

    if entity_extractor is None:
        entity_extractor = EntityExtractor(OwnCompanyConfig([], [], []))
    if internal_matcher is None:
        internal_matcher = ObjectMatcher([])
    entities = entity_extractor.extract(transaction.bank, transaction.description, transaction.counterparty_raw)
    foreign_exchange = extract_foreign_exchange(transaction.description)
    transaction_matching_cfg = config.get("matching", {})

    rule_match = None
    if default_flow in {FLOW_BAO_NO, FLOW_BAO_CO}:
        search_text = f"{transaction.counterparty_raw} {transaction.description}".strip()
        rule_match = _match_rule_for_direction(rule_engine, bank_direction, transaction.bank, search_text, amount)
        if rule_match:
            flow = rule_match.rule.flow
        else:
            errors.append("Không nhận diện được use case")
    else:
        errors.append("Không xác định được chiều tiền vào/tiền ra")

    use_case = ""
    debit_account = ""
    credit_account = ""
    object_code = ""
    object_name = ""
    match_result = ObjectMatchResult()
    confidence = 0.0
    matched_rule = ""
    active_rule: Rule | None = None

    if rule_match:
        active_rule = rule_match.rule
        matched_rule = active_rule.rule_id or active_rule.use_case
        use_case = active_rule.use_case
        confidence = rule_match.confidence
    if active_rule:
        debit_account, credit_account = _accounts_for_flow(flow, active_rule, bank_account, transaction.bank, config)

        if not active_rule.auto_process:
            errors.append(active_rule.error_note or "Rule không xử lý tự động")

        default_object_code = _default_object_code_for_rule(active_rule, transaction.bank, config)
        if active_rule.account_from_foreign_currency_bank and not _effective_rule_account(active_rule, transaction.bank, config):
            errors.append(f"Không tìm thấy tài khoản ngoại tệ cấu hình cho ngân hàng {transaction.bank}")
        if active_rule.default_object_from_bank and not default_object_code:
            errors.append(f"Không tìm thấy mã đối tượng ngân hàng cấu hình cho {transaction.bank}")

        if default_object_code:
            object_code = default_object_code
        elif active_rule.requires_object:
            match_result = _match_rule_object(
                active_rule,
                payable_matcher,
                receivable_matcher,
                internal_matcher,
                transaction.counterparty_raw,
                transaction.description,
                counterparty_hint=entities.counterparty_hint,
                cleaned_description=entities.cleaned_description,
                cross_catalog_enabled=bool(transaction_matching_cfg.get("cross_catalog_fallback", True)),
                cross_catalog_min_score=float(transaction_matching_cfg.get("cross_catalog_min_score", 97)),
                cross_catalog_min_gap=float(transaction_matching_cfg.get("cross_catalog_min_gap", 10)),
            )
            if match_result.status == "AMBIGUOUS":
                match_result = _disambiguate_ambiguous_object(active_rule, match_result, transaction.description, entities)
            if match_result.status != "OK":
                fallback_rule, fallback_result = _company_advance_fallback(
                    active_rule,
                    payable_matcher,
                    receivable_matcher,
                    transaction,
                    entities,
                )
                if fallback_rule:
                    active_rule = fallback_rule
                    matched_rule = fallback_rule.rule_id or fallback_rule.use_case
                    use_case = fallback_rule.use_case
                    debit_account, credit_account = _accounts_for_flow(flow, active_rule, bank_account, transaction.bank, config)
                    match_result = fallback_result
            if match_result.status == "OK":
                object_code = match_result.code
                object_name = match_result.name
                if active_rule.forced_object_code:
                    object_code = active_rule.forced_object_code
                confidence = min(confidence or 1.0, match_result.score / 100)
            elif _can_use_forced_object_code_without_match(active_rule):
                object_code = active_rule.forced_object_code
                object_name = ""
                match_result = ObjectMatchResult(
                    code=object_code,
                    name=object_name,
                    status="OK",
                    score=100.0,
                    source="forced_object_code",
                    candidates=match_result.candidates,
                )
                confidence = confidence or 1.0
            else:
                object_code = "ERROR"
                errors.append(match_result.error_note or "Không tìm thấy mã đối tượng")

    reason = _reason_for_transaction(
        active_rule,
        flow,
        debit_account,
        credit_account,
        object_code,
        object_name,
        transaction.description,
        _reason_purposes_for_config(config),
        _object_purpose_defaults_for_config(config),
        entities,
        _object_name_purposes_for_config(config),
    )
    # A configured reason template is an explicit accounting decision. Keep it
    # verbatim; only enrich generated FX reasons with amount/currency/rate data.
    if _is_foreign_exchange_account(flow, debit_account, credit_account) and not (
        active_rule and active_rule.reason_template
    ):
        reason = format_foreign_exchange_reason(reason, foreign_exchange)
    if (
        not _rule_has_object_free_reason(active_rule)
        and reason_requires_object_code(flow, debit_account, credit_account)
        and not has_usable_object_code(object_code)
    ):
        errors.append("Thiếu mã đối tượng để sinh Lí do RPA")
    item = ProcessedTransaction(
        source_file=transaction.source_file,
        original_row_index=transaction.original_row_index,
        bank=transaction.bank,
        flow=flow,
        transaction_date=transaction.transaction_date,
        object_code=object_code,
        object_name=object_name,
        reason=reason,
        debit_account=debit_account,
        credit_account=credit_account,
        amount=amount,
        use_case=use_case,
        original_content=transaction.description,
        counterparty_raw=transaction.counterparty_raw,
        doc_no=transaction.doc_no,
        status="OK",
        error_note="",
        confidence=round(confidence, 4),
        matched_candidates=match_result.candidates,
        normalized_content=normalize_text(transaction.description),
        normalized_counterparty=normalize_text(transaction.counterparty_raw),
        matched_rule=matched_rule,
        raw_data=transaction.raw_data,
        entities=entities,
        object_match_source=match_result.source,
        source_sheet=transaction.source_sheet,
        bank_direction=bank_direction,
        foreign_currency=foreign_exchange.currency,
        foreign_amount=foreign_exchange.foreign_amount,
        exchange_rate=foreign_exchange.exchange_rate,
    )

    if verifier:
        verification = verifier.verify(item, active_rule)
        item.verification_result = verification
        if verification.status != "OK":
            errors.append(verification.error_note)

    if errors and historical_memory and default_flow in {FLOW_BAO_NO, FLOW_BAO_CO}:
        historical_match = historical_memory.match(
            transaction,
            default_flow,
            amount,
            counterparty_hint=entities.counterparty_hint,
        )
        if historical_match:
            _apply_historical_match(item, historical_match, bank_account)
            errors = []
            if verifier:
                verification = verifier.verify(item, None)
                item.verification_result = verification
                if verification.status != "OK":
                    errors.append(verification.error_note)

    status = "OK" if not errors else "ERROR"
    if status == "OK" and not _has_required_rpa_fields(
        transaction,
        item.object_code,
        item.reason,
        item.debit_account,
        item.credit_account,
        item.amount,
    ):
        status = "ERROR"
        errors.append("Thiếu trường bắt buộc để ghi RPA input")

    item.status = status
    item.error_note = "; ".join(dict.fromkeys(error for error in errors if error))
    item.transaction_uid = build_transaction_uid(item)
    return item


def _reason_for_transaction(
    rule: Rule | None,
    flow: str,
    debit_account: str,
    credit_account: str,
    object_code: str,
    object_name: str = "",
    description: str = "",
    purposes: list[ReasonPurpose] | tuple[ReasonPurpose, ...] | None = None,
    object_purpose_defaults: dict[str, str] | None = None,
    entities: ExtractedEntities | None = None,
    object_name_purposes: list[tuple[str, str]] | None = None,
) -> str:
    if rule and rule.reason_template:
        return _format_reason_template(rule.reason_template, object_code, object_name, entities)
    return generate_reason(
        flow,
        debit_account,
        credit_account,
        object_code,
        object_name=object_name,
        description=description,
        purposes=purposes,
        object_purpose_defaults=object_purpose_defaults,
        entities=entities,
        object_name_purposes=object_name_purposes,
    )


def _format_reason_template(
    template: str,
    object_code: str,
    object_name: str,
    entities: ExtractedEntities | None = None,
) -> str:
    cleaned_object_code = clean_reason_value(object_code)
    cleaned_object_name = clean_reason_value(object_name)
    values = {
        "object_code": cleaned_object_code,
        "object_name": cleaned_object_name,
        "declaration_no": clean_reason_value(entities.declaration_no if entities else ""),
        "loan_account": clean_reason_value(entities.loan_account if entities else ""),
        "vessel": clean_reason_value(entities.vessel if entities else ""),
        "invoice_no": clean_reason_value(entities.invoice_no if entities else ""),
    }
    if "{object_code}" in template and not has_usable_object_code(cleaned_object_code):
        return ""
    if "{object_name}" in template and not cleaned_object_name:
        return ""

    reason = template
    for key, value in values.items():
        reason = reason.replace("{" + key + "}", value)
    reason = re.sub(r"\s+", " ", reason).strip()
    reason = re.sub(r"\s+([,.;:])", r"\1", reason)
    reason = re.sub(r"\s*:\s*$", "", reason)
    reason = re.sub(r"\(\s*\)", "", reason)
    return reason.strip()


def _rule_has_object_free_reason(rule: Rule | None) -> bool:
    return bool(rule and rule.reason_template and "{object_code}" not in rule.reason_template)


def _is_foreign_exchange_account(flow: str, debit_account: str, credit_account: str) -> bool:
    if flow == FLOW_BAO_NO:
        return _is_foreign_currency_account(debit_account)
    if flow == FLOW_BAO_CO:
        return _is_foreign_currency_account(credit_account)
    return False


def _is_foreign_currency_account(account: str) -> bool:
    return str(account or "").strip().upper().startswith("1122")


def _detect_money_direction(transaction: Transaction) -> tuple[str, str, float, list[str]]:
    errors: list[str] = []
    debit_amount = float(transaction.debit_amount or 0)
    credit_amount = float(transaction.credit_amount or 0)
    if debit_amount > 0 and credit_amount > 0:
        return MONEY_UNKNOWN, "", max(debit_amount, credit_amount), ["Dòng có cả ghi nợ và ghi có"]
    if debit_amount > 0:
        return MONEY_OUT, FLOW_BAO_NO, debit_amount, errors
    if credit_amount > 0:
        return MONEY_IN, FLOW_BAO_CO, credit_amount, errors
    return MONEY_UNKNOWN, "", 0.0, ["Dòng không có số tiền hợp lệ"]


def _match_rule_for_direction(
    rule_engine: RuleEngine,
    direction: str,
    bank: str,
    search_text: str,
    amount: float,
) -> Any | None:
    for flow in _candidate_flows_for_direction(direction):
        match = rule_engine.match(flow, bank, search_text, amount=amount)
        if match:
            return match
    return None


def _candidate_flows_for_direction(direction: str) -> list[str]:
    if direction == MONEY_OUT:
        # Cash withdrawal creates a cash receipt voucher, not a bank debit voucher.
        return [FLOW_THU_TIEN_MAT, FLOW_BAO_NO]
    if direction == MONEY_IN:
        # Cash deposit into bank creates a cash payment voucher, not a bank credit voucher.
        return [FLOW_CHI_TIEN_MAT, FLOW_BAO_CO]
    return []


def _accounts_for_flow(
    flow: str,
    rule: Rule,
    bank_account: str,
    bank: str = "",
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    rule_account = _effective_rule_account(rule, bank, config or {})
    if flow == FLOW_BAO_NO:
        return rule_account, bank_account
    if flow == FLOW_BAO_CO:
        return bank_account, rule_account
    if flow == FLOW_THU_TIEN_MAT:
        return CASH_ACCOUNT, bank_account
    if flow == FLOW_CHI_TIEN_MAT:
        return bank_account, CASH_ACCOUNT
    return "", ""


def _effective_rule_account(rule: Rule, bank: str, config: dict[str, Any]) -> str:
    if not rule.account_from_foreign_currency_bank:
        return rule.account
    return str((config.get("foreign_currency_accounts") or {}).get(bank, "") or "").strip()


def _default_object_code_for_rule(rule: Rule, bank: str, config: dict[str, Any]) -> str:
    if rule.default_object_code:
        return rule.default_object_code
    if rule.default_object_from_bank:
        return str((config.get("bank_object_codes") or {}).get(bank, "") or "").strip()
    return ""


def _load_historical_memory(config: dict[str, Any], project_root: Path, logger: logging.Logger) -> HistoricalMemoryMatcher:
    memory_cfg = config.get("historical_memory", {}) or {}
    if not bool(memory_cfg.get("enabled", False)):
        return HistoricalMemoryMatcher([])
    path = _resolve_config_path(memory_cfg.get("file", "input/thong_ke.xlsx"), project_root)
    matcher = HistoricalMemoryMatcher.from_excel(
        path,
        min_unique_similarity=float(memory_cfg.get("min_unique_similarity", 35)),
        min_ambiguous_similarity=float(memory_cfg.get("min_ambiguous_similarity", 70)),
        min_ambiguous_gap=float(memory_cfg.get("min_ambiguous_gap", 8)),
    )
    logger.info("Load historical memory từ %s: %s dòng", path, len(matcher.records))
    return matcher


def _mark_duplicate_transactions(items: list[ProcessedTransaction]) -> int:
    fingerprints = [transaction_fingerprint(item) for item in items]
    counts = Counter(fingerprints)
    first_uid_by_fingerprint: dict[str, str] = {}
    duplicate_count = 0
    for item, fingerprint in zip(items, fingerprints):
        if counts[fingerprint] <= 1:
            continue
        first_uid = first_uid_by_fingerprint.get(fingerprint)
        if not first_uid:
            first_uid_by_fingerprint[fingerprint] = item.transaction_uid
            continue
        duplicate_count += 1
        item.is_duplicate = True
        item.duplicate_of = first_uid
        item.status = "ERROR"
        duplicate_note = f"Giao dịch trùng với {first_uid}"
        item.error_note = "; ".join(error for error in [item.error_note, duplicate_note] if error)
    return duplicate_count


def _load_matcher(
    path: str | Path,
    min_score: float,
    min_gap: float,
    ambiguous_min_score: float,
    label: str,
    logger: logging.Logger,
    aliases: dict[str, list[str]] | None = None,
    exact_phrase_overrides: dict[str, str] | None = None,
    supplemental_objects: list[Any] | None = None,
    own_company: OwnCompanyConfig | None = None,
) -> ObjectMatcher:
    try:
        matcher = ObjectMatcher.from_excel(
            path,
            min_score=min_score,
            min_gap=min_gap,
            ambiguous_min_score=ambiguous_min_score,
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            supplemental_objects=supplemental_objects or [],
            own_company=own_company,
        )
        logger.info("Load danh mục %s: %s dòng", label, len(matcher.objects))
        return matcher
    except Exception as exc:  # noqa: BLE001
        logger.error("Không load được danh mục %s từ %s: %s", label, path, exc)
        return ObjectMatcher(
            list(supplemental_objects or []),
            min_score=min_score,
            min_gap=min_gap,
            ambiguous_min_score=ambiguous_min_score,
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            own_company=own_company or OwnCompanyConfig([], [], []),
        )


def _load_internal_matcher(
    path: str | Path,
    min_score: float,
    min_gap: float,
    ambiguous_min_score: float,
    logger: logging.Logger,
    aliases: dict[str, list[str]] | None = None,
    exact_phrase_overrides: dict[str, str] | None = None,
    supplemental_objects: list[Any] | None = None,
    own_company: OwnCompanyConfig | None = None,
) -> ObjectMatcher:
    try:
        objects = [obj for obj in load_catalog(path) if _looks_like_internal_person(obj)]
        objects.extend(supplemental_objects or [])
        logger.info("Load danh mục nội bộ: %s cá nhân từ %s", len(objects), path)
        return ObjectMatcher(
            objects,
            min_score=min_score,
            min_gap=min_gap,
            ambiguous_min_score=ambiguous_min_score,
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            own_company=own_company or OwnCompanyConfig([], [], []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Không load được danh mục nội bộ từ %s: %s", path, exc)
        return ObjectMatcher(
            list(supplemental_objects or []),
            aliases=aliases or {},
            exact_phrase_overrides=exact_phrase_overrides or {},
            own_company=own_company or OwnCompanyConfig([], [], []),
        )


def _looks_like_internal_person(obj: CatalogObject) -> bool:
    tokens = normalize_text(obj.name).split()
    if not 2 <= len(tokens) <= 6:
        return False
    return tokens[0] in {
        "BUI",
        "CAO",
        "CHAU",
        "CHU",
        "DAO",
        "DANG",
        "DINH",
        "DO",
        "DUONG",
        "HA",
        "HO",
        "HOANG",
        "HUYNH",
        "KIEU",
        "LA",
        "LAM",
        "LE",
        "LUONG",
        "LY",
        "MAC",
        "MAI",
        "NGO",
        "NGUYEN",
        "PHAM",
        "PHAN",
        "QUACH",
        "TA",
        "THAI",
        "TO",
        "TON",
        "TRAN",
        "TRINH",
        "TRUONG",
        "VU",
        "VO",
    }


def _merge_aliases(*sections: dict[str, list[str]] | None) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for section in sections:
        for code, aliases in (section or {}).items():
            merged.setdefault(code, []).extend(aliases or [])
    return {code: list(dict.fromkeys(values)) for code, values in merged.items()}


def _reason_purposes_for_config(config: dict[str, Any]) -> list[ReasonPurpose]:
    if "_reason_purposes" in config:
        return list(config.get("_reason_purposes") or [])

    project_root = Path(__file__).resolve().parents[1]
    reason_aliases_path = _resolve_config_path(config.get("reason_aliases_file", "config/reason_aliases.yaml"), project_root)
    purposes = load_reason_purposes(reason_aliases_path)
    config["_reason_purposes"] = purposes
    return purposes


def _object_purpose_defaults_for_config(config: dict[str, Any]) -> dict[str, str]:
    if "_object_purpose_defaults" in config:
        return dict(config.get("_object_purpose_defaults") or {})

    project_root = Path(__file__).resolve().parents[1]
    reason_aliases_path = _resolve_config_path(config.get("reason_aliases_file", "config/reason_aliases.yaml"), project_root)
    defaults = load_object_purpose_defaults(reason_aliases_path)
    config["_object_purpose_defaults"] = defaults
    return defaults


def _object_name_purposes_for_config(config: dict[str, Any]) -> list[tuple[str, str]]:
    if "_object_name_purposes" in config:
        return list(config.get("_object_name_purposes") or [])

    project_root = Path(__file__).resolve().parents[1]
    reason_aliases_path = _resolve_config_path(config.get("reason_aliases_file", "config/reason_aliases.yaml"), project_root)
    rules = load_object_name_purposes(reason_aliases_path)
    config["_object_name_purposes"] = rules
    return rules


def _has_required_rpa_fields(
    transaction: Transaction,
    object_code: str,
    reason: str,
    debit_account: str,
    credit_account: str,
    amount: float,
) -> bool:
    return bool(transaction.transaction_date and reason and debit_account and credit_account and amount > 0 and object_code != "ERROR")


def _apply_historical_match(item: ProcessedTransaction, historical_match: HistoricalMemoryMatch, bank_account: str) -> None:
    item.flow = historical_match.flow
    if historical_match.flow == FLOW_BAO_NO:
        item.debit_account = historical_match.account
        item.credit_account = bank_account
    elif historical_match.flow == FLOW_BAO_CO:
        item.debit_account = bank_account
        item.credit_account = historical_match.account
    item.object_code = historical_match.code
    item.object_name = historical_match.name
    item.reason = historical_match.reason
    item.use_case = item.use_case or historical_match.reason
    item.confidence = round(max(item.confidence, 0.95, min(historical_match.score / 100, 0.99)), 4)
    item.matched_rule = "historical_memory"
    item.object_match_source = historical_match.source
    item.matched_candidates = [
        ObjectCandidate(
            code=historical_match.code,
            name=historical_match.name,
            score=historical_match.score,
            source=historical_match.source,
            matched_on=f"{historical_match.source_file}:{historical_match.source_row}",
        )
    ]


def _match_rule_object(
    rule: Rule,
    payable_matcher: ObjectMatcher,
    receivable_matcher: ObjectMatcher,
    internal_matcher: ObjectMatcher,
    counterparty_raw: str,
    description: str,
    counterparty_hint: str,
    cleaned_description: str,
    cross_catalog_enabled: bool = True,
    cross_catalog_min_score: float = 97.0,
    cross_catalog_min_gap: float = 10.0,
) -> ObjectMatchResult:
    matcher = _matcher_for_catalog(rule.object_catalog, payable_matcher, receivable_matcher, internal_matcher)
    result = matcher.match(
        counterparty_raw,
        description,
        counterparty_hint=counterparty_hint,
        cleaned_description=cleaned_description,
    )
    if result.status != "NOT_FOUND" or not cross_catalog_enabled:
        return result
    fallback = _cross_catalog_fallback_match(
        rule.object_catalog,
        payable_matcher,
        receivable_matcher,
        counterparty_raw,
        description,
        counterparty_hint,
        cleaned_description,
        cross_catalog_min_score,
        cross_catalog_min_gap,
    )
    return fallback or result


def _matcher_for_catalog(
    catalog: str,
    payable_matcher: ObjectMatcher,
    receivable_matcher: ObjectMatcher,
    internal_matcher: ObjectMatcher,
) -> ObjectMatcher:
    if catalog == "payable":
        return payable_matcher
    if catalog == "receivable":
        return receivable_matcher
    if catalog == INTERNAL_OBJECT_CATALOG:
        return internal_matcher
    return ObjectMatcher([])


def _company_advance_fallback(
    active_rule: Rule,
    payable_matcher: ObjectMatcher,
    receivable_matcher: ObjectMatcher,
    transaction: Transaction,
    entities: Any,
) -> tuple[Rule | None, ObjectMatchResult]:
    if not _is_internal_advance_rule(active_rule):
        return None, ObjectMatchResult()
    if active_rule.flow == FLOW_BAO_CO:
        receivable_result = receivable_matcher.match(
            transaction.counterparty_raw,
            transaction.description,
            counterparty_hint=entities.counterparty_hint,
            cleaned_description=entities.cleaned_description,
        )
        if receivable_result.status != "OK" and not _has_company_signal(f"{transaction.counterparty_raw} {transaction.description}"):
            return None, receivable_result
        return (
            Rule(
                flow=FLOW_BAO_CO,
                use_case="Nhận tạm ứng công ty/khách",
                account="131",
                bank_scope=active_rule.bank_scope,
                include_keywords=[],
                context_keywords=[],
                exclude_keywords=[],
                auto_process=True,
                priority=active_rule.priority,
                requires_object=True,
                object_catalog="receivable",
                rule_id="advance_company_receivable",
                direction=active_rule.direction,
                reason_template="Nhận tiền tạm ứng ({object_name})",
            ),
            receivable_result,
        )

    payable_result = payable_matcher.match(
        transaction.counterparty_raw,
        transaction.description,
        counterparty_hint=entities.counterparty_hint,
        cleaned_description=entities.cleaned_description,
    )
    if payable_result.status != "OK" and not _has_company_signal(f"{transaction.counterparty_raw} {transaction.description}"):
        return None, payable_result
    return (
        Rule(
            flow=FLOW_BAO_NO,
            use_case="Tạm ứng công ty/nhà cung cấp",
            account="331",
            bank_scope=active_rule.bank_scope,
            include_keywords=[],
            context_keywords=[],
            exclude_keywords=[],
            auto_process=True,
            priority=active_rule.priority,
            requires_object=True,
            object_catalog="payable",
            rule_id="advance_company_payable",
            direction=active_rule.direction,
            reason_template="Tạm ứng tiền hàng ({object_name})",
        ),
        payable_result,
    )


def _is_internal_advance_rule(rule: Rule) -> bool:
    return rule.flow in {FLOW_BAO_NO, FLOW_BAO_CO} and rule.account == "141" and rule.object_catalog == INTERNAL_OBJECT_CATALOG


def _cross_catalog_fallback_match(
    primary_catalog: str,
    payable_matcher: ObjectMatcher,
    receivable_matcher: ObjectMatcher,
    counterparty_raw: str,
    description: str,
    counterparty_hint: str,
    cleaned_description: str,
    min_score: float,
    min_gap: float,
) -> ObjectMatchResult | None:
    fallback_catalog = ""
    fallback_matcher: ObjectMatcher | None = None
    if primary_catalog == "payable":
        fallback_catalog = "receivable"
        fallback_matcher = receivable_matcher
    elif primary_catalog == "receivable":
        fallback_catalog = "payable"
        fallback_matcher = payable_matcher
    if not fallback_matcher:
        return None

    result = fallback_matcher.match(
        counterparty_raw,
        description,
        counterparty_hint=counterparty_hint,
        cleaned_description=cleaned_description,
    )
    if not _is_acceptable_cross_catalog_result(result, min_score, min_gap):
        return None
    return ObjectMatchResult(
        code=result.code,
        name=result.name,
        status="OK",
        score=result.score,
        source=f"cross_catalog_{fallback_catalog}_{result.source}",
        candidates=result.candidates,
    )


def _is_acceptable_cross_catalog_result(result: ObjectMatchResult, min_score: float, min_gap: float) -> bool:
    if result.status != "OK":
        return False
    if result.source in {"exact_phrase", "alias_match", "tax_code", "catalog_phrase"}:
        return True
    if result.score < min_score:
        return False
    second_score = result.candidates[1].score if len(result.candidates) > 1 else 0.0
    return result.score - second_score >= min_gap


def _disambiguate_ambiguous_object(
    rule: Rule,
    match_result: ObjectMatchResult,
    description: str,
    entities: Any,
) -> ObjectMatchResult:
    if match_result.status != "AMBIGUOUS" or not match_result.candidates:
        return match_result
    context = normalize_text(f"{description} {getattr(entities, 'service_hint', '')}")
    scored = [
        (_object_context_score(candidate, context, rule.flow), candidate)
        for candidate in match_result.candidates[:5]
    ]
    scored = [(score, candidate) for score, candidate in scored if score > 0]
    if not scored:
        return match_result
    scored.sort(key=lambda item: (item[0], item[1].score), reverse=True)
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    if best_score <= second_score:
        return match_result
    return ObjectMatchResult(
        code=best.code,
        name=best.name,
        status="OK",
        score=best.score,
        source=f"context_disambiguation_{best.source}",
        candidates=match_result.candidates,
    )


def _object_context_score(candidate: Any, context: str, flow: str) -> int:
    candidate_text = normalize_text(f"{candidate.name} {candidate.group_name} {candidate.group_code}")
    score = 0
    for context_keywords, object_keywords in _OBJECT_CONTEXT_DISAMBIGUATION_RULES:
        if not any(keyword in context for keyword in context_keywords):
            continue
        if any(keyword in candidate_text for keyword in object_keywords):
            score += 1
    if flow == FLOW_BAO_CO and "THUE VAN PHONG" in context and "VAN PHONG" in candidate_text:
        score += 1
    return score


_OBJECT_CONTEXT_DISAMBIGUATION_RULES = [
    (("PHI CANG VU", "TIEN CANG VU", "CANG VU"), ("CANG VU HANG HAI", "CANG VU")),
    (("PHI HOA TIEU", "HOA TIEU"), ("HOA TIEU",)),
    (("PHI KIEM DICH", "KIEM DICH"), ("KIEM DICH", "KIEM SOAT BENH TAT")),
    (("PHI KHACH SAN", "TIEN PHONG", "KHACH SAN"), ("KHACH SAN", "DU LICH", "HOTEL")),
    (("THUE VAN PHONG", "THUE VP"), ("VAN PHONG", "CHO THUE")),
    (("CUOC VAN CHUYEN", "TIEN VAN CHUYEN", "CUOC VC"), ("VAN TAI", "LOGISTICS", "GIAO NHAN")),
]


def _has_company_signal(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    patterns = [
        r"\bCONG TY\b",
        r"\bCTY\b",
        r"\bC TY\b",
        r"\bCT\s+(?:TNHH|CP)\b",
        r"\bTNHH\b",
        r"\bCO PHAN\b",
        r"\bCHI NHANH\b",
        r"\bCO SO\b",
        r"\bCOMPANY\b",
        r"\bCORPORATION\b",
        r"\bJSC\b",
        r"\bLTD\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _can_use_forced_object_code_without_match(rule: Rule) -> bool:
    return bool(rule.forced_object_code and rule.amount_equals is not None)


def _resolve_config_path(value: str | Path, project_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path
