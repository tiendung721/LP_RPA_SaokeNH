from __future__ import annotations

import argparse
from pathlib import Path

from src.config_loader import load_config
from src.logger_setup import setup_logger
from src.output_writer import write_outputs
from src.processor import process_all


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline bank statement RPA input generator")
    parser.add_argument("--input-dir", default="input", help="Thư mục input tổng")
    parser.add_argument("--statements", help="Thư mục chứa sao kê ngân hàng")
    parser.add_argument("--receivable", help="File danh mục đối tượng phải thu")
    parser.add_argument("--payable", help="File danh mục đối tượng phải trả")
    parser.add_argument("--output-dir", default="output", help="Thư mục output")
    parser.add_argument("--config", default="config/config.yaml", help="File config YAML")
    return parser.parse_args()  


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent

    config_path = _resolve_path(args.config, project_root)
    config = load_config(config_path)
    output_dir = _resolve_path(args.output_dir, project_root)
    logger = setup_logger()

    input_dir = _resolve_path(args.input_dir, project_root)
    statements_dir = _resolve_path(args.statements, project_root) if args.statements else input_dir / "statements"
    receivable_path = _resolve_path(args.receivable, project_root) if args.receivable else input_dir / "R_DMDT1 1.xlsx"
    payable_path = _resolve_path(args.payable, project_root) if args.payable else input_dir / "R_DMDT1.xlsx"
    default_rules_path = _resolve_path(config.get("rules", {}).get("default_rules_file", "config/default_rules.yaml"), project_root)
    config["_runtime_paths"] = {
        "receivable_path": str(receivable_path),
        "payable_path": str(payable_path),
        "object_aliases_path": str(_resolve_path(config.get("object_aliases_file", "config/object_aliases.yaml"), project_root)),
        "object_overrides_path": str(_resolve_path(config.get("object_overrides_file", "config/object_overrides.yaml"), project_root)),
        "reason_aliases_path": str(_resolve_path(config.get("reason_aliases_file", "config/reason_aliases.yaml"), project_root)),
        "internal_objects_path": str(_resolve_path(config.get("internal_objects_file", "input/MA NOI BO CTY.xlsx"), project_root)),
        "own_company_path": str(_resolve_path(config.get("own_company_file", "config/own_company.yaml"), project_root)),
    }

    processed = process_all(
        statements_dir=statements_dir,
        receivable_path=receivable_path,
        payable_path=payable_path,
        rules_path=None,
        default_rules_path=default_rules_path,
        config=config,
        logger=logger,
    )
    output_result = write_outputs(processed, output_dir, config, logger=logger)
    stats = output_result.stats
    logger.info("Run id: %s", output_result.run_id)
    logger.info("Tong so giao dich parse duoc: %s", stats.get("total_processed", 0))
    logger.info("So dong du dieu kien nhap tu dong: %s", stats.get("auto_process_count", 0))
    logger.info("So dong moi: %s", stats.get("new_count", 0))
    logger.info("So dong chua nhap: %s", stats.get("pending_count", 0))
    logger.info("So dong hoan thanh: %s", stats.get("skipped_completed_count", 0))
    logger.info("So dong bao no xuat ra: %s", stats.get("bao_no_output_count", 0))
    logger.info("So dong bao co xuat ra: %s", stats.get("bao_co_output_count", 0))
    logger.info("So dong phieu thu tien mat xuat ra: %s", stats.get("thu_tien_mat_output_count", 0))
    logger.info("So dong phieu chi tien mat xuat ra: %s", stats.get("chi_tien_mat_output_count", 0))
    logger.info("So dong trong EXCEPTION: %s", stats.get("exception_count", 0))
    logger.info("File review ma doi tuong: %s", output_result.object_match_review_path)
    logger.info("Đã ghi output vào: %s", output_dir)
    return 0


def _resolve_path(value: str | Path | None, project_root: Path) -> Path:
    if value is None:
        return project_root
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = project_root / path
    return candidate if candidate.exists() or not path.exists() else path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
