from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.snowplow import (
    SnowplowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow import snowplow
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import SNOWPLOW_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.snowplow import (
    SnowplowAuthError,
    SnowplowResumeConfig,
    SnowplowRetryableError,
    _flatten_failed_event_aggregates,
    _iter_windows,
    _jobs_window_bounds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.source import SnowplowSource

_ORG_PATH = "/api/msc/v1/organizations/org-1"
_TOKEN_PATH = f"{_ORG_PATH}/credentials/v3/token"
_TOKEN = ScriptedResponse(json={"accessToken": "jwt"})

Handler = Callable[[str, RecordedRequest], Any]


def _api(handler: Handler) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token exchange itself, and hand every data request to `handler` as (path, request)."""

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == _TOKEN_PATH:
            return _TOKEN
        answer = handler(request.path.removeprefix(_ORG_PATH), request)
        return answer if isinstance(answer, ScriptedResponse) else ScriptedResponse(json=answer)

    return respond


def _run_endpoint(endpoint: str, script: Any, **inputs: Any) -> DriveResult:
    config = SnowplowSourceConfig(organization_id="org-1", api_key_id="key-id", api_key="key")
    return SourceDriver(SnowplowSource(), config).run(endpoint, script, **inputs)


def _data_calls(result: DriveResult) -> list[tuple[str, dict[str, str | None]]]:
    return [
        (request.path.removeprefix(_ORG_PATH), {name: request.param(name) for name in request.query})
        for request in result.requests
        if request.path != _TOKEN_PATH
    ]


class TestWindows:
    @parameterized.expand(
        [
            (
                "exact_multiple",
                datetime(2026, 7, 13, tzinfo=UTC),
                datetime(2026, 7, 15, tzinfo=UTC),
                [("2026-07-13", "2026-07-14"), ("2026-07-14", "2026-07-15")],
            ),
            (
                "partial_last_window",
                datetime(2026, 7, 14, tzinfo=UTC),
                datetime(2026, 7, 15, 6, tzinfo=UTC),
                [("2026-07-14", "2026-07-15"), ("2026-07-15", "2026-07-15")],
            ),
            ("empty_range", datetime(2026, 7, 15, tzinfo=UTC), datetime(2026, 7, 15, tzinfo=UTC), []),
        ]
    )
    def test_iter_windows(self, _name: str, start: datetime, end: datetime, expected_days: list[tuple]) -> None:
        windows = list(_iter_windows(start, end, timedelta(hours=24)))
        assert [(w[0].strftime("%Y-%m-%d"), w[1].strftime("%Y-%m-%d")) for w in windows] == expected_days
        # A window must never extend past the requested end (the API rejects future/oversized windows).
        assert all(w_end <= end for _, w_end in windows)

    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_first_sync_starts_at_the_retention_floor(self) -> None:
        # Snowplow only keeps about a week of runs; asking for more gets the window rejected.
        window = _jobs_window_bounds(
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert window.end == datetime(2026, 7, 15, 12, tzinfo=UTC)
        assert window.start == window.end - snowplow.JOB_RUNS_RETENTION

    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_future_watermark_is_clamped_to_now(self) -> None:
        window = _jobs_window_bounds(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-08-01T00:00:00Z",
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert window.start == window.end


class TestJobRuns:
    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_full_window_logs_a_truncation_warning(self) -> None:
        # The API silently caps a window at 10k rows; without the warning a truncated sync looks complete.
        logger = MagicMock()
        script = _api(lambda path, request: [{"runId": f"r{i}"} for i in range(10_000)])

        _run_endpoint(
            "job_runs",
            script,
            logger=logger,
            resume_state=SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"),
        )

        assert logger.warning.called


class TestJobRunSteps:
    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_run_that_404s_is_skipped(self) -> None:
        # A run that aged out of retention between the window listing and the steps fetch must not
        # fail the whole sync.
        def handler(path: str, request: RecordedRequest) -> Any:
            if path == "/jobs/v1/runs":
                return [
                    {"runId": "gone", "startTime": "2026-07-15T00:10:00Z"},
                    {"runId": "r2", "startTime": "2026-07-15T00:20:00Z"},
                ]
            if path == "/jobs/v1/runs/gone/steps":
                return ScriptedResponse(status=404)
            return [{"name": "step", "state": "SUCCEEDED"}]

        result = _run_endpoint(
            "job_run_steps",
            _api(handler),
            resume_state=SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"),
        )

        assert [r["runId"] for r in result.rows] == ["r2"]

    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_run_without_run_id_is_skipped(self) -> None:
        # runId is part of the (runId, name) primary key; a null-keyed row would collapse steps
        # from every such run into one persisted row.
        def handler(path: str, request: RecordedRequest) -> Any:
            if path == "/jobs/v1/runs":
                return [{"state": "SUCCEEDED"}, {"runId": "r1", "startTime": "2026-07-15T00:10:00Z"}]
            return [{"name": "step", "state": "SUCCEEDED"}]

        result = _run_endpoint(
            "job_run_steps",
            _api(handler),
            resume_state=SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"),
        )

        assert [r["runId"] for r in result.rows] == ["r1"]
        assert ("/jobs/v1/runs/r1/steps", {}) in _data_calls(result)


class TestFlattenFailedEventAggregates:
    def test_rows_without_key_fields_are_skipped(self) -> None:
        # errorId and window are primary key columns; null-keyed rows would collapse distinct
        # aggregates into one persisted row on merge.
        aggregates: list[dict[str, Any]] = [
            {"schemaKey": "s", "metrics": [{"window": "2026-07-14T00:00:00Z", "count": 1}]},
            {"errorId": "e1", "metrics": [{"count": 2}, {"window": "2026-07-15T00:00:00Z", "count": 3}]},
            {"errorId": "e2", "metrics": None},
        ]
        rows = _flatten_failed_event_aggregates("p1", aggregates, MagicMock())
        assert [(r["errorId"], r["window"]) for r in rows] == [("e1", "2026-07-15T00:00:00Z")]


class TestFailedEventMetricsFanOut:
    def _handler(self, path: str, request: RecordedRequest) -> Any:
        if path == "/pipelines/v1":
            return {"pipelines": [{"id": "p1", "name": "prod"}, {"id": "p2", "name": "qa"}]}
        return [
            {
                "errorId": "e1",
                "schemaKey": "s",
                "classification": "Enrichment",
                "metrics": [{"window": "2026-07-15T00:00:00Z", "count": 5, "lastSeen": "2026-07-15T01:00:00Z"}],
            }
        ]

    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_fans_out_over_pipelines_with_incremental_window(self) -> None:
        result = _run_endpoint(
            "failed_event_metrics",
            _api(self._handler),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-15T00:00:00Z",
        )

        expected_params = {"from": "2026-07-14T00:00:00Z", "to": "2026-07-15T12:00:00Z"}
        assert _data_calls(result) == [
            ("/pipelines/v1", {}),
            ("/metrics/v1/pipelines/p1/failed-events", expected_params),
            ("/metrics/v1/pipelines/p2/failed-events", expected_params),
        ]
        assert [r["pipelineId"] for r in result.rows] == ["p1", "p2"]
        # Completed pipelines accumulate AFTER each pipeline's rows are consumed, so a crash
        # mid-pipeline re-processes it (merge dedupes) rather than skipping it.
        assert [s.completed_pipeline_ids for s in result.saved_states] == [["p1"], ["p1", "p2"]]

    @time_machine.travel("2026-07-15T12:00:00Z", tick=False)
    def test_resume_skips_completed_pipelines(self) -> None:
        result = _run_endpoint(
            "failed_event_metrics",
            _api(self._handler),
            resume_state=SnowplowResumeConfig(completed_pipeline_ids=["p1"]),
        )

        assert [r["pipelineId"] for r in result.rows] == ["p2"]
        assert "/metrics/v1/pipelines/p1/failed-events" not in [path for path, _ in _data_calls(result)]


class TestListEndpoints:
    @parameterized.expand(
        [
            ("pipelines", "/pipelines/v1", "pipelines", {}),
            (
                "data_products",
                "/data-products/v2",
                "data",
                {"includes": {"owners": [{"id": "g1"}], "eventSpecs": [{"id": "es9"}]}, "errors": []},
            ),
            ("event_specs", "/event-specs/v1", "data", {"includes": [{"eventSpecId": "x1"}], "metadata": {}}),
            ("source_apps", "/source-apps/v1", "data", {}),
        ]
    )
    def test_unwraps_the_wrapper_object(
        self, endpoint: str, expected_path: str, data_key: str, siblings: dict[str, Any]
    ) -> None:
        rows = [{"id": "a1", "name": "first"}, {"id": "a2", "name": "second"}]
        result = _run_endpoint(endpoint, _api(lambda path, request: {**siblings, data_key: rows}))
        assert result.rows == rows
        assert _data_calls(result) == [(expected_path, {})]

    @parameterized.expand(
        [
            ("missing_key", "data_products", {"includes": {}}),
            ("null_list", "event_specs", {"data": None}),
            ("empty_list", "source_apps", {"data": []}),
            ("empty_bare_array", "data_catalog", []),
        ]
    )
    def test_empty_response_yields_no_rows(self, _name: str, endpoint: str, body: Any) -> None:
        result = _run_endpoint(endpoint, _api(lambda path, request: body))
        assert result.raised is None
        assert result.rows == []

    def test_data_catalog_yields_the_bare_array(self) -> None:
        items = [
            {
                "vendor": "com.example",
                "name": "checkout",
                "format": "jsonschema",
                "version": "1-0-0",
                "itemType": "EVENT",
            },
            {
                "vendor": "com.example",
                "name": "checkout",
                "format": "jsonschema",
                "version": "1-0-0",
                "itemType": "ENTITY",
            },
        ]
        result = _run_endpoint("data_catalog", _api(lambda path, request: items))
        assert result.rows == items
        assert _data_calls(result) == [("/data-catalog/v1", {})]

    def test_users_yields_the_bare_array(self) -> None:
        users = [{"id": "u1", "email": "a@b.co"}]
        result = _run_endpoint("users", _api(lambda path, request: users))
        assert result.rows == users

    @pytest.mark.parametrize(
        "page_sizes,expected_calls",
        [
            # A short final page (< 100) signals the end, so the paginator stops without an extra request.
            ([3], 1),
            ([100, 2], 2),
            # Exactly-full final page forces one more request that returns empty, then stops.
            ([100, 0], 2),
        ],
    )
    def test_data_structures_pagination_terminates(self, page_sizes: list[int], expected_calls: int) -> None:
        pages = [[{"hash": f"h{p}-{i}"} for i in range(size)] for p, size in enumerate(page_sizes)]

        def handler(path: str, request: RecordedRequest) -> Any:
            index = int(request.param("from") or 0) // 100
            return pages[index] if index < len(pages) else []

        result = _run_endpoint("data_structures", _api(handler))
        assert len(_data_calls(result)) == expected_calls
        assert len(result.rows) == sum(page_sizes)


class TestClientAuth:
    def test_persistent_401_raises(self) -> None:
        expired = ScriptedResponse(status=401)

        result = _run_endpoint("users", [_TOKEN, expired, _TOKEN, expired])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 4

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("org_not_found", 404)])
    def test_mint_token_raises_auth_error(self, _name: str, status: int) -> None:
        result = _run_endpoint("users", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, SnowplowAuthError)

    def test_retryable_status_is_retried(self) -> None:
        result = _run_endpoint("users", [_TOKEN, ScriptedResponse(status=503), ScriptedResponse(json=[1])])

        assert result.raised is None
        assert result.rows == [1]
        assert [path for path in result.paths if path != _TOKEN_PATH].count(f"{_ORG_PATH}/users") >= 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status: int) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return _TOKEN if request.path == _TOKEN_PATH else ScriptedResponse(status=status)

        result = _run_endpoint("users", respond)

        assert isinstance(result.raised, SnowplowRetryableError)


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with scripted_network([_TOKEN]) as network:
            assert validate_credentials("org-1", "key-id", "key", MagicMock()) == (True, None)
        request = network.requests_log[0]
        assert request.path == _TOKEN_PATH
        assert (request.headers["x-api-key-id"], request.headers["x-api-key"]) == ("key-id", "key")

    def test_network_error_is_invalid_with_generic_message(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            ok, error = validate_credentials("org-1", "key-id", "key", MagicMock())
        assert ok is False
        assert error is not None

    def test_session_redacts_the_key_and_never_follows_redirects(self) -> None:
        with scripted_network([_TOKEN]) as network:
            validate_credentials("org-1", "key-id", "key", MagicMock())
        assert network.session_options == [{"redact_values": ("key",), "capture": False, "allow_redirects": False}]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("pipelines", "asc", None, ["id"]),
            ("users", "asc", None, ["id"]),
            ("data_models", "asc", None, ["name"]),
            ("data_structures", "asc", None, ["hash"]),
            ("data_products", "asc", "createdAt", ["id"]),
            ("event_specs", "asc", None, ["id", "version"]),
            ("source_apps", "asc", None, ["id"]),
            ("data_catalog", "asc", None, ["vendor", "name", "format", "version", "itemType"]),
            ("job_runs", "desc", "startTime", ["runId"]),
            ("job_run_steps", "desc", "runStartTime", ["runId", "name"]),
            ("failed_event_metrics", "desc", "window", ["pipelineId", "errorId", "window"]),
        ]
    )
    def test_sort_mode_partition_and_primary_keys(
        self, endpoint: str, expected_sort: str, partition_key: str | None, primary_keys: list[str]
    ) -> None:
        # Incremental endpoints must report "desc" so the watermark persists only at successful job
        # end; "asc" per-batch persistence would let a crashed run advance past rows it still owes.
        response = _run_endpoint(endpoint, always(_TOKEN)).response
        assert response is not None
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == SNOWPLOW_ENDPOINTS[endpoint].primary_keys == primary_keys
