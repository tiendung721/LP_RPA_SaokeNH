from __future__ import annotations

from dataclasses import asdict, dataclass, field
import uuid
from typing import Any

from .simple_alias import ManagedTextAlias


FLOW_LABELS = {
    "bao_no": "Báo nợ",
    "bao_co": "Báo có",
    "thu_tien_mat": "Thu tiền mặt",
    "chi_tien_mat": "Chi tiền mặt",
}
FLOW_KEYS = tuple(FLOW_LABELS)
CASH_FLOWS = {"thu_tien_mat", "chi_tien_mat"}


@dataclass(frozen=True)
class AccountingRuleView:
    record_id: str
    rule_id: str
    use_case: str
    account: str
    flow: str
    aliases: tuple[ManagedTextAlias, ...] = field(default_factory=tuple)
    active: bool = True
    deleted: bool = False
    source: str = "builtin"
    created_at: str = ""
    updated_at: str = ""

    @property
    def editable(self) -> bool:
        return self.source == "user"

    @property
    def active_aliases(self) -> tuple[str, ...]:
        return tuple(value for alias in self.aliases if (value := alias.active_value))


@dataclass(frozen=True)
class ManagedAccountingRule(AccountingRuleView):
    source: str = "user"

    @classmethod
    def new_user(
        cls,
        use_case: str,
        account: str,
        flow: str,
        aliases: tuple[ManagedTextAlias, ...],
    ) -> "ManagedAccountingRule":
        identifier = f"user_{uuid.uuid4().hex}"
        return cls(
            record_id=f"user:{uuid.uuid4().hex}",
            rule_id=identifier,
            use_case=use_case,
            account=account,
            flow=flow,
            aliases=aliases,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagedAccountingRule":
        rule_id = str(value.get("rule_id", "") or f"user_{uuid.uuid4().hex}")
        return cls(
            record_id=str(value.get("record_id", "") or f"user:{uuid.uuid4().hex}"),
            rule_id=rule_id,
            use_case=str(value.get("use_case", "") or "").strip(),
            account=str(value.get("account", "") or "").strip(),
            flow=str(value.get("flow", "") or "").strip(),
            aliases=tuple(
                ManagedTextAlias.from_dict(item)
                for item in value.get("aliases", []) or []
                if isinstance(item, dict)
            ),
            active=bool(value.get("active", True)),
            deleted=bool(value.get("deleted", False)),
            source=str(value.get("source", "user") or "user").strip(),
            created_at=str(value.get("created_at", "") or ""),
            updated_at=str(value.get("updated_at", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["aliases"] = [alias.to_dict() for alias in self.aliases]
        return value


@dataclass(frozen=True)
class AccountingPublishResult:
    backup_dir: str
    changed_files: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
