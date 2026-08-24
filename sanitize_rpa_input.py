from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.rpa_input_sanitizer import sanitize_rpa_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove blank/deleted rows from an RPA input workbook")
    parser.add_argument("--input-file", required=True, help="Path to rpa_input.xlsx")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = sanitize_rpa_input(Path(args.input_file))
    except (FileNotFoundError, PermissionError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(summary.format())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
