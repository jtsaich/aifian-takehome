"""Regenerate every mock file: `uv run generate-mock-data [--today YYYY-MM-DD] [--seed N] [--out DIR]`."""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from bakery.clock import today_taipei
from bakery.mockdata import DEFAULT_OUT_DIR, DEFAULT_SEED, generate_mock_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生範本、模擬上傳檔、舊格式檔與對照表")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT_DIR), help=f"輸出資料夾（預設 {DEFAULT_OUT_DIR}）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"亂數種子（預設 {DEFAULT_SEED}）")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="第一天的日期 YYYY-MM-DD（預設台北時間今天）",
    )
    args = parser.parse_args(argv)
    today = args.today or today_taipei()
    # Clear what a previous run generated so renamed files never linger.
    for sub in ("templates", "day1", "day2", "legacy"):
        shutil.rmtree(args.out / sub, ignore_errors=True)
    manifest = generate_mock_data(args.out, seed=args.seed, today=today)
    count = len(manifest.templates) + len(manifest.files) + len(manifest.legacy)
    print(f"已產生 {count} 個 .xlsx 到 {args.out}/（seed={manifest.seed}，第一天={manifest.today}）")
    print(f"對照表：{args.out}/對照表.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
