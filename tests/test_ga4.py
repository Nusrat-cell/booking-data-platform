import duckdb
import pytest

from bookings import ga4


@pytest.fixture(scope="module")
def db(warehouse):
    _, path = warehouse
    ga4.build_ga4(path)
    return path


def q(db, sql):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_events_have_the_ga4_export_shape(db):
    cols = {r[0]: r[1] for r in q(db, "DESCRIBE ga4_events")}
    for c in ("event_date", "event_timestamp", "event_name", "event_params", "user_pseudo_id", "traffic_source", "ecommerce"):
        assert c in cols
    assert cols["event_timestamp"] == "BIGINT"
    assert cols["event_params"].startswith("STRUCT(\"key\" VARCHAR") and cols["event_params"].endswith("[]")
    assert q(db, "SELECT count(*) FROM ga4_events WHERE event_name='session_start' AND "
                 "list_filter(event_params, x -> x.key='ga_session_id')[1].value.int_value IS NULL")[0][0] == 0


def test_every_session_has_a_source_and_medium(db):
    df = ga4.run_query(db, "sessions_by_medium")
    assert (df["sessions"] > 0).all()
    assert df["medium"].notna().all() and df["source"].notna().all()


def test_funnel_never_grows_on_the_way_down(db):
    df = ga4.run_query(db, "funnel_by_medium")
    assert ((df.sessions >= df.viewed_item) & (df.viewed_item >= df.began_checkout) & (df.began_checkout >= df.purchased)).all()
    assert df.purchased.sum() > 0


def test_session_count_matches_session_start_events(db):
    df = ga4.run_query(db, "sessions_by_medium")
    (n,) = q(db, "SELECT count(*) FROM (SELECT DISTINCT user_pseudo_id, "
                 "list_filter(event_params, x -> x.key='ga_session_id')[1].value.int_value FROM ga4_events WHERE event_name='session_start')")[0]
    assert df.sessions.sum() == n


def test_reconciliation_finds_the_planted_tracking_loss(db):
    df = ga4.run_query(db, "purchases_vs_bookings")
    missing = 1 - df.ga4_transactions.sum() / df.bookings.sum()
    assert 0.03 < missing < 0.12          # about 7 percent of purchases never reach analytics
    assert df.double_fired.sum() > 0      # purchases sent twice are visible
    assert (df.ga4_transactions <= df.bookings).all()


def test_every_ga4_purchase_is_a_real_booking(db):
    (orphans,) = q(db, "SELECT count(DISTINCT ecommerce.transaction_id) FROM ga4_events WHERE event_name='purchase' "
                       "AND ecommerce.transaction_id NOT IN (SELECT booking_id FROM fct_bookings WHERE status='confirmed')")[0]
    assert orphans == 0


def test_bigquery_files_translate_without_duckdb_only_syntax():
    import sqlglot
    for name in ("sessions_by_medium", "funnel_by_medium", "purchases_vs_bookings"):
        sql = ga4.bigquery_sql(name, {"ga4_events": "p.d.ga4_events", "fct_bookings": "p.d.fct_bookings"})
        assert "`" not in sql.replace("`p.d.ga4_events`", "").replace("`p.d.fct_bookings`", "")
        assert sqlglot.parse_one(sql, read="bigquery") is not None


def test_postgres_types_cover_every_flat_mart(warehouse, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import export_to_postgres as ex
    from bookings import pipeline
    _, path = warehouse
    pipeline.export_marts(path, tmp_path)
    ga4.export_parquet(path, tmp_path)
    con = duckdb.connect()
    for t in ex.TABLES:
        for name, typ, *_ in con.execute(f"DESCRIBE SELECT * FROM '{tmp_path / (t + '.parquet')}'").fetchall():
            assert ex.pg_type(typ)
