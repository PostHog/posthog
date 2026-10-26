from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triggerdev import (
    TriggerDevSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev import trigger_dev
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.source import TriggerDevSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.trigger_dev import (
    TriggerDevResumeConfig,
    _format_incremental_value,
    _should_stop_desc,
    resolve_base_url,
    validate_base_url,
)

BASE_URL = "https://api.trigger.dev"


def _run(endpoint: str, script: Script, **kwargs: Any) -> DriveResult:
    driver = SourceDriver(TriggerDevSource(), TriggerDevSourceConfig(api_key="tr_prod_x"))
    return driver.run(endpoint, script, **kwargs)


def _json(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "run_1234", "run_1234"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestResolveBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, "https://api.trigger.dev"),
            ("empty", "", "https://api.trigger.dev"),
            ("trailing_slash", "https://trigger.acme.internal/", "https://trigger.acme.internal"),
            ("custom", "https://trigger.acme.dev", "https://trigger.acme.dev"),
        ]
    )
    def test_resolve(self, _name: str, given: str | None, expected: str) -> None:
        assert resolve_base_url(given) == expected


class TestValidateBaseUrl:
    @parameterized.expand(
        [
            ("default", "https://api.trigger.dev"),
            ("self_hosted_https", "https://trigger.acme.dev"),
        ]
    )
    def test_https_urls_pass(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is None

    @parameterized.expand(
        [
            # Plaintext would send the secret bearer token in the clear.
            ("http", "http://trigger.acme.dev"),
            # `urlsplit` reads the host as example.com, but requests connects to 169.254.169.254.
            ("backslash_authority_confusion", "https://169.254.169.254\\@example.com"),
        ]
    )
    def test_unsafe_urls_are_rejected(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is not None


class TestShouldStopDesc:
    def test_no_cutoff_never_stops(self) -> None:
        # First sync has no watermark; stopping early here would truncate the initial backfill.
        items = [{"createdAt": "2020-01-01T00:00:00Z"}]
        assert _should_stop_desc(items, "createdAt", None) is False


class TestRunsCursorPagination:
    @parameterized.expand(
        [
            ("runs", "filter[createdAt][from]"),
            ("deployments", "from"),
            ("waitpoint_tokens", "filter[createdAt][from]"),
        ]
    )
    def test_incremental_filters_first_page_then_stops_at_watermark(self, endpoint: str, filter_param: str) -> None:
        # The createdAt filter is only sent on page one; later cursor pages must stop client-side once
        # a page predates the watermark, or every incremental sync re-walks all history.
        responses = [
            _json(
                {
                    "data": [
                        {"id": "r3", "createdAt": "2026-01-12T00:00:00Z"},
                        {"id": "r2", "createdAt": "2026-01-11T00:00:00Z"},
                    ],
                    "pagination": {"next": "r2"},
                }
            ),
            _json(
                {
                    "data": [{"id": "r1", "createdAt": "2026-01-02T00:00:00Z"}],
                    "pagination": {"next": "r0"},
                }
            ),
            # Never fetched: the walk stops after the page containing r1 (older than the cutoff).
            _json({"data": [{"id": "should_not_fetch"}], "pagination": {"next": None}}),
        ]
        result = _run(
            endpoint,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert [r["id"] for r in result.rows] == ["r3", "r2", "r1"]
        assert len(result.requests) == 2
        assert result.requests[0].param(filter_param) is not None
        assert filter_param not in result.requests[1].query

    def test_errors_send_the_wide_period_on_every_page(self) -> None:
        # Without the period the API counts only the last day, so most error groups would be missing.
        responses = [
            _json({"data": [{"id": "error_a", "taskIdentifier": "t1"}], "pagination": {"next": "c1"}}),
            _json({"data": [{"id": "error_a", "taskIdentifier": "t2"}], "pagination": {}}),
        ]
        result = _run("errors", responses)
        assert [(r["id"], r["taskIdentifier"]) for r in result.rows] == [("error_a", "t1"), ("error_a", "t2")]
        assert result.params("filter[period]") == ["365d", "365d"]
        assert result.requests[1].param("page[after]") == "c1"

    def test_waitpoint_tokens_drop_the_callback_url(self) -> None:
        # The callback URL completes the token without an API key, so it must never reach the warehouse.
        token = {
            "id": "waitpoint_1",
            "status": "WAITING",
            "url": "https://api.trigger.dev/api/v1/waitpoints/tokens/waitpoint_1/callback/fakehash",
            "createdAt": "2026-01-12T00:00:00Z",
        }
        result = _run("waitpoint_tokens", [_json({"data": [token], "pagination": {}})])
        assert result.rows == [{"id": "waitpoint_1", "status": "WAITING", "createdAt": "2026-01-12T00:00:00Z"}]

    def test_stages_next_page_cursor_before_each_yield(self) -> None:
        # A resumed full refresh appends without merging, so the state must point at the first unread
        # page: staging the current cursor would replay a page that was already written.
        responses = [
            _json({"data": [{"id": "r3"}], "pagination": {"next": "r2"}}),
            _json({"data": [{"id": "r1"}], "pagination": {"next": None}}),
        ]
        result = _run("errors", responses)
        assert [s.after for s in result.saved_states] == ["r2"]


class TestRunEventsFanOut:
    def test_fetches_events_per_run_across_run_pages(self) -> None:
        responses = [
            _json(
                {
                    "data": [
                        {"id": "run_b", "createdAt": "2026-01-12T00:00:00Z"},
                        {"id": "run_gone", "createdAt": "2026-01-11T12:00:00Z"},
                        {"id": "run_quiet", "createdAt": "2026-01-11T06:00:00Z"},
                    ],
                    "pagination": {"next": "run_quiet"},
                }
            ),
            _json({"events": [{"spanId": "s1"}, {"spanId": "s2"}]}),
            # A run deleted after the runs page was read is skipped, not fatal.
            ScriptedResponse(status=404, json={"error": "Run not found"}),
            _json({"events": []}),
            _json({"data": [{"id": "run_a", "createdAt": "2026-01-10T00:00:00Z"}], "pagination": {}}),
            _json({"events": [{"spanId": "s1"}]}),
        ]
        result = _run("run_events", responses)
        assert [(r["_runs_id"], r["spanId"], r["_runs_createdAt"]) for r in result.rows] == [
            ("run_b", "s1", "2026-01-12T00:00:00Z"),
            ("run_b", "s2", "2026-01-12T00:00:00Z"),
            ("run_a", "s1", "2026-01-10T00:00:00Z"),
        ]
        assert [r.path for r in result.requests] == [
            "/api/v1/runs",
            "/api/v1/runs/run_b/events",
            "/api/v1/runs/run_gone/events",
            "/api/v1/runs/run_quiet/events",
            "/api/v1/runs",
            "/api/v1/runs/run_a/events",
        ]
        assert result.requests[4].param("page[after]") == "run_quiet"

    def test_stages_the_run_before_its_events_and_resumes_after_it(self) -> None:
        # A full refresh appends without merging, so a resume must not replay the events of a run
        # that was already written, even when it is in the middle of a runs page.
        runs_page = {
            "data": [
                {"id": "run_b", "createdAt": "2026-01-12T00:00:00Z"},
                {"id": "run_a", "createdAt": "2026-01-11T00:00:00Z"},
            ],
            "pagination": {},
        }
        events = _json({"events": [{"spanId": "s1"}]})
        fresh = _run("run_events", [_json(runs_page), events, events])
        assert [(s.after, s.last_run_id) for s in fresh.saved_states] == [(None, "run_b"), (None, "run_a")]

        resumed = _run(
            "run_events",
            [_json(runs_page), _json({"events": [{"spanId": "s9"}]})],
            resume_state=TriggerDevResumeConfig(after=None, last_run_id="run_b"),
        )
        assert [(r["_runs_id"], r["spanId"]) for r in resumed.rows] == [("run_a", "s9")]
        assert [r.path for r in resumed.requests] == ["/api/v1/runs", "/api/v1/runs/run_a/events"]

    def test_resume_skips_newer_runs_when_the_checkpointed_run_was_deleted(self) -> None:
        # Without the marker run, the createdAt boundary keeps the newer, already written runs out.
        runs_page = {
            "data": [
                {"id": "run_c", "createdAt": "2026-01-12T00:00:00Z"},
                {"id": "run_a", "createdAt": "2026-01-10T00:00:00Z"},
            ],
            "pagination": {},
        }
        resumed = _run(
            "run_events",
            [_json(runs_page), _json({"events": [{"spanId": "s9"}]})],
            resume_state=TriggerDevResumeConfig(
                after=None, last_run_id="run_b", last_run_created_at="2026-01-11T00:00:00Z"
            ),
        )
        assert [r["_runs_id"] for r in resumed.rows] == ["run_a"]
        assert [r.path for r in resumed.requests] == ["/api/v1/runs", "/api/v1/runs/run_a/events"]

    def test_runs_before_the_cutoff_cost_no_events_request(self) -> None:
        # The page that crosses the watermark still lists older runs. They were synced before, and each
        # one would cost a request.
        runs_page = {
            "data": [
                {"id": "run_new", "createdAt": "2026-01-12T00:00:00Z"},
                {"id": "run_old", "createdAt": "2026-01-05T00:00:00Z"},
            ],
            "pagination": {"next": "run_old"},
        }
        result = _run(
            "run_events",
            [_json(runs_page), _json({"events": [{"spanId": "s1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert [r["_runs_id"] for r in result.rows] == ["run_new"]
        assert [r.path for r in result.requests] == ["/api/v1/runs", "/api/v1/runs/run_new/events"]

    def test_runs_without_events_are_staged_so_a_resume_skips_them(self) -> None:
        runs_page = {"data": [{"id": "run_quiet", "createdAt": "2026-01-12T00:00:00Z"}], "pagination": {}}
        result = _run("run_events", [_json(runs_page), _json({"events": []})])
        assert [s.last_run_id for s in result.saved_states] == ["run_quiet"]


class TestClassicPagination:
    def test_walks_pages_until_total_and_never_checkpoints(self) -> None:
        # schedules/queues are small full-refresh tables: walk page/perPage to the last page and never
        # save resume state (a restart just re-reads from page one).
        responses = [
            _json({"data": [{"id": "sched_1"}], "pagination": {"currentPage": 1, "totalPages": 2, "count": 2}}),
            _json({"data": [{"id": "sched_2"}], "pagination": {"currentPage": 2, "totalPages": 2, "count": 2}}),
        ]
        result = _run("schedules", responses)
        assert [r["id"] for r in result.rows] == ["sched_1", "sched_2"]
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == []

    def test_stops_on_empty_page(self) -> None:
        result = _run("queues", [_json({"data": [], "pagination": {"currentPage": 1, "totalPages": 5, "count": 0}})])
        assert result.rows == []
        assert len(result.requests) == 1

    def test_bails_out_of_a_never_ending_pager(self) -> None:
        # A page endpoint that keeps returning non-empty data with no totalPages must not loop forever.
        with patch.object(trigger_dev, "MAX_CLASSIC_PAGES", 7):
            result = _run("queues", always(_json({"data": [{"id": "q"}], "pagination": {}})))
        assert len(result.requests) == 7


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(trigger_dev._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error: Unauthorized", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponseSortMode:
    @parameterized.expand(
        [
            ("runs", "desc"),
            ("deployments", "desc"),
            ("waitpoint_tokens", "desc"),
            ("run_events", "desc"),
            ("errors", "asc"),
            ("schedules", "asc"),
            ("queues", "asc"),
        ]
    )
    def test_sort_mode_matches_arrival_order(self, endpoint: str, expected: str) -> None:
        # Runs arrive newest-first; declaring asc there would corrupt the incremental watermark.
        response = _run(endpoint, []).response
        assert response is not None
        assert response.sort_mode == expected


class TestSampleCapture:
    @parameterized.expand([("runs", True), ("waitpoint_tokens", False)])
    def test_capture_is_off_when_a_field_is_excluded(self, endpoint: str, expected: bool) -> None:
        # HTTP samples are stored before excluded_fields is applied, so the callback URL would leak.
        result = _run(endpoint, [_json({"data": [], "pagination": {}})])
        assert result.session_options[0]["capture"] is expected
