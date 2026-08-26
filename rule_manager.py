from __future__ import annotations

from pathlib import Path

from src.rule_manager.ui import run_rule_manager


if __name__ == "__main__":
    run_rule_manager(Path(__file__).resolve().parent)
