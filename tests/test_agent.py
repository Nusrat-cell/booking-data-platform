import json
from types import SimpleNamespace as NS

import pytest

from agent import ops_agent


@pytest.mark.parametrize("bad", [
    "DROP TABLE fct_bookings",
    "SELECT 1; DELETE FROM fct_bookings",
    "UPDATE fct_bookings SET status = 'x'",
    "SELECT * FROM fct_bookings; SELECT 2",
    "COPY fct_bookings TO '/tmp/x.csv'",
    "ATTACH 'other.db'",
])
def test_unsafe_queries_are_refused(bad):
    with pytest.raises(ops_agent.UnsafeQuery):
        ops_agent.check_query(bad)


def test_select_and_with_are_allowed():
    assert ops_agent.check_query("SELECT 1;") == "SELECT 1"
    assert ops_agent.check_query("WITH a AS (SELECT 1) SELECT * FROM a").startswith("WITH")


def test_tool_runs_read_only(warehouse):
    _, db = warehouse
    out = json.loads(ops_agent.run_tool("run_sql", {"query": "SELECT count(*) AS n FROM fct_bookings"}, str(db)))
    assert out["columns"] == ["n"] and out["rows"][0][0] > 0
    assert ops_agent.run_tool("run_sql", {"query": "DELETE FROM fct_bookings"}, str(db)).startswith("error:")


def test_result_is_capped(warehouse):
    _, db = warehouse
    out = json.loads(ops_agent.run_tool("run_sql", {"query": "SELECT * FROM stg_touchpoints"}, str(db)))
    assert len(out["rows"]) == ops_agent.MAX_ROWS


def test_sql_error_goes_back_to_the_model_not_up_the_stack(warehouse):
    _, db = warehouse
    assert ops_agent.run_tool("run_sql", {"query": "SELECT nope FROM fct_bookings"}, str(db)).startswith("error:")


class FakeClient:
    """Plays the model: asks for a query, then answers using what the tool returned."""
    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace_create(self)


def SimpleNamespace_create(owner):
    def create(**kw):
        owner.calls += 1
        if owner.calls == 1:
            return NS(content=[NS(type="tool_use", id="t1", name="run_sql",
                                  input={"query": "SELECT count(*) AS n FROM fct_bookings"})])
        result = kw["messages"][-1]["content"][0]["content"]
        return NS(content=[NS(type="text", text=f"Bookings: {json.loads(result)['rows'][0][0]}")])
    return NS(create=create)


def test_agent_loop_calls_the_tool_and_answers(warehouse):
    _, db = warehouse
    client = FakeClient()
    answer = ops_agent.ask("How many bookings do we have?", str(db), client=client)
    assert answer.startswith("Bookings: ") and client.calls == 2
