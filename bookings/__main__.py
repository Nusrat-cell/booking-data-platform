"""python -m bookings backfill 2026-06-01 2026-10-17     load a range of days, then report
   python -m bookings day 2026-10-18                      run one day through every step
"""
import argparse
import datetime as dt
from pathlib import Path

from . import pipeline


def main() -> None:
    ap = argparse.ArgumentParser(prog="bookings")
    ap.add_argument("--root", default="data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("start")
    b.add_argument("end")
    d = sub.add_parser("day")
    d.add_argument("date")
    a = ap.parse_args()
    root = Path(a.root)
    db = root / "warehouse.duckdb"
    if a.cmd == "day":
        print(pipeline.run_day(dt.date.fromisoformat(a.date), root, db))
        return
    day, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    while day <= end:
        pipeline.extract(day, root)
        pipeline.load_raw(day, root, db)
        day += dt.timedelta(days=1)
    pipeline.build_models(db)
    for r in pipeline.quality_gate(db, fail_on_blocking=False):
        print(f"{r['status']:>5}  {r['check_id']:<32} {r['failed_rows']}")
    print(pipeline.finance_report(db, root / "reports"))
    print(pipeline.export_marts(db, root / "marts"))


main()
