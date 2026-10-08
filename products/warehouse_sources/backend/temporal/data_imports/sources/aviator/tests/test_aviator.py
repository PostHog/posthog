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
    _iter_repositories,
    aviator_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import AVIATOR_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: AviatorResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AviatorResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AviatorResumeConfig | None:
        return self._state

    def save_state(self, data: AviatorResumeConfig) -> None:
        self.saved.append(data)


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
        calls: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            page = (params or {}).get("page", 1)
            calls.append(page)
            return pages[page - 1]

        with patch.object(aviator, "_fetch", fake_fetch):
            repos = list(_iter_repositories(MagicMock(), {}, MagicMock()))

        assert len(calls) == expected_calls
        assert repos == [row for page in pages for row in page]


def _run_fan_out(
    endpoint: str,
    fake_fetch: Any,
    repos: list[dict],
    manager: _FakeResumableManager,
    monkeypatch: Any,
    **incremental: Any,
) -> list[dict]:
    monkeypatch.setattr(aviator, "_iter_repositories", lambda *a, **k: iter(repos))
    monkeypatch.setattr(aviator, "_fetch", fake_fetch)
    rows: list[dict] = []
    for table in get_rows(
        api_token="av_uat_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestFanOutExtraction:
    def test_queued_pull_requests_inject_org_repo_and_drop_nested_repository(self, monkeypatch: Any) -> None:
        # PR number is unique only within a repo, so the injected org/repo are what make the
        # composite primary key unique table-wide across the fan-out.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {
                "pull_requests": [
                    {"number": 89, "title": "fix", "repository": {"org": "o", "name": "r"}, "status": "queued"}
                ]
            }

        rows = _run_fan_out(
            "queued_pull_requests", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert rows == [{"number": 89, "title": "fix", "status": "queued", "org": "o", "repo": "r"}]

    def test_queued_pull_request_without_number_is_skipped(self, monkeypatch: Any) -> None:
        # number is part of the (org, repo, number) primary key; a null-keyed row would collapse
        # every numberless PR in the repo into a single persisted row, so such rows are dropped.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {"pull_requests": [{"number": 7, "title": "keep"}, {"title": "no number"}]}

        rows = _run_fan_out(
            "queued_pull_requests", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert [r["title"] for r in rows] == ["keep"]

    def test_config_history_entry_without_applied_at_is_skipped(self, monkeypatch: Any) -> None:
        # applied_at is part of the (org, repo, applied_at) primary key; a null-keyed row would
        # collapse multiple config changes into one persisted row, so such rows are dropped.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            page = (params or {}).get("page", 1)
            if page == 1:
                return {
                    "history": [
                        {"applied_at": "2022-11-16T17:21:41Z", "commit_sha": "keep"},
                        {"commit_sha": "no applied_at"},
                    ]
                }
            return {"history": []}

        rows = _run_fan_out(
            "config_history", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert [r["commit_sha"] for r in rows] == ["keep"]

    def test_analytics_fan_out_requests_repo_slug_and_window(self, monkeypatch: Any) -> None:
        # The analytics call is only correct if it forwards repo=org/name plus the incremental window;
        # a regression that dropped either would sync the wrong (or unbounded) data.
        captured: dict[str, Any] = {}

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            captured.update(params or {})
            return {"mergequeue_usage": [{"date": "2026-06-14", "total": 5}]}

        with time_machine.travel("2026-06-15", tick=False):
            rows = _run_fan_out(
                "merge_queue_analytics",
                fake_fetch,
                [{"org": "aviator-co", "name": "testrepo"}],
                _FakeResumableManager(),
                monkeypatch,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 10),
                incremental_field="date",
            )
        assert captured == {"repo": "aviator-co/testrepo", "start": "2026-06-03", "end": "2026-06-15"}
        assert rows == [
            {
                "repo": "aviator-co/testrepo",
                "org": "aviator-co",
                "name": "testrepo",
                "date": "2026-06-14",
                "mergequeue_usage_total": 5,
            }
        ]


class TestBranchesFanOut:
    def test_branch_without_a_pattern_is_skipped(self, monkeypatch: Any) -> None:
        # pattern is part of the (org, repo, pattern) primary key; a null-keyed row would collapse
        # every patternless branch in the repo into a single persisted row, so such rows are dropped.
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, **kwargs: Any) -> Any:
            return {"branches": [{"pattern": "master", "paused": False}, {"paused": True}]}

        rows = _run_fan_out("branches", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch)
        assert [r["pattern"] for r in rows] == ["master"]


class TestBotPullRequestsFanOut:
    @staticmethod
    def _fetch_for(queued: list[int], bot_prs: dict[int, Any]) -> Any:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, **kwargs: Any) -> Any:
            if url.endswith("/pull_request/queued"):
                return {"pull_requests": [{"number": n} for n in queued]}
            return bot_prs.get(kwargs["params"]["number"])

        return fake_fetch

    def test_queued_prs_sharing_a_batch_yield_one_row(self, monkeypatch: Any) -> None:
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
        fake_fetch = self._fetch_for([89, 90, 91], {89: batch, 90: batch, 91: batch})

        rows = _run_fan_out(
            "bot_pull_requests", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )

        # head_branch_oid is a documented legacy alias for head_commit_sha, so it is not carried.
        # The pipeline lands the member list as a JSON string, which is what the warehouse column holds.
        assert rows == [
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

    def test_queued_prs_without_a_batch_are_skipped(self, monkeypatch: Any) -> None:
        # Serial-mode repos never create bot PRs, so the lookup 404s for every queued PR. That must
        # sync an empty table rather than fail the whole run.
        fake_fetch = self._fetch_for([89, 90], {89: None, 90: {"number": 202, "pull_requests": []}})

        rows = _run_fan_out(
            "bot_pull_requests", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert [(r["number"], r["pull_request_numbers"]) for r in rows] == [(202, "[]")]


class TestUserActions:
    @staticmethod
    def _run(pages: dict[int, Any], monkeypatch: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, **kwargs: Any) -> Any:
            return pages[kwargs["params"]["page"]]

        monkeypatch.setattr(aviator, "_fetch", fake_fetch)
        rows: list[dict] = []
        for table in get_rows(
            api_token="av_uat_test",
            endpoint="user_actions",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())
        return rows

    def test_entry_without_a_timestamp_is_skipped(self, monkeypatch: Any) -> None:
        # timestamp leads the composite primary key and the endpoint exposes no id, so an entry
        # without one cannot be identified at all.
        pages = {
            1: [{"timestamp": "2026-06-15T10:00:00Z", "action": "keep"}, {"action": "no timestamp"}],
            2: [],
        }
        rows = self._run(pages, monkeypatch)
        assert [r["action"] for r in rows] == ["keep"]


class TestFanOutResume:
    def _fetch_stats(self, session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
        p = params or {}
        return {"depth": {"queued": 1, "processing": 0, "waiting": 1, "_repo": p.get("repo")}}

    def test_resume_processes_repo_added_before_the_resume_point(self, monkeypatch: Any) -> None:
        # A repo discovered ahead of already-completed ones on retry must NOT be skipped. A positional
        # bookmark would drop it, and since the watermark only advances at successful job end, that
        # repo's older analytics would never be fetched outside the trailing lookback window.
        manager = _FakeResumableManager(AviatorResumeConfig(completed_repo_keys=["o/b"]))
        repos = [{"org": "o", "name": "new"}, {"org": "o", "name": "b"}, {"org": "o", "name": "c"}]
        rows = _run_fan_out("queue_stats", self._fetch_stats, repos, manager, monkeypatch)
        assert [r["repo"] for r in rows] == ["new", "c"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(aviator, "make_tracked_session", return_value=session):
            assert validate_credentials("av_uat_test") is expected

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(aviator, "make_tracked_session", return_value=session):
            assert validate_credentials("av_uat_test") is False


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
        response = aviator_source(
            api_token="av_uat_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == AVIATOR_ENDPOINTS[endpoint].primary_keys
