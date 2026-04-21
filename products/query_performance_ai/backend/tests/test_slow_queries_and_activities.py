"""Tests for slow_queries aggregation + workflow-layer helpers.

These are pure-Python tests — no ClickHouse, no sandbox. They cover the
pieces that otherwise only run in a live weekly workflow and are easy to
regress if the schema drifts.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from products.query_performance_ai.backend.slow_queries import (
    _AGGREGATE_SQL,
    SlowQueryCandidate,
    fetch_slow_query_candidates,
)
from products.query_performance_ai.backend.temporal.workflows import _extract_best_sql


class TestAggregateSQL:
    """Guard rails on the slow-query aggregation query.

    If any of these fail, the weekly workflow is going to either (a) ingest
    non-opted-in queries, (b) skip the frequency gate, or (c) point at the
    wrong column names. Cheap to assert, expensive to miss.
    """

    def test_filters_on_ai_approval(self):
        assert "ai_data_processing_approved" in _AGGREGATE_SQL

    def test_reads_team_id_from_log_comment(self):
        assert "JSONExtractInt(log_comment, 'team_id')" in _AGGREGATE_SQL

    def test_groups_by_normalized_query_hash(self):
        assert "normalized_query_hash" in _AGGREGATE_SQL
        assert "GROUP BY normalized_query_hash" in _AGGREGATE_SQL

    def test_filters_to_query_finish_type(self):
        # Running queries / ExceptionWhileProcessing etc. are noise.
        assert "type = 'QueryFinish'" in _AGGREGATE_SQL

    def test_parameterizes_bounds(self):
        for name in ("%(window_days)s", "%(min_duration_ms)s", "%(min_executions)s", "%(limit)s", "%(cluster)s"):
            assert name in _AGGREGATE_SQL


class TestFetchSlowQueryCandidates:
    def test_returns_typed_dataclasses(self):
        fake_rows = [
            ("0xabc123", 2, "qid-001", "SELECT count() FROM events", 8123.5, 42_000_000, 150),
            ("0xdef456", 7, "qid-002", "SELECT * FROM persons", 3200.0, 1_000_000, 40),
        ]
        with patch("products.query_performance_ai.backend.slow_queries.sync_execute", return_value=fake_rows) as mocked:
            results = fetch_slow_query_candidates(window_days=3, min_duration_ms=1000)

        # Parameters should flow through to ClickHouse.
        params = mocked.call_args.args[1]
        assert params["window_days"] == 3
        assert params["min_duration_ms"] == 1000

        assert len(results) == 2
        first = results[0]
        assert isinstance(first, SlowQueryCandidate)
        assert first.normalized_query_hash == "0xabc123"
        assert first.team_id == 2
        assert first.executions == 150

    def test_empty_result(self):
        with patch("products.query_performance_ai.backend.slow_queries.sync_execute", return_value=[]):
            results = fetch_slow_query_candidates()
        assert results == []


class TestExtractBestSql:
    def test_returns_best_sql_when_present(self):
        assert _extract_best_sql({"best_sql": "SELECT 1"}) == "SELECT 1"

    def test_returns_empty_for_none(self):
        assert _extract_best_sql(None) == ""

    def test_returns_empty_for_non_dict(self):
        # Defensive: if the serializer ever hands us a list/str/etc we
        # degrade gracefully rather than crashing the workflow.
        assert _extract_best_sql("not a dict") == ""  # type: ignore[arg-type]

    def test_returns_empty_when_missing(self):
        assert _extract_best_sql({"other": "value"}) == ""

    def test_returns_empty_when_non_string(self):
        assert _extract_best_sql({"best_sql": 42}) == ""


class TestParseTaskDescription:
    """Covers the JSON + bare-SQL parsing the autoresearch activity does.

    We import the activity module inline to keep the Django-free test file
    tidy — the helper itself is pure-Python once imported.
    """

    def _helper(self):
        from products.tasks.backend.temporal.process_task.activities.run_autoresearch_campaign import (
            _parse_task_description,
        )

        return _parse_task_description

    def test_json_payload(self):
        helper = self._helper()

        class FakeTask:
            id = "task-xyz"
            description = json.dumps({"sql": "SELECT 1", "query_id": "slow-abc"})

        sql, qid = helper(FakeTask())
        assert sql == "SELECT 1"
        assert qid == "slow-abc"

    def test_json_payload_without_query_id(self):
        helper = self._helper()

        class FakeTask:
            id = "task-abc"
            description = json.dumps({"sql": "SELECT 2"})

        sql, qid = helper(FakeTask())
        assert sql == "SELECT 2"
        assert qid == "task-task-abc"

    def test_bare_sql_fallback(self):
        helper = self._helper()

        class FakeTask:
            id = "task-123"
            description = "SELECT count() FROM events"

        sql, qid = helper(FakeTask())
        assert sql == "SELECT count() FROM events"
        assert qid == "task-task-123"

    def test_rejects_empty_description(self):
        from products.tasks.backend.temporal.exceptions import TaskInvalidStateError

        helper = self._helper()

        class FakeTask:
            id = "task-empty"
            description = "   "

        with pytest.raises(TaskInvalidStateError):
            helper(FakeTask())
