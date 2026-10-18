"""The steps behind the Airflow DAG, as plain functions so they can be tested without Airflow."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import duckdb

from . import generate

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
RAW = {  # table, file, partitioned by day
    "raw_bookings": "bookings.csv",
    "raw_touchpoints": "touchpoints.csv",
    "raw_ad_spend": "ad_spend.csv",
    "raw_fx": "fx_rates.csv",
}


class QualityGateFailed(Exception):
    pass


def extract(day: dt.date, root: Path) -> dict:
    """Pull one day from the source system (here: the generator) into the landing folder."""
    generate.write_events(root)
    return generate.generate_day(day, root)


def load_raw(day: dt.date, root: Path, db: Path) -> dict:
    """Load one day into raw tables. Re-running a day replaces that day, so it is safe to retry."""
    folder = root / "landing" / day.isoformat()
    con = duckdb.connect(str(db))
    counts = {}
    try:
        for table, file in RAW.items():
            src = folder / file
            if not src.exists():
                counts[table] = 0
                continue
            read = f"SELECT *, DATE '{day}' AS _source_day, now() AS _loaded_at FROM read_csv('{src}', all_varchar=true)"
            if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0]:
                con.execute(f"DELETE FROM {table} WHERE _source_day = DATE '{day}'")
                con.execute(f"INSERT INTO {table} {read}")
            else:
                con.execute(f"CREATE TABLE {table} AS {read}")
            counts[table] = con.execute(f"SELECT count(*) FROM {table} WHERE _source_day = DATE '{day}'").fetchone()[0]
        con.execute(f"CREATE OR REPLACE TABLE raw_events AS SELECT * FROM read_csv('{root / 'landing' / 'events.csv'}', all_varchar=true)")
    finally:
        con.close()
    return counts


def build_models(db: Path) -> list[str]:
    con = duckdb.connect(str(db))
    done = []
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            con.execute(path.read_text())
            done.append(path.stem)
    finally:
        con.close()
    return done


CHECKS = [  # id, description, severity, SQL that returns the number of failing rows
    ("booking_id_unique", "fct_bookings has one row per booking", "blocking",
     "SELECT count(*) FROM (SELECT booking_id FROM fct_bookings GROUP BY 1 HAVING count(*) > 1)"),
    ("every_booking_has_fx", "every booking has an exchange rate", "blocking",
     "SELECT count(*) FROM fct_bookings WHERE eur_per_unit IS NULL"),
    ("revenue_reconciles", "net revenue equals confirmed source amounts times the rate", "blocking",
     """SELECT CASE WHEN abs((SELECT sum(net_revenue_eur) FROM fct_bookings) -
        (SELECT sum(b.gross_amount * fx.eur_per_unit) FROM stg_bookings b
         JOIN dim_fx_daily fx ON fx.day = CAST(b.booked_at AS DATE) AND fx.currency = b.currency
         WHERE b.status = 'confirmed')) > 1 THEN 1 ELSE 0 END"""),
    ("attribution_one_row_each", "each credited booking has exactly one last-touch row", "blocking",
     "SELECT count(*) FROM (SELECT booking_id FROM fct_attribution GROUP BY 1 HAVING count(*) > 1)"),
    ("every_line_loaded_or_rejected", "latest bookings = loaded + rejected", "blocking",
     "SELECT CASE WHEN (SELECT count(*) FROM stg_bookings_latest) = (SELECT count(*) FROM stg_bookings) + (SELECT count(*) FROM stg_bookings_rejected) THEN 0 ELSE 1 END"),
    ("fx_carried", "bookings that use a carried forward rate", "warning",
     "SELECT count(*) FROM fct_bookings WHERE fx_source = 'carried'"),
    ("rejected_share", "more than 2 percent of bookings rejected", "warning",
     "SELECT CASE WHEN (SELECT count(*) FROM stg_bookings_rejected) > 0.02 * (SELECT count(*) FROM stg_bookings_latest) THEN 1 ELSE 0 END"),
    ("unknown_channel", "visits without a channel", "warning",
     "SELECT count(*) FROM stg_touchpoints WHERE channel = 'unknown'"),
]


def quality_gate(db: Path, fail_on_blocking: bool = True) -> list[dict]:
    con = duckdb.connect(str(db))
    results = []
    try:
        con.execute("CREATE OR REPLACE TABLE dq_latest (check_id VARCHAR, description VARCHAR, severity VARCHAR, failed_rows BIGINT, status VARCHAR)")
        for cid, desc, sev, sql in CHECKS:
            failed = con.execute(sql).fetchone()[0]
            status = "pass" if failed == 0 else ("FAIL" if sev == "blocking" else "warn")
            results.append({"check_id": cid, "description": desc, "severity": sev, "failed_rows": failed, "status": status})
            con.execute("INSERT INTO dq_latest VALUES (?, ?, ?, ?, ?)", [cid, desc, sev, failed, status])
    finally:
        con.close()
    bad = [r for r in results if r["status"] == "FAIL"]
    if bad and fail_on_blocking:
        raise QualityGateFailed("; ".join(f"{r['check_id']} ({r['failed_rows']})" for r in bad))
    return results


def finance_report(db: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    try:
        cur = con.execute("SELECT * FROM mart_finance_monthly ORDER BY month")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    path = out_dir / "finance_monthly.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return path


def export_marts(db: Path, out_dir: Path) -> list[str]:
    """Write the marts as Parquet, for BI tools that read files (Metabase, Power BI, Tableau)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    names = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'mart_%' ORDER BY 1").fetchall()]
    try:
        for n in names:
            con.execute(f"COPY {n} TO '{out_dir / (n + '.parquet')}' (FORMAT PARQUET)")
    finally:
        con.close()
    return names


def run_day(day: dt.date, root: Path, db: Path) -> dict:
    """All steps for one day, in order. The DAG runs the same steps as separate tasks."""
    out = {"extract": extract(day, root), "load": load_raw(day, root, db)}
    out["models"] = build_models(db)
    out["quality"] = quality_gate(db)
    out["report"] = str(finance_report(db, root / "reports"))
    out["marts"] = export_marts(db, root / "marts")
    return out
