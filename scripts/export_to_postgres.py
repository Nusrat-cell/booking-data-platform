"""Copy the Parquet marts into Postgres, so Metabase can read them.

Used by docker compose (service `loader`); can also run on its own:
    DATABASE_URL=postgresql://warehouse:warehouse@localhost:5432/warehouse python scripts/export_to_postgres.py
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import psycopg

PG_TYPE = {"VARCHAR": "text", "DOUBLE": "double precision", "BIGINT": "bigint", "INTEGER": "integer",
           "DATE": "date", "TIMESTAMP": "timestamp", "BOOLEAN": "boolean", "HUGEINT": "numeric"}
# Nested GA4 events stay in BigQuery and DuckDB; Metabase reads the flat marts and the booking fact.
TABLES = ("mart_marketing_daily", "mart_finance_monthly", "mart_attribution_compare", "fct_bookings")


def pg_type(duck_type: str) -> str:
    base = duck_type.split("(")[0]
    if base not in PG_TYPE:
        raise ValueError(f"no Postgres type for {duck_type}")
    return PG_TYPE[base]


def main() -> None:
    marts = Path(os.environ.get("MARTS_DIR", "data/marts"))
    url = os.environ.get("DATABASE_URL", "postgresql://warehouse:warehouse@db:5432/warehouse")
    duck = duckdb.connect()
    with psycopg.connect(url) as pg:
        for t in TABLES:
            path = marts / f"{t}.parquet"
            if not path.exists():
                print(f"skip {t}: {path} not found")
                continue
            cols = duck.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()
            ddl = ", ".join(f'"{c[0]}" {pg_type(c[1])}' for c in cols)
            pg.execute(f'DROP TABLE IF EXISTS "{t}"')
            pg.execute(f'CREATE TABLE "{t}" ({ddl})')
            rows = duck.execute(f"SELECT * FROM '{path}'").fetchall()
            with pg.cursor() as cur, cur.copy(f'COPY "{t}" FROM STDIN') as cp:
                for r in rows:
                    cp.write_row(r)
            print(f"{t}: {len(rows):,} rows")
        pg.commit()


if __name__ == "__main__":
    main()
