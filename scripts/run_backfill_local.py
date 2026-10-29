"""Backfill iFood ingest month-by-month (same code path as Lambda).

Run from repo root:
  uv run --directory scripts python run_backfill_local.py
"""
from __future__ import annotations

import calendar
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
LAMBDA_ROOT = ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_ROOT))

from run_ingest_local import ensure_aws_credentials, load_dotenv  # noqa: E402


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def main() -> None:
    load_dotenv()
    ensure_aws_credentials()
    from src.ingest.ifood import main as ingest_main

    year = int(os.getenv("IFOOD_BACKFILL_YEAR", "2026"))
    from_month = int(os.getenv("IFOOD_BACKFILL_FROM_MONTH", "1"))
    to_month = int(os.getenv("IFOOD_BACKFILL_TO_MONTH", "12"))
    incremental = os.getenv("IFOOD_INGEST_INCREMENTAL", "true").lower() in ("1", "true", "yes")
    cap = os.getenv("IFOOD_BACKFILL_THROUGH_YESTERDAY", "true").lower() in ("1", "true", "yes")
    end_cap_raw = os.getenv("IFOOD_BACKFILL_END_DATE")
    end_cap = date.fromisoformat(end_cap_raw) if end_cap_raw else None
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    print(
        f"[BACKFILL] year={year} months={from_month}..{to_month} "
        f"incremental={incremental} cap_yesterday={cap} ({yesterday})"
    )

    for month in range(from_month, to_month + 1):
        start_day, end_day = _month_bounds(year, month)
        if end_cap is not None:
            if start_day > end_cap:
                print(f"[BACKFILL] skip {year}-{month:02d} (after end cap {end_cap})")
                continue
            end_day = min(end_day, end_cap)
        if cap:
            end_day = min(end_day, yesterday)
        if start_day > end_day:
            print(f"[BACKFILL] skip {year}-{month:02d} (future)")
            continue

        start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(end_day, time.max, tzinfo=timezone.utc)
        print(f"\n[BACKFILL] ===== {start_day} .. {end_day} =====")
        ingest_main(start, end, incremental=incremental)

    print("[BACKFILL] all requested months finished")


if __name__ == "__main__":
    main()
