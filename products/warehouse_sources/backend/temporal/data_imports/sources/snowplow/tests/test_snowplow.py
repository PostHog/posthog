from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow import snowplow
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import SNOWPLOW_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.snowplow import (
    SnowplowAuthError,
    SnowplowClient,
    SnowplowResumeConfig,
    _flatten_failed_event_aggregates,
    _iter_windows,
    _jobs_window_bounds,
    get_rows,
    snowplow_source,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: SnowplowResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SnowplowResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SnowplowResumeConfig | None:
        return self._state

    def save_state(self, data: SnowplowResumeConfig) -> None:
        self.saved.append(data)


class _FakeClient:
    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, path: str, params: dict | None = None) -> Any:
        self.calls.append((path, params))
        return self._handler(path, params)


def _run_endpoint(
    endpoint: str,
    handler: Any,
    manager: _FakeResumableManager,
    monkeypatch: Any,
    **incremental: Any,
) -> tuple[list[dict], _FakeClient]:
    client = _FakeClient(handler)
    monkeypatch.setattr(snowplow, "SnowplowClient", lambda *a, **k: client)
    rows: list[dict] = []
    for batch in get_rows(
        organization_id="org-1",
        api_key_id="key-id",
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(batch)
    return rows, client


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

    @freeze_time("2026-07-15T12:00:00Z")
    def test_first_sync_starts_at_the_retention_floor(self) -> None:
        # Snowplow only keeps about a week of runs; asking for more gets the window rejected.
        start, end = _jobs_window_bounds(
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert end == datetime(2026, 7, 15, 12, tzinfo=UTC)
        assert start == end - snowplow.JOB_RUNS_RETENTION

    @freeze_time("2026-07-15T12:00:00Z")
    def test_incremental_run_rewinds_watermark_by_lookback(self) -> None:
        # A run listed while RUNNING changes state after we fetch it; advancing straight from the
        # watermark would freeze it at RUNNING forever.
        start, _ = _jobs_window_bounds(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-15T00:00:00Z",
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert start == datetime(2026, 7, 14, tzinfo=UTC)

    @freeze_time("2026-07-15T12:00:00Z")
    def test_stale_watermark_is_clamped_to_the_retention_floor(self) -> None:
        # A watermark older than the retention window would produce a from the API rejects.
        start, end = _jobs_window_bounds(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01T00:00:00Z",
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert start == end - snowplow.JOB_RUNS_RETENTION

    @freeze_time("2026-07-15T12:00:00Z")
    def test_future_watermark_is_clamped_to_now(self) -> None:
        start, end = _jobs_window_bounds(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-08-01T00:00:00Z",
            resume_window_from=None,
            now=datetime.now(UTC),
        )
        assert start == end

    @freeze_time("2026-07-15T12:00:00Z")
    def test_resume_window_takes_precedence_over_the_watermark(self) -> None:
        # On resume the saved window marks what was already yielded; restarting from the watermark
        # would re-fetch (and re-merge) everything the crashed attempt already produced.
        start, _ = _jobs_window_bounds(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-10T00:00:00Z",
            resume_window_from="2026-07-14T12:00:00Z",
            now=datetime.now(UTC),
        )
        assert start == datetime(2026, 7, 14, 12, tzinfo=UTC)


class TestJobRuns:
    @freeze_time("2026-07-15T12:00:00Z")
    def test_windows_are_requested_and_state_saved_after_each(self, monkeypatch: Any) -> None:
        run = {"runId": "r1", "state": "SUCCEEDED", "startTime": "2026-07-14T00:10:00Z"}

        def handler(path: str, params: dict | None) -> Any:
            assert path == "/jobs/v1/runs"
            assert params is not None and set(params) == {"from", "to"}
            return [run] if params["from"] == "2026-07-14T12:00:00Z" else []

        manager = _FakeResumableManager()
        rows, client = _run_endpoint(
            "job_runs",
            handler,
            manager,
            monkeypatch,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-15T12:00:00Z",
        )

        # Watermark minus the 24h lookback => one 24h window [07-14T12, 07-15T12].
        assert [p for _, p in client.calls] == [{"from": "2026-07-14T12:00:00Z", "to": "2026-07-15T12:00:00Z"}]
        assert rows == [run]
        # State advances to the window end AFTER the batch was consumed, so a crash re-fetches the
        # in-flight window instead of skipping it.
        assert [s.window_from for s in manager.saved] == ["2026-07-15T12:00:00Z"]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_resume_restarts_from_the_saved_window(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"))
        _, client = _run_endpoint("job_runs", lambda path, params: [], manager, monkeypatch)
        assert [p for _, p in client.calls] == [{"from": "2026-07-15T00:00:00Z", "to": "2026-07-15T12:00:00Z"}]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_full_window_logs_a_truncation_warning(self, monkeypatch: Any) -> None:
        # The API silently caps a window at 10k rows; without the warning a truncated sync looks complete.
        logger = MagicMock()
        client = _FakeClient(lambda path, params: [{"runId": f"r{i}"} for i in range(10_000)])
        monkeypatch.setattr(snowplow, "SnowplowClient", lambda *a, **k: client)
        list(
            get_rows(
                organization_id="org-1",
                api_key_id="key-id",
                api_key="key",
                endpoint="job_runs",
                logger=logger,
                resumable_source_manager=_FakeResumableManager(
                    SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z")
                ),  # type: ignore[arg-type]
            )
        )
        assert logger.warning.called


class TestJobRunSteps:
    @freeze_time("2026-07-15T12:00:00Z")
    def test_steps_carry_parent_run_fields(self, monkeypatch: Any) -> None:
        # Step names are unique only within a run; the injected runId is what makes the composite
        # primary key unique table-wide, and runStartTime is the advertised incremental field.
        run = {
            "runId": "r1",
            "jobId": "j1",
            "jobName": "webmodel",
            "environment": "com.acme-prod1",
            "state": "SUCCEEDED",
            "startTime": "2026-07-15T00:10:00Z",
        }

        def handler(path: str, params: dict | None) -> Any:
            if path == "/jobs/v1/runs":
                return [run]
            assert path == "/jobs/v1/runs/r1/steps"
            return [{"name": "run-page-views", "state": "SUCCEEDED", "dependencies": ["other"], "duration": "PT1M"}]

        manager = _FakeResumableManager(SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"))
        rows, _ = _run_endpoint("job_run_steps", handler, manager, monkeypatch)
        assert rows == [
            {
                "name": "run-page-views",
                "state": "SUCCEEDED",
                "dependencies": ["other"],
                "duration": "PT1M",
                "runId": "r1",
                "jobId": "j1",
                "jobName": "webmodel",
                "environment": "com.acme-prod1",
                "runStartTime": "2026-07-15T00:10:00Z",
            }
        ]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_run_that_404s_is_skipped(self, monkeypatch: Any) -> None:
        # A run that aged out of retention between the window listing and the steps fetch must not
        # fail the whole sync.
        not_found = requests.Response()
        not_found.status_code = 404

        def handler(path: str, params: dict | None) -> Any:
            if path == "/jobs/v1/runs":
                return [
                    {"runId": "gone", "startTime": "2026-07-15T00:10:00Z"},
                    {"runId": "r2", "startTime": "2026-07-15T00:20:00Z"},
                ]
            if path == "/jobs/v1/runs/gone/steps":
                raise requests.HTTPError(response=not_found)
            return [{"name": "step", "state": "SUCCEEDED"}]

        manager = _FakeResumableManager(SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"))
        rows, _ = _run_endpoint("job_run_steps", handler, manager, monkeypatch)
        assert [r["runId"] for r in rows] == ["r2"]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_run_without_run_id_is_skipped(self, monkeypatch: Any) -> None:
        # runId is part of the (runId, name) primary key; a null-keyed row would collapse steps
        # from every such run into one persisted row.
        def handler(path: str, params: dict | None) -> Any:
            if path == "/jobs/v1/runs":
                return [{"state": "SUCCEEDED"}, {"runId": "r1", "startTime": "2026-07-15T00:10:00Z"}]
            return [{"name": "step", "state": "SUCCEEDED"}]

        manager = _FakeResumableManager(SnowplowResumeConfig(window_from="2026-07-15T00:00:00Z"))
        rows, client = _run_endpoint("job_run_steps", handler, manager, monkeypatch)
        assert [r["runId"] for r in rows] == ["r1"]
        assert ("/jobs/v1/runs/r1/steps", None) in client.calls


class TestFlattenFailedEventAggregates:
    def test_flattens_one_row_per_error_and_window(self) -> None:
        aggregates = [
            {
                "errorId": "e1",
                "schemaKey": "iglu:com.acme/checkout/jsonschema/1-0-0",
                "classification": "Validation",
                "metrics": [
                    {"window": "2026-07-14T00:00:00Z", "count": 12, "lastSeen": "2026-07-14T18:00:00Z"},
                    {"window": "2026-07-15T00:00:00Z", "count": 3, "lastSeen": "2026-07-15T09:00:00Z"},
                ],
            }
        ]
        rows = _flatten_failed_event_aggregates("p1", aggregates, MagicMock())
        assert rows == [
            {
                "pipelineId": "p1",
                "errorId": "e1",
                "schemaKey": "iglu:com.acme/checkout/jsonschema/1-0-0",
                "classification": "Validation",
                "window": "2026-07-14T00:00:00Z",
                "count": 12,
                "lastSeen": "2026-07-14T18:00:00Z",
            },
            {
                "pipelineId": "p1",
                "errorId": "e1",
                "schemaKey": "iglu:com.acme/checkout/jsonschema/1-0-0",
                "classification": "Validation",
                "window": "2026-07-15T00:00:00Z",
                "count": 3,
                "lastSeen": "2026-07-15T09:00:00Z",
            },
        ]

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
    def _handler(self, path: str, params: dict | None) -> Any:
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

    @freeze_time("2026-07-15T12:00:00Z")
    def test_fans_out_over_pipelines_with_incremental_window(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, client = _run_endpoint(
            "failed_event_metrics",
            self._handler,
            manager,
            monkeypatch,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-15T00:00:00Z",
        )
        expected_params = {"from": "2026-07-14T00:00:00Z", "to": "2026-07-15T12:00:00Z"}
        assert client.calls[0] == ("/pipelines/v1", None)
        assert client.calls[1:] == [
            ("/metrics/v1/pipelines/p1/failed-events", expected_params),
            ("/metrics/v1/pipelines/p2/failed-events", expected_params),
        ]
        assert [r["pipelineId"] for r in rows] == ["p1", "p2"]
        # Completed pipelines accumulate AFTER each pipeline's rows are consumed, so a crash
        # mid-pipeline re-processes it (merge dedupes) rather than skipping it.
        assert [s.completed_pipeline_ids for s in manager.saved] == [["p1"], ["p1", "p2"]]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_resume_skips_completed_pipelines(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SnowplowResumeConfig(completed_pipeline_ids=["p1"]))
        rows, client = _run_endpoint("failed_event_metrics", self._handler, manager, monkeypatch)
        assert [r["pipelineId"] for r in rows] == ["p2"]
        assert ("/metrics/v1/pipelines/p1/failed-events", None) not in [(p, None) for p, _ in client.calls[1:]]


class TestListEndpoints:
    def test_pipelines_unwraps_the_wrapper_object(self, monkeypatch: Any) -> None:
        pipelines = [{"id": "p1", "name": "prod"}]
        rows, _ = _run_endpoint(
            "pipelines", lambda path, params: {"pipelines": pipelines}, _FakeResumableManager(), monkeypatch
        )
        assert rows == pipelines

    def test_users_yields_the_bare_array(self, monkeypatch: Any) -> None:
        users = [{"id": "u1", "email": "a@b.co"}]
        rows, _ = _run_endpoint("users", lambda path, params: users, _FakeResumableManager(), monkeypatch)
        assert rows == users

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
    def test_data_structures_pagination_terminates(
        self, page_sizes: list[int], expected_calls: int, monkeypatch: Any
    ) -> None:
        pages = [[{"hash": f"h{p}-{i}"} for i in range(size)] for p, size in enumerate(page_sizes)]

        def handler(path: str, params: dict | None) -> Any:
            offset = (params or {})["from"]
            index = offset // 100
            return pages[index] if index < len(pages) else []

        rows, client = _run_endpoint("data_structures", handler, _FakeResumableManager(), monkeypatch)
        assert len(client.calls) == expected_calls
        assert len(rows) == sum(page_sizes)


class TestClientAuth:
    def _session(self, responses: list[MagicMock]) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = responses
        return session

    def _token_response(self, token: str = "jwt-1") -> MagicMock:
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = {"accessToken": token}
        return response

    def _data_response(self, payload: Any) -> MagicMock:
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = payload
        return response

    def test_token_is_minted_once_and_reused(self) -> None:
        session = self._session([self._token_response(), self._data_response([1]), self._data_response([2])])
        with patch.object(snowplow, "make_tracked_session", return_value=session) as mock_session_factory:
            client = SnowplowClient("org-1", "key-id", "key", MagicMock())
            assert client.get("/users") == [1]
            assert client.get("/users") == [2]
        # The session must never follow redirects: the token exchange carries the admin-capable API
        # key in custom X-API-Key headers, which requests would replay to a redirect target.
        assert mock_session_factory.call_args.kwargs["allow_redirects"] is False
        # Exactly one token mint for two data calls; re-minting per request would double API traffic
        # and hammer the credentials endpoint.
        token_calls = [c for c in session.get.call_args_list if "credentials/v3/token" in c.args[0]]
        assert len(token_calls) == 1
        data_call = next(c for c in session.get.call_args_list if "credentials" not in c.args[0])
        assert data_call.kwargs["headers"]["Authorization"] == "Bearer jwt-1"

    def test_expired_token_is_reminted_once_mid_sync(self) -> None:
        # The JWT is only valid ~24h; a long sync must recover from a 401 by re-minting instead of
        # failing the job.
        expired = MagicMock(status_code=401, ok=False)
        session = self._session(
            [self._token_response("jwt-1"), expired, self._token_response("jwt-2"), self._data_response([1])]
        )
        with patch.object(snowplow, "make_tracked_session", return_value=session):
            client = SnowplowClient("org-1", "key-id", "key", MagicMock())
            assert client.get("/users") == [1]
        last_data_call = session.get.call_args_list[-1]
        assert last_data_call.kwargs["headers"]["Authorization"] == "Bearer jwt-2"

    def test_persistent_401_raises(self) -> None:
        unauthorized = requests.Response()
        unauthorized.status_code = 401

        def raise_401() -> None:
            raise requests.HTTPError(
                "401 Client Error: Unauthorized for url: https://console.snowplowanalytics.com",
                response=unauthorized,
            )

        expired = MagicMock(status_code=401, ok=False)
        expired.raise_for_status.side_effect = raise_401
        session = self._session([self._token_response("jwt-1"), expired, self._token_response("jwt-2"), expired])
        with patch.object(snowplow, "make_tracked_session", return_value=session):
            client = SnowplowClient("org-1", "key-id", "key", MagicMock())
            with pytest.raises(requests.HTTPError):
                client.get("/users")

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("org_not_found", 404)])
    def test_mint_token_raises_auth_error(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False)
        session = self._session([response])
        with patch.object(snowplow, "make_tracked_session", return_value=session):
            client = SnowplowClient("org-1", "key-id", "key", MagicMock())
            with pytest.raises(SnowplowAuthError):
                client._mint_token()

    def test_retryable_status_is_retried(self) -> None:
        bad = MagicMock(status_code=503, ok=False)
        session = self._session([self._token_response(), bad, self._data_response([1])])
        with (
            patch.object(snowplow, "make_tracked_session", return_value=session),
            patch.object(SnowplowClient._request.retry, "sleep", lambda *_: None),  # type: ignore[attr-defined]
        ):
            client = SnowplowClient("org-1", "key-id", "key", MagicMock())
            assert client.get("/users") == [1]
        assert session.get.call_count == 3


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with patch.object(SnowplowClient, "_mint_token", return_value="jwt"):
            assert validate_credentials("org-1", "key-id", "key", MagicMock()) == (True, None)

    def test_auth_error_surfaces_its_message(self) -> None:
        with patch.object(SnowplowClient, "_mint_token", side_effect=SnowplowAuthError("bad key")):
            ok, error = validate_credentials("org-1", "key-id", "key", MagicMock())
        assert ok is False
        assert error == "bad key"

    def test_network_error_is_invalid_with_generic_message(self) -> None:
        with patch.object(SnowplowClient, "_mint_token", side_effect=requests.ConnectionError("boom")):
            ok, error = validate_credentials("org-1", "key-id", "key", MagicMock())
        assert ok is False
        assert error is not None


class TestSourceResponse:
    @parameterized.expand(
        [
            ("pipelines", "asc", None, ["id"]),
            ("users", "asc", None, ["id"]),
            ("data_models", "asc", None, ["name"]),
            ("data_structures", "asc", None, ["hash"]),
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
        response = snowplow_source(
            organization_id="org-1",
            api_key_id="key-id",
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == SNOWPLOW_ENDPOINTS[endpoint].primary_keys == primary_keys
