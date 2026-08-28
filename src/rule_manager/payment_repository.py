from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .json_store import AtomicJsonStore
from .payment_models import ManagedPaymentPurpose


class PaymentRuleRepository:
    def __init__(self, path):
        self.store = AtomicJsonStore(path, "purposes")

    @property
    def path(self):
        return self.store.path

    def records(self) -> list[ManagedPaymentPurpose]:
        return [
            ManagedPaymentPurpose.from_dict(item)
            for item in self.store.load()["purposes"]
            if isinstance(item, dict)
        ]

    def upsert(self, record: ManagedPaymentPurpose) -> None:
        data = self.store.load()
        records = self.records()
        now = datetime.now().isoformat(timespec="seconds")
        updated: list[ManagedPaymentPurpose] = []
        found = False
        for current in records:
            if current.record_id != record.record_id:
                updated.append(current)
                continue
            found = True
            updated.append(replace(record, created_at=current.created_at or now, updated_at=now))
        if not found:
            updated.append(replace(record, created_at=record.created_at or now, updated_at=now))
        data["purposes"] = [item.to_dict() for item in updated]
        self.store.save(data)
