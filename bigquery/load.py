"""Load the GA4 shaped events and the booking fact into BigQuery and run the queries there.

Works with the free BigQuery sandbox (no billing needed, tables expire after 60 days):

    pip install -r requirements-cloud.txt
    gcloud auth application-default login
    export GCP_PROJECT=your-project-id
    python -m bookings ga4                  # builds data/marts/ga4_events.parquet
    python bigquery/load.py                 # loads both tables, runs the three queries

The same three queries run locally on DuckDB in the tests (they are translated with sqlglot);
this script is the run against real BigQuery.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent.parent
DATASET = os.environ.get("BQ_DATASET", "booking_platform")
TABLES = ("ga4_events", "fct_bookings")
QUERIES = ("sessions_by_medium", "funnel_by_medium", "purchases_vs_bookings")


def main() -> None:
    project = os.environ.get("GCP_PROJECT")
    if not project:
        sys.exit("Set GCP_PROJECT to your Google Cloud project id.")
    client = bigquery.Client(project=project)
    client.create_dataset(bigquery.Dataset(f"{project}.{DATASET}"), exists_ok=True)
    for t in TABLES:
        path = ROOT / "data" / "marts" / f"{t}.parquet"
        cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.PARQUET,
                                     write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        with open(path, "rb") as f:
            client.load_table_from_file(f, f"{project}.{DATASET}.{t}", job_config=cfg).result()
        print(f"loaded {t}: {client.get_table(f'{project}.{DATASET}.{t}').num_rows:,} rows")
    names = {t: f"{project}.{DATASET}.{t}" for t in TABLES}
    for q in QUERIES:
        sql = (ROOT / "ga4" / "bigquery" / f"{q}.sql").read_text().format(**names)
        df = client.query(sql).to_dataframe()
        print(f"\n== {q} ({len(df)} rows)\n{df.head(10).to_string(index=False)}")


if __name__ == "__main__":
    main()
