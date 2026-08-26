from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import CATALOG_DEFINITIONS


@dataclass(frozen=True)
class RuleManagerPaths:
    project_root: Path
    input_dir: Path
    config_dir: Path
    data_dir: Path
    backup_dir: Path
    user_rules_path: Path
    object_aliases_path: Path
    object_overrides_path: Path
    own_company_path: Path

    @classmethod
    def from_project_root(cls, project_root: str | Path) -> "RuleManagerPaths":
        root = Path(project_root).resolve()
        return cls(
            project_root=root,
            input_dir=root / "input",
            config_dir=root / "config",
            data_dir=root / "data" / "rule_manager",
            backup_dir=root / "backup" / "rule_manager",
            user_rules_path=root / "data" / "rule_manager" / "object_rules.user.json",
            object_aliases_path=root / "config" / "object_aliases.yaml",
            object_overrides_path=root / "config" / "object_overrides.yaml",
            own_company_path=root / "config" / "own_company.yaml",
        )

    def catalog_path(self, catalog: str) -> Path:
        definition = CATALOG_DEFINITIONS[catalog]
        return self.input_dir / definition.filename

