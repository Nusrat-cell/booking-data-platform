"""Daily bookings pipeline: extract, load, build the models, check the numbers, publish the report.

Each task is a thin wrapper around a function in bookings/pipeline.py, which is where the logic
and the tests are. The quality gate fails the run when a blocking check fails, so the finance
report is never built from numbers that do not reconcile.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from airflow.sdk import dag, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bookings import pipeline  # noqa: E402

ROOT = Path(os.environ.get("BOOKINGS_ROOT", Path(__file__).resolve().parent.parent / "data"))
DB = Path(os.environ.get("BOOKINGS_DB", ROOT / "warehouse.duckdb"))


@dag(
    dag_id="daily_bookings",
    schedule="@daily",
    start_date=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
    catchup=False,
    max_active_runs=1,  # one writer at a time: DuckDB allows a single writer
    default_args={"retries": 2, "retry_delay": dt.timedelta(minutes=5)},
    tags=["bookings", "finance"],
)
def daily_bookings():
    @task
    def extract(ds=None) -> str:
        pipeline.extract(dt.date.fromisoformat(ds), ROOT)
        return ds

    @task
    def load_raw(day: str) -> dict:  # not named "ds": Airflow reserves that name for its context
        return pipeline.load_raw(dt.date.fromisoformat(day), ROOT, DB)

    @task
    def build_models(loaded: dict) -> list[str]:
        return pipeline.build_models(DB)

    @task
    def quality_gate(built: list[str]) -> list[dict]:
        return pipeline.quality_gate(DB)

    @task
    def finance_report(checks: list[dict]) -> str:
        pipeline.export_marts(DB, ROOT / "marts")
        return str(pipeline.finance_report(DB, ROOT / "reports"))

    day = extract()
    finance_report(quality_gate(build_models(load_raw(day))))


daily_bookings()
