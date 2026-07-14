from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

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
    def test_merges_all_series_into_one_row_per_date(self) -> None:
        # The five daily series share min/avg/pXX keys; merging without prefixing would clobber them,
        # and dropping a series would silently lose columns. This is the source's core transform.
        payload = {
            "time_in_queue": [{"date": "2021-07-14", "min": 12, "p50": 23}],
            "wait_times_to_queue": [{"date": "2021-07-14", "min": 5, "p50": 8.2}],
            "mergequeue_usage": [{"date": "2021-07-14", "total": 52, "merged_by_bot": 40}],
            "blocked_reason": [{"date": "2021-07-14", "merge_conflict": 2, "ci_failure": 4}],
            "sync_frequency": [{"date": "2021-07-14", "min": 1, "p90": 3.2}],
        }
        rows = _flatten_analytics("aviator-co/testrepo", "aviator-co", "testrepo", payload)
        assert rows == [
            {
                "repo": "aviator-co/testrepo",
                "org": "aviator-co",
                "name": "testrepo",
                "date": "2021-07-14",
                "time_in_queue_min": 12,
                "time_in_queue_p50": 23,
                "wait_times_to_queue_min": 5,
                "wait_times_to_queue_p50": 8.2,
                "mergequeue_usage_total": 52,
                "mergequeue_usage_merged_by_bot": 40,
                "blocked_reason_merge_conflict": 2,
                "blocked_reason_ci_failure": 4,
                "sync_frequency_min": 1,
                "sync_frequency_p90": 3.2,
            }
        ]

    def test_rows_are_sorted_by_date_and_span_multiple_days(self) -> None:
        payload = {
            "mergequeue_usage": [
                {"date": "2021-07-15", "total": 3},
                {"date": "2021-07-14", "total": 1},
            ],
        }
        rows = _flatten_analytics("o/r", "o", "r", payload)
        assert [r["date"] for r in rows] == ["2021-07-14", "2021-07-15"]

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
    @freeze_time("2026-06-15")
    def test_first_sync_uses_default_lookback(self) -> None:
        # No watermark: pull the configured history window (365 days) rather than an unbounded range.
        config = AVIATOR_ENDPOINTS["merge_queue_analytics"]
        start, end = _analytics_window(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert start == "2025-06-15"
        assert end == "2026-06-15"

    @freeze_time("2026-06-15")
    def test_incremental_run_rewinds_watermark_by_lookback(self) -> None:
        # Recent daily aggregates get revised upstream, so each run must re-pull a trailing window;
        # advancing straight from the watermark would freeze the last few days at stale values.
        config = AVIATOR_ENDPOINTS["merge_queue_analytics"]
        start, end = _analytics_window(
            config, should_use_incremental_field=True, db_incremental_field_last_value=date(2026, 6, 10)
        )
        assert start == "2026-06-03"  # 2026-06-10 minus the 7-day lookback
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
        with freeze_time("2026-06-15"):
            start, _ = _analytics_window(
                config, should_use_incremental_field=True, db_incremental_field_last_value=value
            )
        assert start == expected_start

    @freeze_time("2026-06-15")
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

    def test_queue_stats_flattens_depth_object(self, monkeypatch: Any) -> None:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            return {"depth": {"queued": 8, "processing": 2, "waiting": 6}}

        rows = _run_fan_out(
            "queue_stats", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert rows == [{"org": "o", "repo": "r", "queued": 8, "processing": 2, "waiting": 6}]

    def test_config_history_paginates_and_flattens_applied_by(self, monkeypatch: Any) -> None:
        # Pagination must terminate on the first empty page; applied_by is flattened so the row is a
        # flat record with the injected org/repo the endpoint's primary key needs.
        page_payloads = {
            1: {
                "history": [
                    {
                        "applied_at": "2022-11-16T17:21:41Z",
                        "commit_sha": "abc",
                        "diff": "x",
                        "applied_by": {"email": "a@b.co"},
                    }
                ]
            },
            2: {"history": []},
        }
        seen_pages: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
            page = (params or {}).get("page", 1)
            seen_pages.append(page)
            return page_payloads[page]

        rows = _run_fan_out(
            "config_history", fake_fetch, [{"org": "o", "name": "r"}], _FakeResumableManager(), monkeypatch
        )
        assert seen_pages == [1, 2]
        assert rows == [
            {
                "org": "o",
                "repo": "r",
                "applied_at": "2022-11-16T17:21:41Z",
                "commit_sha": "abc",
                "diff": "x",
                "applied_by_email": "a@b.co",
                "applied_by_gh_username": None,
            }
        ]

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

        with freeze_time("2026-06-15"):
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


class TestFanOutResume:
    def _fetch_stats(self, session: Any, url: str, headers: dict, logger: Any, params: dict | None = None) -> Any:
        p = params or {}
        return {"depth": {"queued": 1, "processing": 0, "waiting": 1, "_repo": p.get("repo")}}

    def test_marks_each_repo_completed_as_it_finishes(self, monkeypatch: Any) -> None:
        # State accumulates completed repo keys AFTER each repo's rows are yielded, so a crash resumes
        # with only the repos still owed (and a crash mid-repo re-processes it, since merge dedupes).
        manager = _FakeResumableManager()
        repos = [{"org": "o", "name": "a"}, {"org": "o", "name": "b"}, {"org": "o", "name": "c"}]
        _run_fan_out("queue_stats", self._fetch_stats, repos, manager, monkeypatch)
        assert [s.completed_repo_keys for s in manager.saved] == [
            ["o/a"],
            ["o/a", "o/b"],
            ["o/a", "o/b", "o/c"],
        ]

    def test_resume_skips_completed_repos(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(AviatorResumeConfig(completed_repo_keys=["o/a"]))
        repos = [{"org": "o", "name": "a"}, {"org": "o", "name": "b"}, {"org": "o", "name": "c"}]
        rows = _run_fan_out("queue_stats", self._fetch_stats, repos, manager, monkeypatch)
        assert [r["repo"] for r in rows] == ["b", "c"]

    def test_resume_processes_repo_added_before_the_resume_point(self, monkeypatch: Any) -> None:
        # A repo discovered ahead of already-completed ones on retry must NOT be skipped. A positional
        # bookmark would drop it, and since the watermark only advances at successful job end, that
        # repo's older analytics would never be fetched outside the trailing lookback window.
        manager = _FakeResumableManager(AviatorResumeConfig(completed_repo_keys=["o/b"]))
        repos = [{"org": "o", "name": "new"}, {"org": "o", "name": "b"}, {"org": "o", "name": "c"}]
        rows = _run_fan_out("queue_stats", self._fetch_stats, repos, manager, monkeypatch)
        assert [r["repo"] for r in rows] == ["new", "c"]

    def test_resume_with_only_unknown_completed_keys_processes_all(self, monkeypatch: Any) -> None:
        # A completed repo removed between runs must not strand the sync; every current repo runs.
        manager = _FakeResumableManager(AviatorResumeConfig(completed_repo_keys=["o/gone"]))
        repos = [{"org": "o", "name": "a"}, {"org": "o", "name": "b"}]
        rows = _run_fan_out("queue_stats", self._fetch_stats, repos, manager, monkeypatch)
        assert [r["repo"] for r in rows] == ["a", "b"]


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

    def test_client_error_raises_without_retry(self) -> None:
        import requests

        bad = requests.Response()
        bad.status_code = 401
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            aviator._fetch(session, "https://api.aviator.co/api/v1/repo", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponseSortMode:
    @parameterized.expand(
        [
            ("repositories", "asc", None),
            ("merge_queue_analytics", "desc", "date"),
            ("queued_pull_requests", "desc", "created_at"),
            ("queue_stats", "desc", None),
            ("config_history", "desc", "applied_at"),
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
