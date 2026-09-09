from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from ..models import Transaction
from ..normalizer import normalize_text
from ..transaction_identity import transaction_fingerprint


def assign_source_transaction_uids(transactions: list[Transaction]) -> list[str]:
    fingerprints = [transaction_fingerprint(item) for item in transactions]
    counts = Counter(fingerprints)
    seen: dict[str, int] = defaultdict(int)
    uids: list[str] = []
    for transaction, fingerprint in zip(transactions, fingerprints):
        identity = fingerprint
        if counts[fingerprint] > 1:
            seen[fingerprint] += 1
            suffix = "|".join(
                [
                    normalize_text(transaction.source_file),
                    normalize_text(transaction.source_sheet),
                    str(transaction.original_row_index),
                    str(seen[fingerprint]),
                ]
            )
            identity = f"{fingerprint}|{suffix}"
        uids.append(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32])
    return uids


def entry_uid(source_transaction_uid: str, entry_kind: str = "") -> str:
    return f"{source_transaction_uid}:{entry_kind}" if entry_kind else source_transaction_uid
