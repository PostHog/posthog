from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from unittest import mock

from products.query_performance_ai.orchestrator.backends.base import BackendError
from products.query_performance_ai.orchestrator.backends.metabase import MetabaseBackend, _tag_with_log_comment


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    return subprocess.CompletedProcess(args=["hogli"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_metabase_backend_falls_back_to_running_time_when_query_log_misses() -> None:
    """When the query_log poll returns nothing, fall back to Metabase's `running_time`."""
    body = json.dumps(
        {
            "data": {
                "cols": [{"name": "n"}],
                "rows": [[1], [2]],
            },
            "running_time": 42.5,
        }
    )
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with (
        mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)),
        mock.patch.object(MetabaseBackend, "_fetch_query_log_metrics", return_value=None),
    ):
        result = backend.run("SELECT 1", timeout_s=30)
    assert result.rows == [[1], [2]]
    assert result.elapsed_ms == 42.5
    assert result.rows_read is None
    assert result.bytes_read is None
    assert result.query_id is None


def test_metabase_backend_uses_query_log_metrics_when_available() -> None:
    """When the query_log poll returns a row, use those CH-side metrics — not running_time."""
    body = json.dumps(
        {
            "data": {"cols": [{"name": "n"}], "rows": [[1]]},
            "running_time": 9999.0,  # Should be ignored.
        }
    )
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with (
        mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)),
        mock.patch.object(
            MetabaseBackend, "_fetch_query_log_metrics", return_value=(123.0, 1000, 50000, "abcd-query-id")
        ),
    ):
        result = backend.run("SELECT 1", timeout_s=30)
    # The 9999ms running_time is overridden by the 123ms CH-side number.
    assert result.elapsed_ms == 123.0
    assert result.rows_read == 1000
    assert result.bytes_read == 50000
    assert result.query_id == "abcd-query-id"


def test_metabase_backend_falls_back_to_round_trip_when_no_running_time() -> None:
    body = json.dumps({"data": {"cols": [], "rows": []}})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with (
        mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)),
        mock.patch.object(MetabaseBackend, "_fetch_query_log_metrics", return_value=None),
    ):
        result = backend.run("SELECT 1", timeout_s=30)
    assert result.elapsed_ms >= 0


def test_metabase_backend_raises_backend_error_on_hogli_failure() -> None:
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", return_value=_completed(returncode=1, stderr="Query failed: SYNTAX")):
        with pytest.raises(BackendError, match="Query failed: SYNTAX"):
            backend.run("SELECT bad", timeout_s=30)


def test_metabase_backend_raises_backend_error_when_response_status_failed() -> None:
    body = json.dumps({"status": "failed", "error": "no such column"})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)):
        with pytest.raises(BackendError, match="no such column"):
            backend.run("SELECT bad", timeout_s=30)


def test_metabase_backend_raises_backend_error_on_non_json() -> None:
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout="not json")):
        with pytest.raises(BackendError, match="non-JSON"):
            backend.run("SELECT 1", timeout_s=30)


def test_metabase_backend_raises_backend_error_on_timeout() -> None:
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=["hogli"], timeout=5)):
        with pytest.raises(BackendError, match="timed out"):
            backend.run("SELECT 1", timeout_s=5)


def test_metabase_backend_tags_candidate_with_autoresearch_run_id() -> None:
    """The candidate SQL must carry an autoresearch_run_id we can later look up."""
    body = json.dumps({"data": {"rows": []}, "running_time": 1.0})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    captured: dict[str, str] = {}

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        captured["sql"] = kwargs.get("input") or ""
        return _completed(stdout=body)

    with (
        mock.patch.object(subprocess, "run", side_effect=fake_run),
        mock.patch.object(MetabaseBackend, "_fetch_query_log_metrics", return_value=None),
    ):
        backend.run("SELECT 1", timeout_s=30)
    assert "autoresearch_run_id" in captured["sql"]
    # The id is interpolated into the JSON inside the log_comment string.
    assert "autoresearch_test_cluster_replay" in captured["sql"]


def test_fetch_query_log_metrics_returns_tuple_when_row_present() -> None:
    body = json.dumps({"data": {"rows": [[567.0, 12345, 6789012, "uuid-a-b-c"]]}})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)):
        out = backend._fetch_query_log_metrics("0123456789abcdef")
    assert out == (567.0, 12345, 6789012, "uuid-a-b-c")


def test_fetch_query_log_metrics_returns_none_when_poll_budget_exhausted() -> None:
    """No row in `data.rows` for any poll attempt → returns None (caller falls back)."""
    body = json.dumps({"data": {"rows": []}})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with (
        mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)),
        mock.patch("time.sleep"),  # don't actually wait
    ):
        out = backend._fetch_query_log_metrics("0123456789abcdef")
    assert out is None


def test_fetch_query_log_metrics_rejects_invalid_run_id() -> None:
    """Defence-in-depth: malformed run_id (anything but 16 hex) returns None without querying."""
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run") as mocked:
        # Wrong length, contains non-hex, includes a quote injection attempt.
        assert backend._fetch_query_log_metrics("short") is None
        assert backend._fetch_query_log_metrics("g" * 16) is None
        assert backend._fetch_query_log_metrics("' OR 1=1 --     ") is None
        mocked.assert_not_called()


def test_metabase_backend_target_and_prompt_addendum() -> None:
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    assert backend.target == "test_cluster"
    addendum = backend.prompt_addendum()
    assert "team 2" in addendum.lower()
    assert "rewrite" in addendum.lower()


def test_metabase_backend_prompt_addendum_parameterizes_team_id() -> None:
    backend = MetabaseBackend(region="us", database_id=7, team_id=42)
    addendum = backend.prompt_addendum()
    assert "team 42" in addendum.lower()
    assert "team 2" not in addendum.lower()


@pytest.mark.parametrize(
    "input_sql,expected_substring",
    [
        # No existing SETTINGS clause: appended at the end.
        ("SELECT 1", "SETTINGS log_comment = '"),
        # Trailing semicolon stripped before appending.
        ("SELECT 1;", "SETTINGS log_comment = '"),
        # Existing SETTINGS clause: log_comment spliced into it.
        (
            "SELECT 1 SETTINGS max_threads = 4",
            "SETTINGS log_comment = '",
        ),
        # Multiple settings preserved alongside log_comment.
        (
            "SELECT 1 SETTINGS max_threads = 4, max_memory_usage = 1000000",
            "max_threads = 4",
        ),
    ],
)
def test_tag_with_log_comment_handles_existing_settings(input_sql: str, expected_substring: str) -> None:
    tagged = _tag_with_log_comment(input_sql, '{"feature":"autoresearch"}')
    assert expected_substring in tagged
    assert '"feature":"autoresearch"' in tagged


def test_tag_with_log_comment_escapes_single_quotes_in_json() -> None:
    # ClickHouse string literals double-up single quotes; the JSON value must
    # be escaped so a quote in the comment doesn't terminate the string early.
    tagged = _tag_with_log_comment("SELECT 1", '{"who":"that\'s me"}')
    # The original `'` must appear as `''` inside the SQL string literal.
    assert "that''s me" in tagged
    assert "log_comment = '" in tagged


def test_tag_with_log_comment_merges_into_last_settings_only() -> None:
    """If a query has the word `SETTINGS` in a string/comment we still inject — the
    worst-case is a parse error from CH, which is loud and trivial to debug."""
    sql = "SELECT 1 SETTINGS max_threads = 2"
    tagged = _tag_with_log_comment(sql, '{"k":"v"}')
    # log_comment is inserted right after the existing SETTINGS keyword.
    assert "SETTINGS log_comment = " in tagged
    assert "max_threads = 2" in tagged
