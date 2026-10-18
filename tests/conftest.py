import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bookings import generate, pipeline  # noqa: E402


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    root = tmp_path_factory.mktemp("platform")
    db = root / "wh.duckdb"
    day = dt.date(2026, 9, 1)
    for i in range(24):  # 1 to 24 Sep: covers the 15th, the day without a CHF rate
        d = day + dt.timedelta(days=i)
        pipeline.extract(d, root)
        pipeline.load_raw(d, root, db)
    pipeline.build_models(db)
    return root, db
