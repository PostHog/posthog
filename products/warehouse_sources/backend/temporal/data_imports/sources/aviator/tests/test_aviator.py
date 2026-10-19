from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aviator import aviator
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.aviator import (
    AviatorResumeConfig,
    _analytics_window,
    _flatten_analytics,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import AVIATOR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.source import AviatorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aviator import (
    AviatorSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AviatorSource(), AviatorSourceConfig(api_token="av_uat_test"))


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    return [row for table in result.rows for row in table.to_pylist()]


class TestFlattenAnalytics:
    def test_missing_or_malformed_series_are_ignored(self) -> None:
        # A partial response (only some series present, a non-list series, a dateless item) must not crash.
        payload: dict[str, Any] = {
            "time_in_queue": [{"date": "2021-07-14", "avg": 24}],
            "sync_frequency": "unexpected",
            "blocked_reason": [{"min": 1}],
        }
        rows = _flatten_analytics("o/r", "o", "r", payload)
        assert rows == [{"repo": "o/r", "org": "o", "name": "r", "date": "2021-07-14", "time_in_queue_avg": 24}]


class TestAnalyticsWindow:
    @time_machine.travel("2026-06-15", tick=False)
    def test_first_sync_uses_default_lookback(self) -> None:
        # No watermark: pull the configured history window (365 days) rather than an unbounded range.
        config = AVIATOR_ENDPOINTS["merge_queue_analytics"]
        start, end = _analytics_window(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert start == "2025-06-15"
        assert end == "2026-06-15"

    @parameterized.expand(
        [
            ("date_object", date(2026, 6, 10), "2026-06-03"),
            ("datetime_object", datetime(2026, 6, 10, 8, 30, tzinfo=UTC), "2026-06-03"),
            ("iso_string", "2026-06-10T08:30:00+00:00", "2026-06-03"),
        ]
    )
    def test_watermark_accepts_multiple_value_types(self, _name: str, value: Any, expected_start: str) -> None:
        config = AVIATOR_ENDPOINTS["merge_queue_analytics"]
        with time_machine.travel("2026-06-15", tick=False):
            start, _ = _analytics_window(
                config, should_use_incremental_field=True, db_incremental_field_last_value=value
            )
        assert start == expected_start

    @time_machine.travel("2026-06-15", tick=False)
    def test_future_watermark_is_clamped_to_today(self) -> None:
        # A future-dated watermark would otherwise make start > end and produce an invalid window.
        config = AVIATOR_ENDPOINTS["merge_queue_analytics"]
        start, end = _analytics_window(
            config, should_use_incremental_field=True, db_incremental_field_last_value=date(2027, 1, 1)
        )
        assert start == "2026-06-15"
        assert end == "2026-06-15"


class TestIterRepositories:
    @parameterized.expand(
        [
            # A short final page (< 10) signals the end, so the paginator stops without an extra request.
            ("single_partial_page", [[{"org": "o", "name": "a"}, {"org": "o", "name": "b"}]], 1),
            (
                "full_then_partial_page",
                [[{"org": "o", "name": f"r{i}"} for i in range(10)], [{"org": "o", "name": "last"}]],
                2,
            ),
            # Exactly-full final page forces one more request that returns empty, then stops.
            (
                "full_then_empty_page",
                [[{"org": "o", "name": f"r{i}"} for i in range(10)], []],
                2,
            ),
        ]
    )
    def test_pagination_terminates(self, _name: str, pages: list[list[dict]], expected_calls: int) -> None:
        result = _driver().run("repositories", [ScriptedResponse(json=page) for page in pages])

        assert result.raised is None
        assert result.paths == ["/api/v1/repo"] * expected_calls
        assert result.params("page") == [str(page) for page in range(1, expected_calls + 1)]
        assert _rows(result) == [row for page in pages for row in page]


class TestFanOutExtraction:
    def test_queued_pull_requests_inject_org_repo_and_drop_nested_repository(self) -> None:
        # PR number is unique only within a repo, so the injected org/repo are what make the
        # composite primary key unique table-wide across the fan-out.
        result = _driver().run(
            "queued_pull_requests",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(
                    json={
                        "pull_requests": [
                            {"number": 89, "title": "fix", "repository": {"org": "o", "name": "r"}, "status": "queued"}
                        ]
                    }
                ),
            ],
        )
        assert result.raised is None
        assert result.paths == ["/api/v1/repo", "/api/v1/pull_request/queued"]
        assert _rows(result) == [{"number": 89, "title": "fix", "status": "queued", "org": "o", "repo": "r"}]

    def test_queued_pull_request_without_number_is_skipped(self) -> None:
        # number is part of the (org, repo, number) primary key; a null-keyed row would collapse
        # every numberless PR in the repo into a single persisted row, so such rows are dropped.
        result = _driver().run(
            "queued_pull_requests",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(json={"pull_requests": [{"number": 7, "title": "keep"}, {"title": "no number"}]}),
            ],
        )
        assert result.raised is None
        assert [row["title"] for row in _rows(result)] == ["keep"]

    def test_config_history_entry_without_applied_at_is_skipped(self) -> None:
        # applied_at is part of the (org, repo, applied_at) primary key; a null-keyed row would
        # collapse multiple config changes into one persisted row, so such rows are dropped.
        result = _driver().run(
            "config_history",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(
                    json={
                        "history": [
                            {"applied_at": "2022-11-16T17:21:41Z", "commit_sha": "keep"},
                            {"commit_sha": "no applied_at"},
                        ]
                    }
                ),
                ScriptedResponse(json={"history": []}),
            ],
        )
        assert result.raised is None
        assert result.params("page") == ["1", "1", "2"]
        assert [row["commit_sha"] for row in _rows(result)] == ["keep"]

    def test_analytics_fan_out_requests_repo_slug_and_window(self) -> None:
        # The analytics call is only correct if it forwards repo=org/name plus the incremental window;
        # a regression that dropped either would sync the wrong (or unbounded) data.
        with time_machine.travel("2026-06-15", tick=False):
            result = _driver().run(
                "merge_queue_analytics",
                [
                    ScriptedResponse(json=[{"org": "aviator-co", "name": "testrepo"}]),
                    ScriptedResponse(json={"mergequeue_usage": [{"date": "2026-06-14", "total": 5}]}),
                ],
                db_incremental_field_last_value=date(2026, 6, 10),
                incremental_field="date",
            )
        assert result.raised is None
        assert {key: result.requests[1].param(key) for key in ("repo", "start", "end")} == {
            "repo": "aviator-co/testrepo",
            "start": "2026-06-03",
            "end": "2026-06-15",
        }
        assert _rows(result) == [
            {
                "repo": "aviator-co/testrepo",
                "org": "aviator-co",
                "name": "testrepo",
                "date": "2026-06-14",
                "mergequeue_usage_total": 5,
            }
        ]


class TestBranchesFanOut:
    def test_branch_without_a_pattern_is_skipped(self) -> None:
        # pattern is part of the (org, repo, pattern) primary key; a null-keyed row would collapse
        # every patternless branch in the repo into a single persisted row, so such rows are dropped.
        result = _driver().run(
            "branches",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(json={"branches": [{"pattern": "master", "paused": False}, {"paused": True}]}),
            ],
        )
        assert result.raised is None
        assert result.requests[1].json() == {"repository": {"org": "o", "name": "r"}}
        assert [row["pattern"] for row in _rows(result)] == ["master"]


class TestBotPullRequestsFanOut:
    def test_queued_prs_sharing_a_batch_yield_one_row(self) -> None:
        # Every queued PR in a batch resolves to the same bot PR. Merge only dedupes across syncs, so
        # emitting all three would put duplicate (org, repo, number) keys in one batch, and every
        # later merge would multi-match them.
        batch = {
            "number": 201,
            "github_url": "https://github.com/o/r/pull/201",
            "target_branch": "master",
            "head_commit_sha": "abc",
            "head_branch_oid": "abc",
            "codemix_pre_batch_sha": "def",
            "pull_requests": [{"number": 89}, {"number": 90}, {"number": 91}],
        }
        result = _driver().run(
            "bot_pull_requests",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(json={"pull_requests": [{"number": 89}, {"number": 90}, {"number": 91}]}),
                ScriptedResponse(json=batch),
                ScriptedResponse(json=batch),
                ScriptedResponse(json=batch),
            ],
        )

        # head_branch_oid is a documented legacy alias for head_commit_sha, so it is not carried.
        # The pipeline lands the member list as a JSON string, which is what the warehouse column holds.
        assert result.raised is None
        assert result.params("number") == [None, None, "89", "90", "91"]
        assert _rows(result) == [
            {
                "org": "o",
                "repo": "r",
                "number": 201,
                "github_url": "https://github.com/o/r/pull/201",
                "target_branch": "master",
                "head_commit_sha": "abc",
                "codemix_pre_batch_sha": "def",
                "pull_request_numbers": "[89,90,91]",
            }
        ]

    def test_queued_prs_without_a_batch_are_skipped(self) -> None:
        # Serial-mode repos never create bot PRs, so the lookup 404s for every queued PR. That must
        # sync an empty table rather than fail the whole run.
        result = _driver().run(
            "bot_pull_requests",
            [
                ScriptedResponse(json=[{"org": "o", "name": "r"}]),
                ScriptedResponse(json={"pull_requests": [{"number": 89}, {"number": 90}]}),
                ScriptedResponse(status=404),
                ScriptedResponse(json={"number": 202, "pull_requests": []}),
            ],
        )
        assert result.raised is None
        assert result.params("number") == [None, None, "89", "90"]
        assert [(row["number"], row["pull_request_numbers"]) for row in _rows(result)] == [(202, "[]")]


class TestUserActions:
    def test_entry_without_a_timestamp_is_skipped(self) -> None:
        # timestamp leads the composite primary key and the endpoint exposes no id, so an entry
        # without one cannot be identified at all.
        result = _driver().run(
            "user_actions",
            [
                ScriptedResponse(
                    json=[{"timestamp": "2026-06-15T10:00:00Z", "action": "keep"}, {"action": "no timestamp"}]
                ),
                ScriptedResponse(json=[]),
            ],
        )
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert [row["action"] for row in _rows(result)] == ["keep"]


class TestFanOutResume:
    def test_resume_processes_repo_added_before_the_resume_point(self) -> None:
        # A repo discovered ahead of already-completed ones on retry must NOT be skipped. A positional
        # bookmark would drop it, and since the watermark only advances at successful job end, that
        # repo's older analytics would never be fetched outside the trailing lookback window.
        repos = [{"org": "o", "name": "new"}, {"org": "o", "name": "b"}, {"org": "o", "name": "c"}]
        result = _driver().run(
            "queue_stats",
            [
                ScriptedResponse(json=repos),
                ScriptedResponse(json={"depth": {"queued": 1, "processing": 0, "waiting": 1}}),
                ScriptedResponse(json={"depth": {"queued": 1, "processing": 0, "waiting": 1}}),
            ],
            resume_state=AviatorResumeConfig(completed_repo_keys=["o/b"]),
        )
        assert result.raised is None
        assert result.params("repo") == [None, "new", "c"]
        assert [row["repo"] for row in _rows(result)] == ["new", "c"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json=[])]) as network:
            assert validate_credentials("av_uat_test") is expected
        assert network.requests_log[0].path == "/api/v1/repo"
        assert network.requests_log[0].param("page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer av_uat_test"
        assert network.session_options == [{"redact_values": ("av_uat_test",), "capture": False}]

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(ConnectionError("reset"))) as network:
            assert validate_credentials("av_uat_test") is False
        assert {request.path for request in network.requests_log} == {"/api/v1/repo"}


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"ok": True}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(aviator._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = aviator._fetch(session, "https://api.aviator.co/api/v1/repo", {}, MagicMock())

        assert result == {"ok": True}
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_without_retry(self, _name: str, status: int) -> None:
        bad = requests.Response()
        bad.status_code = status
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            aviator._fetch(session, "https://api.aviator.co/api/v1/repo", {}, MagicMock())
        assert session.get.call_count == 1

    def test_not_found_returns_none_only_when_opted_in(self) -> None:
        # The bot-PR lookup treats 404 as "this PR has no batch"; every other caller must still raise,
        # otherwise a mistyped path would silently sync an empty table.
        bad = requests.Response()
        bad.status_code = 404
        session = MagicMock()
        session.get.return_value = bad

        result = aviator._fetch(
            session, "https://api.aviator.co/api/v1/bot_pull_request", {}, MagicMock(), none_on_not_found=True
        )
        assert result is None


class TestSourceResponseSortMode:
    @parameterized.expand(
        [
            ("repositories", "asc", None),
            ("merge_queue_analytics", "desc", "date"),
            ("queued_pull_requests", "desc", "created_at"),
            ("queue_stats", "desc", None),
            ("config_history", "desc", "applied_at"),
            ("branches", "desc", None),
            ("bot_pull_requests", "desc", None),
            # Top-level, but the endpoint documents newest-first ordering, so it is desc too.
            ("user_actions", "desc", "timestamp"),
        ]
    )
    def test_sort_mode_and_partition(self, endpoint: str, expected_sort: str, partition_key: str | None) -> None:
        # Fan-out endpoints must report "desc" so the watermark persists only at successful job end;
        # reverting to "asc" per-batch persistence lets a crashed run advance past unreached repos.
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == AVIATOR_ENDPOINTS[endpoint].primary_keys
