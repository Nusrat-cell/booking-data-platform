"""A small agent that answers questions about the bookings warehouse with SQL.

It uses the Anthropic Messages API with tool use: the model asks for a tool, this code runs it
against a read-only DuckDB connection, and the result goes back to the model until it answers.
The model never gets a write path to the warehouse: queries must be one SELECT, the connection
is read-only, and the result is capped.

    python -m agent.ops_agent "Why did marketing ROAS drop last week?" --db data/warehouse.duckdb
"""
from __future__ import annotations

import argparse
import json
import os
import re

import duckdb

MAX_ROWS = 100
MAX_TURNS = 8
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")

SYSTEM = (
    "You are a data analyst for an event travel booking platform. Answer with numbers from the "
    "warehouse, not from guesses. Use list_tables first if you do not know the schema. Say when "
    "data is missing or when a number rests on carried forward exchange rates. Keep answers short."
)

TOOLS = [
    {"name": "list_tables", "description": "List tables and their columns in the warehouse.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_sql", "description": f"Run one read-only SELECT query (max {MAX_ROWS} rows returned).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|copy|pragma|install|load|export|call)\b", re.I)


class UnsafeQuery(ValueError):
    pass


def check_query(query: str) -> str:
    q = query.strip().rstrip(";").strip()
    if ";" in q:
        raise UnsafeQuery("only one statement is allowed")
    if not re.match(r"^(select|with)\b", q, re.I):
        raise UnsafeQuery("only SELECT queries are allowed")
    if _FORBIDDEN.search(q):
        raise UnsafeQuery("the query contains a keyword that is not allowed")
    return q


def run_tool(name: str, args: dict, db: str) -> str:
    con = duckdb.connect(db, read_only=True)
    try:
        if name == "list_tables":
            rows = con.execute("SELECT table_name, string_agg(column_name, ', ' ORDER BY ordinal_position) "
                               "FROM information_schema.columns WHERE table_name NOT LIKE 'raw_%' "
                               "GROUP BY table_name ORDER BY table_name").fetchall()
            return "\n".join(f"{t}: {c}" for t, c in rows)
        if name == "run_sql":
            q = check_query(args.get("query", ""))
            cur = con.execute(f"SELECT * FROM ({q}) LIMIT {MAX_ROWS}")
            cols = [d[0] for d in cur.description]
            return json.dumps({"columns": cols, "rows": cur.fetchall()}, default=str)
        return f"unknown tool {name}"
    except (UnsafeQuery, duckdb.Error) as err:
        return f"error: {err}"  # the model sees the error and can fix its query
    finally:
        con.close()


def ask(question: str, db: str, client=None) -> str:
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    for _ in range(MAX_TURNS):
        reply = client.messages.create(model=MODEL, max_tokens=1024, system=SYSTEM, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": reply.content})
        calls = [b for b in reply.content if b.type == "tool_use"]
        if not calls:
            return "".join(b.text for b in reply.content if b.type == "text")
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": run_tool(c.name, c.input, db)} for c in calls]})
    return "Stopped: too many tool calls without an answer."


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--db", default="data/warehouse.duckdb")
    a = ap.parse_args()
    print(ask(a.question, a.db))
