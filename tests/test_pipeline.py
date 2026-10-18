import datetime as dt
import shutil

import duckdb
import pytest

from bookings import generate, pipeline


def q(db, sql, *args):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(sql, list(args)).fetchall()
    finally:
        con.close()


def test_generator_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    day = dt.date(2026, 9, 3)
    generate.generate_day(day, a)
    generate.generate_day(day, b)
    for name in ("bookings.csv", "touchpoints.csv", "ad_spend.csv", "fx_rates.csv"):
        assert (a / "landing" / "2026-09-03" / name).read_text() == (b / "landing" / "2026-09-03" / name).read_text()


def test_rerunning_a_day_changes_nothing(warehouse):
    root, db = warehouse
    before = q(db, "SELECT count(*) FROM raw_bookings")[0][0]
    pipeline.load_raw(dt.date(2026, 9, 5), root, db)
    assert q(db, "SELECT count(*) FROM raw_bookings")[0][0] == before


def test_duplicate_export_is_collapsed(warehouse):
    _, db = warehouse
    assert q(db, "SELECT count(*) FROM (SELECT booking_id FROM stg_bookings GROUP BY 1 HAVING count(*) > 1)")[0][0] == 0
    raw = q(db, "SELECT count(*) FROM raw_bookings")[0][0]
    latest = q(db, "SELECT count(*) FROM stg_bookings_latest")[0][0]
    assert latest < raw


def test_cancelled_export_wins_over_confirmed(warehouse):
    _, db = warehouse
    rows = q(db, "SELECT count(*) FROM raw_bookings WHERE status = 'cancelled'")[0][0]
    cancelled = q(db, "SELECT count(*) FROM fct_bookings WHERE status = 'cancelled'")[0][0]
    assert rows > 0 and cancelled == rows
    assert q(db, "SELECT sum(net_revenue_eur) FROM fct_bookings WHERE status = 'cancelled'")[0][0] == 0


def test_bad_rows_are_rejected_with_a_reason(warehouse):
    _, db = warehouse
    reasons = {r[0] for r in q(db, "SELECT DISTINCT reason FROM stg_bookings_rejected")}
    assert reasons == {"unknown event", "persons must be positive"}
    days = q(db, "SELECT count(DISTINCT _source_day) FROM raw_bookings")[0][0]
    assert q(db, "SELECT count(*) FROM stg_bookings_rejected")[0][0] == 2 * days


def test_every_booking_is_loaded_or_rejected(warehouse):
    _, db = warehouse
    latest = q(db, "SELECT count(*) FROM stg_bookings_latest")[0][0]
    loaded = q(db, "SELECT count(*) FROM stg_bookings")[0][0]
    rejected = q(db, "SELECT count(*) FROM stg_bookings_rejected")[0][0]
    assert latest == loaded + rejected


def test_missing_chf_rate_is_carried_and_marked(warehouse):
    _, db = warehouse
    row = q(db, "SELECT eur_per_unit, fx_source FROM dim_fx_daily WHERE currency = 'CHF' AND day = DATE '2026-09-15'")[0]
    assert row == (1.06, "carried")
    assert q(db, "SELECT count(*) FROM fct_bookings WHERE eur_per_unit IS NULL")[0][0] == 0


def test_booking_after_midnight_still_gets_a_rate(warehouse):
    _, db = warehouse
    after = q(db, "SELECT count(*) FROM fct_bookings b WHERE CAST(booked_at AS DATE) > "
                  "(SELECT CAST(_source_day AS DATE) FROM stg_bookings_latest l JOIN raw_bookings r USING (booking_id) "
                  "WHERE l.booking_id = b.booking_id LIMIT 1)")[0][0]
    assert after > 0
    assert q(db, "SELECT count(*) FROM fct_bookings WHERE eur_per_unit IS NULL")[0][0] == 0


def test_each_credited_booking_has_one_last_touch(warehouse):
    _, db = warehouse
    assert q(db, "SELECT count(*) FROM (SELECT booking_id FROM fct_attribution GROUP BY 1 HAVING count(*) > 1)")[0][0] == 0
    credited = q(db, "SELECT count(*) FROM fct_attribution")[0][0]
    confirmed = q(db, "SELECT count(*) FROM fct_bookings WHERE status = 'confirmed'")[0][0]
    assert 0 < credited <= confirmed


def test_first_and_last_touch_can_differ(warehouse):
    _, db = warehouse
    assert q(db, "SELECT count(*) FROM fct_attribution WHERE first_touch_channel <> last_touch_channel")[0][0] > 0


def test_finance_months_add_up(warehouse):
    _, db = warehouse
    total = q(db, "SELECT sum(net_revenue_eur) FROM mart_finance_monthly")[0][0]
    fact = q(db, "SELECT sum(net_revenue_eur) FROM fct_bookings")[0][0]
    assert abs(total - fact) < 0.5
    assert all(0 < m[0] < 100 for m in q(db, "SELECT margin_pct FROM mart_finance_monthly"))


def test_gate_passes_on_a_clean_run(warehouse):
    _, db = warehouse
    results = pipeline.quality_gate(db)
    assert not [r for r in results if r["status"] == "FAIL"]
    assert any(r["check_id"] == "fx_carried" and r["status"] == "warn" for r in results)


def test_gate_stops_the_run_when_a_booking_is_duplicated(warehouse, tmp_path):
    _, db = warehouse
    broken = tmp_path / "broken.duckdb"
    shutil.copy(db, broken)
    con = duckdb.connect(str(broken))
    con.execute("INSERT INTO fct_bookings SELECT * FROM fct_bookings LIMIT 1")
    con.close()
    with pytest.raises(pipeline.QualityGateFailed, match="booking_id_unique"):
        pipeline.quality_gate(broken)


def test_gate_catches_revenue_that_does_not_reconcile(warehouse, tmp_path):
    _, db = warehouse
    broken = tmp_path / "broken2.duckdb"
    shutil.copy(db, broken)
    con = duckdb.connect(str(broken))
    con.execute("UPDATE fct_bookings SET net_revenue_eur = net_revenue_eur * 1.1 WHERE status = 'confirmed'")
    con.close()
    with pytest.raises(pipeline.QualityGateFailed, match="revenue_reconciles"):
        pipeline.quality_gate(broken)


def test_finance_report_file(warehouse, tmp_path):
    _, db = warehouse
    path = pipeline.finance_report(db, tmp_path)
    lines = path.read_text().splitlines()
    assert lines[0].startswith("month,bookings,cancelled")
    assert len(lines) >= 2


def test_marts_are_exported_as_parquet(warehouse, tmp_path):
    _, db = warehouse
    names = pipeline.export_marts(db, tmp_path)
    assert set(names) == {"mart_attribution_compare", "mart_finance_monthly", "mart_marketing_daily"}
    assert all((tmp_path / f"{n}.parquet").stat().st_size > 0 for n in names)
