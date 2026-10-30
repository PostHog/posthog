from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal import (
    AGGREGATE_BUCKET_SECONDS,
    AppsignalResumeConfig,
    AppsignalRetryableError,
    _fetch_v2,
    _parse_iso,
    _to_epoch,
    _to_iso,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    APPSIGNAL_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source import AppsignalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsignal import (
    AppsignalSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal"
_LOG_SOURCES = {"data": {"app": {"logs": {"sources": [{"id": "src-1"}]}}}}


def _driver(api_token: str = "token") -> SourceDriver:
    return SourceDriver(AppsignalSource(), AppsignalSourceConfig(api_token=api_token, app_id="app-id"))


def _graphql_page(field: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"app": {field: rows}}})


def _v2_script(
    *,
    graphql: Any = None,
    post: dict[str, Any] | None = None,
    get: dict[str, Any] | None = None,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    post_handlers, get_handlers = post or {}, get or {}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/graphql":
            payload = graphql(request.json()) if callable(graphql) else graphql
            return ScriptedResponse(json=payload or {})
        path = request.path.removeprefix("/api/v2")
        handlers = post_handlers if request.method == "POST" else get_handlers
        if path not in handlers:
            raise UnexpectedRequest(f"unexpected {request.method} {request.path}")
        handler = handlers[path]
        payload = handler(request.json()) if callable(handler) else handler
        if isinstance(payload, int):
            return ScriptedResponse(status=payload, json={"error": "Not found"})
        return ScriptedResponse(json=payload)

    return respond


def _windowed_script(
    rows: list[dict[str, Any]], cursor: str = "time", data_key: str = "log_entries"
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        since = int(request.param("since") or request.param("from") or 0)
        before = int(request.param("before") or request.param("to") or 2**62)
        matching = [row for row in rows if since <= (_to_epoch(row[cursor]) or 0) <= before]
        if request.param("count_only"):
            return ScriptedResponse(json={"count": len(matching)})
        matching.sort(key=lambda row: _to_epoch(row[cursor]) or 0, reverse=True)
        return ScriptedResponse(json={data_key: matching[: int(request.param("limit") or 0)]})

    return respond


def _log_lines_script(lines: list[dict[str, Any]]) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    def respond(body: dict[str, Any]) -> list[dict[str, Any]]:
        cursor = _parse_iso(body["pagination"]["cursor"]["time"])
        matching = [line for line in lines if cursor is None or (_parse_iso(line["timestamp"]) or cursor) >= cursor]
        return matching[: body["pagination"]["per_page"]]

    return respond


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-date", None),
        ],
    )
    def test_to_epoch_values(self, value: Any, expected: int | None) -> None:
        assert _to_epoch(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(404, False)])
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            assert validate_credentials("token", "app-id") is expected
        assert network.requests_log[0].path == "/api/app-id/markers.json"
        assert network.requests_log[0].param("count_only") == "true"


class TestWindowedRows:
    @mock.patch(f"{MODULE}.WINDOW_PAGE_LIMIT", 2)
    def test_over_limit_narrow_window_is_fetched_not_split_forever(self) -> None:
        # More rows than the page limit inside a span narrower than 2 * MIN_WINDOW_SECONDS.
        # Bisection can't shrink such a window (the right child's `mid - 1` overlap makes it equal
        # to its parent), so it must be fetched directly rather than split endlessly.
        base = int(datetime.now(UTC).timestamp()) - 10
        rows = [{"id": str(offset), "time": base + offset} for offset in range(3)]
        result = _driver().run(
            "error_samples", _windowed_script(rows), resume_state=AppsignalResumeConfig(window_start=base)
        )

        assert result.raised is None
        assert {row["id"] for row in result.rows} == {"0", "1", "2"}
        assert len(result.requests) <= 100

    def test_auth_failure_error_message_does_not_leak_token(self) -> None:
        secret = "super-secret-token-value"
        result = _driver(secret).run("error_samples", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert secret not in str(result.raised)
        assert str(result.raised).startswith("401 Client Error: Unauthorized for url: https://appsignal.com")

    def test_transport_error_message_does_not_leak_token(self) -> None:
        # requests raises ConnectionError before any response exists, with the full request URL —
        # token included — in its message. That path is not covered by the status-error scrubbing.
        secret = "super-secret-token-value"
        error = requests.ConnectionError(f"connection failed for /api/app-id/samples/errors.json?token={secret}")
        result = _driver(secret).run("error_samples", always(error))

        assert isinstance(result.raised, AppsignalRetryableError)
        assert secret not in str(result.raised)
        assert set(result.paths) == {"/api/app-id/samples/errors.json"}


class TestIncidentRows:
    @mock.patch(f"{MODULE}.GRAPHQL_PAGE_SIZE", 2)
    def test_pages_by_offset_until_short_page(self) -> None:
        result = _driver().run(
            "exception_incidents",
            [
                _graphql_page("exceptionIncidents", [{"id": "1"}, {"id": "2"}]),
                _graphql_page("exceptionIncidents", [{"id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert [request.json()["variables"]["offset"] for request in result.requests] == [0, 2]
        # State saved only after the full first page — the short page ends the walk.
        assert result.saved_states == [AppsignalResumeConfig(offset=2)]

    @mock.patch(f"{MODULE}.GRAPHQL_PAGE_SIZE", 2)
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "performance_incidents",
            [_graphql_page("performanceIncidents", [{"id": "5"}])],
            resume_state=AppsignalResumeConfig(offset=4),
        )

        assert result.raised is None
        assert result.requests[0].json()["variables"]["offset"] == 4
        assert result.requests[0].json()["variables"]["appId"] == "app-id"

    def test_missing_app_raises_clear_error(self) -> None:
        result = _driver().run("exception_incidents", [ScriptedResponse(json={"data": {"app": None}})])
        assert result.raised is not None
        assert "AppSignal app not found" in str(result.raised)

    def test_graphql_errors_raise(self) -> None:
        result = _driver().run(
            "exception_incidents", [ScriptedResponse(json={"errors": [{"message": "Field 'nope' doesn't exist"}]})]
        )
        assert result.raised is not None
        assert "Field 'nope' doesn't exist" in str(result.raised)

    def test_transport_error_message_does_not_leak_token(self) -> None:
        secret = "super-secret-token-value"
        result = _driver(secret).run(
            "exception_incidents", always(requests.ConnectionError(f"failed /graphql?token={secret}"))
        )

        assert isinstance(result.raised, AppsignalRetryableError)
        assert secret not in str(result.raised)
        assert set(result.paths) == {"/graphql"}

    def test_log_incidents_query_omits_the_invalid_severities_field(self) -> None:
        # AppSignal's `LogLineActionTrigger` type has no `severities` field (only id, name,
        # description, query, sourceIds, actionType, ...). Requesting it makes AppSignal's
        # GraphQL server reject the whole query with a 400, failing every log_incidents sync.
        result = _driver().run("log_incidents", [_graphql_page("logIncidents", [])])

        assert result.raised is None
        assert "severities" not in result.requests[0].json()["query"]


class TestAppsignalSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = APPSIGNAL_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None


class TestFetchV2:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_transient_statuses_are_retryable(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.post.return_value = mock.MagicMock(status_code=status_code)

        with (
            mock.patch.object(_fetch_v2.retry, "sleep", lambda _: None),  # type: ignore[attr-defined]
            pytest.raises(AppsignalRetryableError),
        ):
            _fetch_v2(session, "token", "/logs/lines", mock.MagicMock(), body={})

    @pytest.mark.parametrize("status_code", [401, 403, 404, 422])
    def test_client_statuses_are_terminal(self, status_code: int) -> None:
        session = mock.MagicMock()
        response = mock.MagicMock(status_code=status_code, ok=False, url="https://appsignal.com/api/v2/logs/lines")
        response.reason = "Error"
        session.post.return_value = response

        with pytest.raises(requests.HTTPError):
            _fetch_v2(session, "token", "/logs/lines", mock.MagicMock(), body={})


class TestAppRows:
    def test_apps_carry_their_organization(self) -> None:
        # Only the configured app's organization: a personal token often reaches several, and
        # syncing those would expose apps this connection never named.
        result = _driver().run(
            "apps",
            [
                ScriptedResponse(
                    json={
                        "data": {
                            "app": {
                                "organization": {
                                    "id": "org-1",
                                    "name": "Acme",
                                    "slug": "acme",
                                    "apps": [{"id": "a1", "name": "web"}, {"id": "a2", "name": "api"}],
                                }
                            }
                        }
                    }
                )
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["organizationSlug"]) for row in result.items[0]] == [("a1", "acme"), ("a2", "acme")]
        assert result.requests[0].json()["variables"] == {"appId": "app-id"}

    def test_missing_app_raises_clear_error(self) -> None:
        result = _driver().run("apps", [ScriptedResponse(json={"data": {"app": None}})])
        assert result.raised is not None
        assert "AppSignal app not found" in str(result.raised)


class TestLogLineRows:
    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    def test_boundary_line_is_not_yielded_twice(self) -> None:
        # The cursor is the last line's timestamp and the endpoint is inclusive of it, so the
        # next page re-serves that line. Without the boundary filter it lands in the table twice.
        lines = [{"id": str(n), "timestamp": f"2026-01-0{n}T00:00:00Z"} for n in (1, 2, 3)]
        result = _driver().run(
            "log_lines", _v2_script(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_script(lines)})
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]

    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    def test_full_page_on_one_instant_steps_past_it_instead_of_looping(self) -> None:
        # Every line shares a timestamp, so the keyset cursor cannot advance on its own and the
        # walk would re-request the same page forever.
        lines = [{"id": str(n), "timestamp": "2026-01-01T00:00:00Z"} for n in (1, 2, 3)]
        logger = mock.MagicMock()
        result = _driver().run(
            "log_lines", _v2_script(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_script(lines)}), logger=logger
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert "share timestamp" in logger.warning.call_args.args[0]

    @pytest.mark.parametrize(
        "should_use_incremental_field, watermark, expected_cursor",
        [(False, "2026-01-02T00:00:00Z", None), (True, "2026-01-02T00:00:00Z", "2026-01-01T23:59:59Z")],
    )
    def test_first_page_cursor_follows_the_watermark(
        self, should_use_incremental_field: bool, watermark: str, expected_cursor: str | None
    ) -> None:
        result = _driver().run(
            "log_lines",
            _v2_script(graphql=_LOG_SOURCES, post={"/logs/lines": []}),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        body = result.requests[-1].json()
        assert body["pagination"]["cursor"] == {"time": expected_cursor}
        assert body["source_ids"] == ["src-1"]

    def test_app_without_log_sources_makes_no_query(self) -> None:
        result = _driver().run("log_lines", [ScriptedResponse(json={"data": {"app": {"logs": {"sources": []}}}})])
        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/graphql"]

    def test_resumes_from_saved_cursor(self) -> None:
        lines = [{"id": "late", "timestamp": "2026-01-05T00:00:00Z"}]
        result = _driver().run(
            "log_lines",
            _v2_script(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_script(lines)}),
            resume_state=AppsignalResumeConfig(cursor_time="2026-01-04T00:00:00Z"),
        )

        assert result.raised is None
        assert result.requests[1].json()["pagination"]["cursor"] == {"time": "2026-01-04T00:00:00Z"}


class TestMetricRows:
    _NAMES_PATH = "/metrics/names/app-id"

    def test_metric_without_type_does_not_abort_the_catalog(self) -> None:
        # type_and_tags 404s when a metric stops reporting between the two calls; the rest of
        # the catalog must still sync.
        result = _driver().run(
            "metric_names",
            _v2_script(
                get={
                    self._NAMES_PATH: ["cpu", "gone"],
                    "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": [["hostname"]]},
                    "/metrics/type_and_tags/app-id/gone": 404,
                }
            ),
        )

        assert result.raised is None
        assert result.items[0] == [
            {"name": "cpu", "metric_type": "gauge", "available_tags": [["hostname"]]},
            {"name": "gone", "metric_type": None, "available_tags": []},
        ]

    @mock.patch(f"{MODULE}.METRICS_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_timeseries_selectors_use_the_field_for_the_metric_type(self) -> None:
        result = _driver().run(
            "metric_timeseries",
            _v2_script(
                get={
                    self._NAMES_PATH: ["cpu", "requests", "latency", "unknown"],
                    "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": [["hostname"]]},
                    "/metrics/type_and_tags/app-id/requests": {"metric_type": "counter", "available_tags": []},
                    "/metrics/type_and_tags/app-id/latency": {
                        "metric_type": "measurement",
                        "available_tags": [{"namespace": "web"}],
                    },
                    "/metrics/type_and_tags/app-id/unknown": {"metric_type": "mystery", "available_tags": []},
                },
                post={"/metrics/timeseries": {"series": []}},
            ),
        )

        assert result.raised is None
        body = result.requests[-1].json()
        assert body["resolution"] == "HOURLY"
        assert body["select"] == [
            {"name": "cpu", "field": "gauge", "tags": {"hostname": "*"}},
            {"name": "requests", "field": "counter", "tags": {}},
            {"name": "latency", "field": "mean", "tags": {"namespace": "*"}},
        ]

    @mock.patch(f"{MODULE}.METRICS_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_series_are_flattened_into_ascending_point_rows(self) -> None:
        # Points restart at the window's start for every metric, so a batch built straight from
        # the response order is not ascending and would corrupt the asc watermark.
        result = _driver().run(
            "metric_timeseries",
            _v2_script(
                get={
                    self._NAMES_PATH: ["cpu"],
                    "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": []},
                },
                post={
                    "/metrics/timeseries": {
                        "series": [
                            {
                                "id": "cpu/host=b/gauge",
                                "name": "cpu",
                                "field": "gauge",
                                "tags": {"host": "b"},
                                "data": [{"timestamp": "2026-01-01T02:00:00Z", "value": 4.0}],
                            },
                            {
                                "id": "cpu/host=a/gauge",
                                "name": "cpu",
                                "field": "gauge",
                                "tags": {"host": "a"},
                                "data": [{"timestamp": "2026-01-01T01:00:00Z", "value": 1.0}],
                            },
                        ]
                    }
                },
            ),
        )

        assert result.raised is None
        assert [(row["series_id"], row["timestamp"], row["value"]) for row in result.items[0]] == [
            ("cpu/host=a/gauge", "2026-01-01T01:00:00Z", 1.0),
            ("cpu/host=b/gauge", "2026-01-01T02:00:00Z", 4.0),
        ]


def _traces_handler(traces: list[dict[str, Any]]) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    def respond(body: dict[str, Any]) -> list[dict[str, Any]]:
        matching = [trace for trace in traces if body["from"] <= trace["time"] <= body["to"]]
        return matching[: body["pagination"]["per_page"]]

    return respond


class TestTraceRows:
    def _traces(self, count: int) -> list[dict[str, Any]]:
        base = int(datetime.now(UTC).timestamp()) - 3000
        return [
            {"trace_id": str(offset), "site_id": "app-id", "time": _to_iso(base + offset * 100)}
            for offset in range(count)
        ]

    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_full_response_splits_the_window_until_every_trace_is_reached(self) -> None:
        # The response is capped at per_page and the cursor carries no position, so a full
        # response means truncation. Without the split the extra traces never sync.
        traces = self._traces(5)
        result = _driver().run(
            "performance_traces",
            _v2_script(
                post={
                    "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                    "/tracing/traces/performance": _traces_handler(traces),
                }
            ),
        )

        assert result.raised is None
        assert {row["trace_id"] for row in result.rows} == {"0", "1", "2", "3", "4"}
        for batch in result.items:
            assert [row["time"] for row in batch] == sorted(row["time"] for row in batch)

    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_spans_carry_the_parent_trace_time(self) -> None:
        traces = self._traces(2)
        result = _driver().run(
            "trace_spans",
            _v2_script(
                post={
                    "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                    "/tracing/traces/performance": _traces_handler(traces),
                    "/tracing/trace": lambda body: [{"span_id": f"s-{body['trace_id']}", "trace_id": body["trace_id"]}],
                }
            ),
        )

        assert result.raised is None
        assert [(row["span_id"], row["trace_time"]) for row in result.rows] == [
            ("s-0", traces[0]["time"]),
            ("s-1", traces[1]["time"]),
        ]

    @mock.patch(f"{MODULE}.MAX_SPAN_TRACES_PER_SYNC", 1)
    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_span_cap_stops_the_sweep_and_checkpoints_the_last_trace(self) -> None:
        traces = self._traces(3)
        result = _driver().run(
            "trace_spans",
            _v2_script(
                post={
                    "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                    "/tracing/traces/performance": _traces_handler(traces),
                    "/tracing/trace": lambda body: [{"span_id": f"s-{body['trace_id']}", "trace_id": body["trace_id"]}],
                }
            ),
        )

        # Traces are handled oldest-first, so stopping early leaves the rest for the next sync.
        assert result.raised is None
        assert [row["span_id"] for row in result.rows] == ["s-0"]
        assert result.saved_states[-1].window_start == _to_epoch(traces[0]["time"])


class TestPerformanceActionRows:
    @mock.patch(f"{MODULE}.AGGREGATE_INITIAL_LOOKBACK_SECONDS", 2 * 3600)
    def test_watermark_re_reads_its_own_bucket(self) -> None:
        # The newest bucket was still filling when it synced, so the watermark's bucket has to be
        # read again and merged; starting after it would freeze a partial aggregate.
        watermark = _to_iso(1_000_000 - 1_000_000 % AGGREGATE_BUCKET_SECONDS)
        with time_machine.travel(
            datetime.fromtimestamp((_to_epoch(watermark) or 0) + AGGREGATE_BUCKET_SECONDS, UTC), tick=False
        ):
            result = _driver().run(
                "performance_actions",
                _v2_script(post={"/tracing/actions": []}),
                incremental_field="timestamp",
                db_incremental_field_last_value=watermark,
            )

        assert result.raised is None
        assert result.requests[0].json()["from"] == watermark


class TestServiceEdgeRows:
    @mock.patch(f"{MODULE}.AGGREGATE_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_the_same_peer_in_two_directions_stays_two_rows(self) -> None:
        # A service both calls us and is called by us, so the group it came from is what tells the
        # two apart — collapsing them would merge the pair onto one primary key.
        result = _driver().run(
            "service_edges",
            _v2_script(
                post={
                    "/tracing/site_edges": {
                        "upstream": [{"service": "gateway", "count": 3}],
                        "downstream": [{"service": "gateway", "count": 5}],
                        "internal": [{"count": 1}],
                    }
                }
            ),
        )

        assert result.raised is None
        assert {(row["direction"], row["service"], row["count"]) for row in result.rows} == {
            ("upstream", "gateway", 3),
            ("downstream", "gateway", 5),
        }


class TestSlowEventRows:
    @pytest.mark.parametrize("status_code", [404, 422])
    @mock.patch(f"{MODULE}.SLOW_EVENT_BUCKET_SECONDS", 3600)
    @mock.patch(f"{MODULE}.SLOW_EVENT_INITIAL_LOOKBACK_SECONDS", 3600)
    def test_a_bucket_older_than_retention_is_skipped_not_fatal(self, status_code: int) -> None:
        # A bucket outside the account's tracing retention gets the same aged-out-range response
        # as /deploys/stats (see TestDeployStatsRows), not a hard failure for the whole sync.
        result = _driver().run("slow_events", _v2_script(post={"/tracing/slow_events": status_code}))

        assert result.raised is None
        assert result.rows == []

    @mock.patch(f"{MODULE}.SLOW_EVENT_BUCKET_SECONDS", 3600)
    @mock.patch(f"{MODULE}.SLOW_EVENT_INITIAL_LOOKBACK_SECONDS", 2 * 3600)
    def test_a_later_in_retention_bucket_still_yields_rows_after_a_skipped_one(self) -> None:
        # The skip must not stop the walk: an in-retention bucket after a skipped one still
        # contributes its rows, rather than the whole sync going quietly empty.
        calls: list[dict[str, Any]] = []

        def respond(body: dict[str, Any]) -> Any:
            calls.append(body)
            return 422 if len(calls) == 1 else [{"digest": "d1", "impact": 9}]

        # Pinned to a bucket boundary so the lookback produces exactly two windows.
        now = datetime.fromtimestamp(1_000_000 - 1_000_000 % 3600, UTC)
        with time_machine.travel(now, tick=False):
            result = _driver().run("slow_events", _v2_script(post={"/tracing/slow_events": respond}))

        assert result.raised is None
        assert [row["digest"] for row in result.rows] == ["d1"]
        assert len(calls) == 2

    @mock.patch(f"{MODULE}.MAX_SLOW_EVENT_DIGESTS_PER_SYNC", 1)
    @mock.patch(f"{MODULE}.SLOW_EVENT_BUCKET_SECONDS", 3600)
    @mock.patch(f"{MODULE}.SLOW_EVENT_INITIAL_LOOKBACK_SECONDS", 2 * 3600)
    def test_digest_cap_stops_between_buckets_so_the_walk_advances(self) -> None:
        # Stopping inside a bucket would leave it uncheckpointed, and a bucket holding the whole
        # budget would then be redone from the start on every sync, reaching no later bucket.
        events = [{"digest": "d1", "impact": 9}, {"digest": "d2", "impact": 2}]
        logger = mock.MagicMock()
        result = _driver().run(
            "slow_event_actions",
            _v2_script(
                post={
                    "/tracing/slow_events": events,
                    "/tracing/slow_events/actions": lambda body: [
                        {"namespace": "web", "action_name": f"action-for-{body['digest']}", "count": 1}
                    ],
                }
            ),
            logger=logger,
        )

        assert result.raised is None
        assert [row["digest"] for row in result.rows] == ["d1", "d2"]
        assert len(result.saved_states) == 1
        assert "digest limit" in logger.warning.call_args.args[0]


def _deploy_stats_script(markers: list[dict[str, Any]], stats: Any) -> Callable[[RecordedRequest], ScriptedResponse]:
    marker_response = _windowed_script(markers, cursor="created_at", data_key="markers")

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/api/app-id/markers.json":
            return marker_response(request)
        if request.path == "/api/v2/deploys/stats":
            payload = stats(request.json()["revision"]) if callable(stats) else stats
            if isinstance(payload, int):
                return ScriptedResponse(status=payload, json={"error": "Not found"})
            return ScriptedResponse(json=payload)
        raise UnexpectedRequest(f"unexpected {request.method} {request.path}")

    return respond


class TestDeployStatsRows:
    def _markers(self, revisions: list[str]) -> list[dict[str, Any]]:
        base = int(datetime.now(UTC).timestamp()) - 10_000
        return [
            {"id": f"m{offset}", "revision": revision, "created_at": _to_iso(base + offset * 10)}
            for offset, revision in enumerate(revisions)
        ]

    @pytest.mark.parametrize("status_code", [404, 422])
    def test_a_revision_without_statistics_still_yields_its_marker(self, status_code: int) -> None:
        # A deploy that served no requests, or whose data aged out of retention, has no stats to
        # report — dropping the row would lose the deploy from the table entirely.
        result = _driver().run("deploy_stats", _deploy_stats_script(self._markers(["abc123"]), status_code))

        assert result.raised is None
        assert [(row["marker_id"], row["throughput"]) for row in result.rows] == [("m0", None)]

    @mock.patch(f"{MODULE}.MAX_DEPLOY_STATS_PER_SYNC", 1)
    @mock.patch(f"{MODULE}.WINDOW_PAGE_LIMIT", 1)
    def test_revision_cap_stops_between_windows_so_the_walk_advances(self) -> None:
        # Same reason as the slow-event digest cap: a window abandoned part-way keeps no
        # checkpoint, so the next sync would redo it and never reach the windows after it.
        markers = self._markers(["r0", "r1", "r2"])
        result = _driver().run("deploy_stats", _deploy_stats_script(markers, {"throughput": 1}))

        assert result.raised is None
        assert [row["marker_id"] for row in result.rows] == ["m0"]
        assert len(result.saved_states) == 1

    def test_a_watermark_older_than_the_initial_lookback_still_wins(self) -> None:
        # The lookback only floors a first sync. Clamping an older watermark up to it would skip
        # every deploy in between when a source has been paused.
        watermark = int(datetime.now(UTC).timestamp()) - 400 * 24 * 3600
        result = _driver().run(
            "deploy_stats",
            _deploy_stats_script([], {}),
            incremental_field="created_at",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[0].param("from") == str(watermark - 1)
