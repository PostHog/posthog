from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from unittest import mock

from products.query_performance_ai.orchestrator import slow_queries


def test_build_sql_substitutes_filters() -> None:
    sql = slow_queries.build_sql(team_id=42, lookback_hours=12, limit=7)
    assert "team_id') = 42" in sql
    assert "INTERVAL 12 HOUR" in sql
    assert "LIMIT 7" in sql
    assert "ai_data_processing_approved') = 'true'" in sql
    assert "hasAll(" not in sql  # no available_columns filter when arg omitted


def test_build_sql_with_available_dictionaries_adds_has_all_filter() -> None:
    sql = slow_queries.build_sql(
        team_id=2,
        lookback_hours=24,
        limit=1,
        available_dictionaries=["posthog.web_pre_aggregated_teams_dict"],
    )
    assert "used_dictionaries" in sql
    assert "posthog.web_pre_aggregated_teams_dict" in sql
    # Empty list (`[]`) is meaningful — it requires queries to use no
    # dictionaries at all. Distinguish from `None` (skip the filter).
    sql_empty = slow_queries.build_sql(
        team_id=2,
        lookback_hours=24,
        limit=1,
        available_dictionaries=[],
    )
    assert "used_dictionaries" in sql_empty
    sql_none = slow_queries.build_sql(team_id=2, lookback_hours=24, limit=1, available_dictionaries=None)
    assert "used_dictionaries" not in sql_none


def test_build_sql_with_available_columns_adds_has_all_filter() -> None:
    sql = slow_queries.build_sql(
        team_id=2,
        lookback_hours=24,
        limit=1,
        available_columns=["team_id", "event", "timestamp"],
    )
    assert "hasAll(" in sql
    # Compare on column NAME only, not full database.table.column; that lets
    # prod's `sharded_events` and the test cluster's `events` match.
    assert "splitByChar('.', c)[3]" in sql
    assert "team_id" in sql
    assert "event" in sql
    # backticks must be stripped before comparison so `mat_$host` matches `mat_$host`.
    assert "'`'" in sql


def test_parse_metabase_response_typed_records() -> None:
    raw = json.dumps(
        {
            "data": {
                "cols": [
                    {"name": "query_id"},
                    {"name": "team_id"},
                    {"name": "clickhouse_query"},
                    {"name": "hogql_query"},
                    {"name": "query_duration_ms"},
                    {"name": "read_bytes"},
                    {"name": "event_time_iso"},
                ],
                "rows": [
                    [
                        "q1",
                        2,
                        "SELECT count() FROM events",
                        '{"kind":"HogQLQuery"}',
                        31000,
                        5000,
                        "2026-05-01 09:00:00",
                    ],
                    ["q2", 2, "SELECT 2", "", 60000, 12345, "2026-05-01 09:30:00"],
                ],
            }
        }
    )
    rows = slow_queries.parse_metabase_response(raw)
    assert len(rows) == 2
    assert rows[0].query_id == "q1"
    assert rows[0].query_duration_ms == 31000
    assert rows[0].clickhouse_query == "SELECT count() FROM events"
    assert rows[0].hogql_query == '{"kind":"HogQLQuery"}'
    assert rows[1].read_bytes == 12345
    assert rows[1].clickhouse_query == "SELECT 2"


def test_fetch_slow_queries_propagates_hogli_failure() -> None:
    completed: Any = subprocess.CompletedProcess(args=["hogli"], returncode=1, stdout="", stderr="boom")
    with mock.patch.object(subprocess, "run", return_value=completed):
        with pytest.raises(RuntimeError, match="hogli metabase:query failed"):
            slow_queries.fetch_slow_queries(region="us", database_id=1, team_id=2, limit=1)


def test_fetch_slow_queries_passes_args_via_stdin() -> None:
    payload = json.dumps({"data": {"cols": [], "rows": []}})
    completed: Any = subprocess.CompletedProcess(args=["hogli"], returncode=0, stdout=payload, stderr="")
    with mock.patch.object(subprocess, "run", return_value=completed) as run_mock:
        slow_queries.fetch_slow_queries(region="eu", database_id=99, team_id=2, limit=3)
    args, kwargs = run_mock.call_args
    assert args[0][:5] == ["hogli", "metabase:query", "--region", "eu", "--database-id"]
    assert "99" in args[0]
    # SQL is fed via stdin, NOT argv — keeps it off /proc/.../cmdline.
    assert "INTERVAL 24 HOUR" in kwargs["input"]
