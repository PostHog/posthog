import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mux import mux
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import (
    INCREMENTAL_OVERLAP,
    MuxResumeConfig,
    _as_epoch,
    _normalize_row,
    _strip_sensitive_fields,
    get_validation_status,
    mux_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    AGGREGATE_LOOKBACK,
    DIMENSION_VALUES_MAX_PAGES,
    MUX_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between retries — patch its clock so retry paths don't actually block.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: dict[str, Any] | None, status: int = 200, *, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = "https://api.mux.com/video/v1/list"
    resp._content = json.dumps(body if body is not None else {}).encode()
    return resp


def _make_manager(resume_state: MuxResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict[str, Any]]:
    response = mux_source(
        access_token_id="id",
        secret_key="secret",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestNormalizeRow:
    @parameterized.expand(
        [
            ("digit_string_to_int", "assets", {"id": "a", "created_at": "1609869152"}, 1609869152),
            ("already_int_unchanged", "assets", {"id": "a", "created_at": 1609869152}, 1609869152),
            ("non_digit_string_unchanged", "assets", {"id": "a", "created_at": "not-a-ts"}, "not-a-ts"),
        ]
    )
    def test_created_at_coercion(self, _name: str, endpoint: str, item: dict, expected: Any) -> None:
        result = _normalize_row(item, MUX_ENDPOINTS[endpoint])
        assert result["created_at"] == expected


class TestStripSensitiveFields:
    def test_live_stream_simulcast_target_stream_keys_are_dropped(self) -> None:
        item = {
            "id": "ls1",
            "simulcast_targets": [
                {"id": "t1", "url": "rtmp://example", "stream_key": "secret", "status": "idle"},
            ],
        }
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["live_streams"])
        assert cleaned["simulcast_targets"] == [{"id": "t1", "url": "rtmp://example", "status": "idle"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_never_yields_stripped_fields(self, MockSession) -> None:
        # End-to-end guard: a secret in the API response must not survive into batched rows, and
        # created_at is still coerced to int.
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "ls1", "created_at": "1609869152", "stream_key": "leak"}]})])

        rows = _run("live_streams", _make_manager())
        assert rows == [{"id": "ls1", "created_at": 1609869152}]
        assert all("stream_key" not in row for row in rows)


class TestGetValidationStatus:
    def test_returns_status_code(self, monkeypatch: Any) -> None:
        for status_code in (200, 401, 403):
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=status_code)
            monkeypatch.setattr(mux, "_make_session", lambda *a, _s=session, **k: _s)
            assert get_validation_status("id", "secret", "/video/v1/assets") == status_code


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_final_page_triggers_one_more_empty_fetch(self, MockSession) -> None:
        # An exact-multiple final page can't be distinguished from a full page, so we fetch once more.
        session = MockSession.return_value
        full_page = [{"id": str(i), "created_at": "1609869152"} for i in range(100)]
        _wire(session, [_response({"data": full_page}), _response({"data": []})])

        manager = _make_manager()
        rows = _run("live_streams", manager)

        assert len(rows) == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "x", "created_at": "1609869152"}]})])

        manager = _make_manager(MuxResumeConfig(page=3))
        rows = _run("live_streams", manager)

        assert rows == [{"id": "x", "created_at": 1609869152}]
        assert params[0]["page"] == 3
        assert session.send.call_count == 1


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_assets_walk_via_next_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"data": [{"id": "a1", "created_at": "1609869152"}], "next_cursor": "CURSOR2"}),
                _response({"data": [{"id": "a2", "created_at": "1609869152"}], "next_cursor": None}),
            ],
        )

        manager = _make_manager()
        rows = _run("assets", manager)

        assert [r["id"] for r in rows] == ["a1", "a2"]
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "CURSOR2"
        manager.save_state.assert_called_once_with(MuxResumeConfig(cursor="CURSOR2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_assets_resume_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "a9", "created_at": "1609869152"}], "next_cursor": None})])

        manager = _make_manager(MuxResumeConfig(cursor="SAVED"))
        rows = _run("assets", manager)

        assert [r["id"] for r in rows] == ["a9"]
        assert params[0]["cursor"] == "SAVED"


class TestRetryableErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, status=status_code, reason="err"),
                _response({"data": [{"id": "ok", "created_at": "1609869152"}]}),
            ],
        )

        rows = _run("live_streams", _make_manager())

        assert [r["id"] for r in rows] == ["ok"]
        assert session.send.call_count == 2

    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_eventually_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock(url=request.url)
        session.send.return_value = _response(None, status=500, reason="err")

        with pytest.raises(Exception):
            _run("live_streams", _make_manager())
        # Default of 5 attempts, no early success.
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, MockSession) -> None:
        # A 403 (missing scope) is a permanent client error — raised on the first response, not retried.
        session = MockSession.return_value
        _wire(session, [_response(None, status=403, reason="Forbidden")])

        with pytest.raises(requests.HTTPError):
            _run("live_streams", _make_manager())
        assert session.send.call_count == 1


class TestAsEpoch:
    def test_naive_datetime_treated_as_utc(self) -> None:
        # Mux `view_end` values are UTC; a tz-naive watermark must not shift by the local offset.
        assert _as_epoch(datetime(2023, 1, 1)) == 1672531200


class TestTimeframeParams:
    def test_aggregate_lookback_stays_within_standard_retention(self) -> None:
        # A window past the account's retention is rejected with `400 invalid_timeframe`, not clamped.
        # Mux's standard retention floor is 100 days, so the aggregate lookback must not exceed it —
        # this guards against widening it back toward the 13-month add-on window every plan doesn't have.
        assert AGGREGATE_LOOKBACK <= timedelta(days=100)


class TestMuxDataEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_video_views_incremental_windows_from_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "v1", "view_end": "2023-02-01T00:00:00Z"}]})])

        rows = _run(
            "video_views",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-01-01T00:00:00Z",
        )

        assert [r["id"] for r in rows] == ["v1"]
        start, _end = params[0]["timeframe[]"]
        assert start == 1672531200 - int(INCREMENTAL_OVERLAP.total_seconds())
        # Oldest-first so the asc watermark advances safely, and page pagination still applies.
        assert params[0]["order_direction"] == "asc"
        assert params[0]["limit"] == 100
        assert params[0]["page"] == 1

    @parameterized.expand([("errors",), ("metrics_comparison",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_response_endpoints_fetch_once_with_timeframe(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": 1, "code": 500}]})])

        rows = _run(endpoint, _make_manager())

        assert len(rows) == 1
        # Single-page paginator: exactly one request, no page/limit walking.
        assert session.send.call_count == 1
        assert "timeframe[]" in params[0]
        assert "page" not in params[0]


def _wire_urls(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    session.headers = {}
    requests_sent: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        requests_sent.append((request.url, dict(request.params or {})))
        return mock.MagicMock(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return requests_sent


class TestMuxDataFanOut:
    @mock.patch.object(mux, "DATA_METRICS", ("views", "rebuffer_percentage"))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metric_timeseries_explodes_points_per_metric(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire_urls(
            session,
            [
                _response(
                    {
                        "data": [["2024-01-01T00:00:00Z", "10", "10"], ["2024-01-02T00:00:00Z", 12, None]],
                        "meta": {"granularity": "day", "aggregation": "view_end"},
                    }
                ),
                _response({"data": [["2024-01-01T00:00:00Z", "0.25", "40"]], "meta": {"granularity": "day"}}),
            ],
        )

        rows = _run("metric_timeseries", _make_manager())

        assert [url for url, _ in sent] == [
            "https://api.mux.com/data/v1/metrics/views/timeseries",
            "https://api.mux.com/data/v1/metrics/rebuffer_percentage/timeseries",
        ]
        assert sent[0][1]["group_by"] == "day"
        assert "timeframe[]" in sent[0][1]
        assert rows == [
            {
                "metric": "views",
                "interval_start": "2024-01-01T00:00:00Z",
                "value": 10.0,
                "views": 10,
                "granularity": "day",
                "aggregation": "view_end",
            },
            {
                "metric": "views",
                "interval_start": "2024-01-02T00:00:00Z",
                "value": 12.0,
                "views": None,
                "granularity": "day",
                "aggregation": "view_end",
            },
            {
                "metric": "rebuffer_percentage",
                "interval_start": "2024-01-01T00:00:00Z",
                "value": 0.25,
                "views": 40,
                "granularity": "day",
                "aggregation": None,
            },
        ]

    @mock.patch.object(mux, "DATA_METRICS", ("views",))
    @mock.patch.object(mux, "BREAKDOWN_DIMENSIONS", ("country", "cdn"))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metric_breakdowns_walk_pages_per_metric_and_dimension(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"field": f"c{i}", "value": 1, "views": 1} for i in range(100)]
        sent = _wire_urls(
            session,
            [
                _response({"data": full_page}),
                _response({"data": [{"field": "US", "value": 2, "views": 5}]}),
                _response({"data": [{"field": "fastly", "value": 3, "views": 7}]}),
            ],
        )

        rows = _run("metric_breakdowns", _make_manager())

        assert [(url, params["page"]) for url, params in sent] == [
            ("https://api.mux.com/data/v1/metrics/views/breakdown?group_by=country", 1),
            ("https://api.mux.com/data/v1/metrics/views/breakdown?group_by=country", 2),
            ("https://api.mux.com/data/v1/metrics/views/breakdown?group_by=cdn", 1),
        ]
        assert sent[0][1]["order_by"] == "field"
        assert len(rows) == 102
        assert rows[100] == {"field": "US", "value": 2, "views": 5, "metric": "views", "dimension": "country"}
        assert rows[101] == {"field": "fastly", "value": 3, "views": 7, "metric": "views", "dimension": "cdn"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dimension_values_fan_out_routes_trace_dimensions_to_elements(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire_urls(
            session,
            [
                _response({"data": {"basic": ["country"], "advanced": ["country", "video_cdn_trace"]}}),
                _response({"data": [{"value": "US", "total_count": 9}]}),
                _response({"data": [{"value": "fastly", "total_count": 4}]}),
            ],
        )

        rows = _run("dimension_values", _make_manager())

        assert [url for url, _ in sent] == [
            "https://api.mux.com/data/v1/dimensions",
            "https://api.mux.com/data/v1/dimensions/country",
            "https://api.mux.com/data/v1/dimensions/video_cdn_trace/elements",
        ]
        assert rows == [
            {"value": "US", "total_count": 9, "dimension": "country"},
            {"value": "fastly", "total_count": 4, "dimension": "video_cdn_trace"},
        ]

    def test_dimension_parent_rows_percent_encode_names_from_the_response(self) -> None:
        rows = mux._dimension_parent_rows(
            {"basic": ["https://attacker.example/x", "//attacker.example/x"], "advanced": ["video_cdn_trace"]}
        )

        assert [row["values_path"] for row in rows] == [
            "https%3A%2F%2Fattacker.example%2Fx",
            "%2F%2Fattacker.example%2Fx",
            "video_cdn_trace/elements",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dimension_values_stop_at_page_cap(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = {"data": [{"value": str(i), "total_count": 1} for i in range(100)]}
        _wire_urls(
            session,
            [_response({"data": {"basic": ["view_session_id"], "advanced": []}})]
            + [_response(full_page) for _ in range(DIMENSION_VALUES_MAX_PAGES + 1)],
        )

        rows = _run("dimension_values", _make_manager())

        assert len(rows) == DIMENSION_VALUES_MAX_PAGES * 100
        assert session.send.call_count == DIMENSION_VALUES_MAX_PAGES + 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dimensions_flatten_tiers(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_urls(session, [_response({"data": {"basic": ["browser", "country"], "advanced": ["country", "asn"]}})])

        rows = _run("dimensions", _make_manager())

        assert rows == [
            {"name": "browser", "tier": "basic"},
            {"name": "country", "tier": "basic"},
            {"name": "asn", "tier": "advanced"},
        ]

    @mock.patch.object(mux, "DATA_METRICS", ("views", "rebuffer_percentage"))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_resumes_past_completed_metrics(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire_urls(session, [_response({"data": [["2024-01-01T00:00:00Z", "0.5", "2"]]})])
        manager = _make_manager(
            MuxResumeConfig(
                fan_out={"completed": ["/data/v1/metrics/views/timeseries"], "current": None, "child_state": None}
            )
        )

        rows = _run("metric_timeseries", manager)

        assert [url for url, _ in sent] == ["https://api.mux.com/data/v1/metrics/rebuffer_percentage/timeseries"]
        assert [row["metric"] for row in rows] == ["rebuffer_percentage"]
        saved = manager.save_state.call_args.args[0]
        assert saved.fan_out["completed"] == [
            "/data/v1/metrics/rebuffer_percentage/timeseries",
            "/data/v1/metrics/views/timeseries",
        ]
