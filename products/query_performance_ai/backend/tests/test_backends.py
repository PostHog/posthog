from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from unittest import mock

from products.query_performance_ai.scripts.backends.base import BackendError
from products.query_performance_ai.scripts.backends.metabase import MetabaseBackend


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    return subprocess.CompletedProcess(args=["hogli"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_metabase_backend_parses_running_time_and_rows() -> None:
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
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)):
        result = backend.run("SELECT 1", timeout_s=30)
    assert result.rows == [[1], [2]]
    assert result.elapsed_ms == 42.5
    assert result.rows_read is None
    assert result.bytes_read is None


def test_metabase_backend_falls_back_to_round_trip_when_no_running_time() -> None:
    body = json.dumps({"data": {"cols": [], "rows": []}})
    backend = MetabaseBackend(region="us", database_id=7, team_id=2)
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout=body)):
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
