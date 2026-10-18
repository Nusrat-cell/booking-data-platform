from pathlib import Path

import pytest

pytest.importorskip("airflow")
from airflow.models import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parent.parent / "dags"


def test_dag_imports_without_errors():
    bag = DagBag(dag_folder=str(DAGS), include_examples=False)
    assert not bag.import_errors, bag.import_errors
    assert "daily_bookings" in bag.dags


def test_dag_shape_and_settings():
    dag = DagBag(dag_folder=str(DAGS), include_examples=False).dags["daily_bookings"]
    assert [t.task_id for t in dag.topological_sort()] == ["extract", "load_raw", "build_models", "quality_gate", "finance_report"]
    assert dag.max_active_runs == 1 and dag.catchup is False
    assert all(t.retries == 2 for t in dag.tasks)
