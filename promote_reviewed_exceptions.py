from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.exception_promotion import ExceptionPromotionError, promote_reviewed_exceptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote reviewed EXCEPTION rows into RPA input sheets")
    parser.add_argument("--input-file", required=True, help="Path to rpa_input.xlsx")
    parser.add_argument(
        "--fail-on-validation-error",
        action="store_true",
        help="Return exit code 2 when reviewed exception rows are missing required data",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = promote_reviewed_exceptions(Path(args.input_file))
    except (FileNotFoundError, PermissionError, OSError, ExceptionPromotionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(summary.format())
    if args.fail_on_validation_error and summary.failed_validation:
        print(
            f"Validation failed for {summary.failed_validation} reviewed exception rows. "
            "Please fix the EXCEPTION sheet and run again.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
