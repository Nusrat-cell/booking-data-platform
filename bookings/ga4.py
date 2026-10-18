"""GA4 export shaped events on top of the warehouse, and the BigQuery SQL that reads them.

The queries in ga4/bigquery/ are written in BigQuery Standard SQL. For tests and local use they
are translated to DuckDB with sqlglot, so one set of queries serves both.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import sqlglot

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "ga4" / "bigquery"


def build_ga4(db: Path) -> int:
    con = duckdb.connect(str(db))
    try:
        for path in sorted((ROOT / "sql" / "ga4").glob("*.sql")):
            con.execute(path.read_text())
        return con.execute("SELECT count(*) FROM ga4_events").fetchone()[0]
    finally:
        con.close()


def bigquery_sql(name: str, tables: dict[str, str]) -> str:
    return (QUERIES / f"{name}.sql").read_text().format(**tables)


def run_query(db: Path, name: str):
    """Run a BigQuery query on the local DuckDB copy and return a DataFrame."""
    sql = bigquery_sql(name, {"ga4_events": "ga4_events", "fct_bookings": "fct_bookings"})
    duck = sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]
    # DuckDB has no `key` column when it unnests a list of structs, so the GA4 idiom
    # (SELECT value.x FROM UNNEST(event_params) WHERE key = 'k') becomes a list lookup.
    duck = re.sub(r"\(SELECT value\.(\w+) FROM UNNEST\(event_params\) WHERE key = '(\w+)'\)",
                  r"list_filter(event_params, x -> x.key = '\2')[1].value.\1", duck)
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(duck).df()
    finally:
        con.close()


def export_parquet(db: Path, out_dir: Path) -> list[str]:
    """Write the GA4 shaped events and the booking fact as Parquet, ready to load into BigQuery."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    try:
        for t in ("ga4_events", "fct_bookings"):
            con.execute(f"COPY {t} TO '{out_dir / (t + '.parquet')}' (FORMAT PARQUET)")
    finally:
        con.close()
    return ["ga4_events", "fct_bookings"]
