"""python -m bookings backfill 2026-06-01 2026-10-17     load a range of days, then report
   python -m bookings day 2026-10-18                      run one day through every step
   python -m bookings ga4                                 build GA4 shaped events, show the reconciliation
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
    sub.add_parser("ga4")
    a = ap.parse_args()
    root = Path(a.root)
    db = root / "warehouse.duckdb"
    if a.cmd == "ga4":
        from . import ga4
        print(f"{ga4.build_ga4(db):,} events built")
        print(ga4.run_query(db, "funnel_by_medium").to_string(index=False))
        rec = ga4.run_query(db, "purchases_vs_bookings")
        print(f"\nGA4 saw {rec.ga4_transactions.sum():,} of {rec.bookings.sum():,} bookings; "
              f"{rec.double_fired.sum():,} purchases were sent twice")
        print(ga4.export_parquet(db, root / "marts"))
        return
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
