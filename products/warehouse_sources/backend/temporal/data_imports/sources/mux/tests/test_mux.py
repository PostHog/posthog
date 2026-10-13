from datetime import datetime, timedelta
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mux import MuxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mux import mux
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import (
    INCREMENTAL_OVERLAP,
    MuxResumeConfig,
    _as_epoch,
    _normalize_row,
    _strip_sensitive_fields,
    get_validation_status,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    AGGREGATE_LOOKBACK,
    DIMENSION_VALUES_MAX_PAGES,
    MUX_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.source import MuxSource


def _driver() -> SourceDriver:
    return SourceDriver(MuxSource(), MuxSourceConfig(access_token_id="id", secret_key="secret"))


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

    def test_source_never_yields_stripped_fields(self) -> None:
        # End-to-end guard: a secret in the API response must not survive into batched rows, and
        # created_at is still coerced to int.
        result = _driver().run(
            "live_streams",
            [ScriptedResponse(json={"data": [{"id": "ls1", "created_at": "1609869152", "stream_key": "leak"}]})],
        )

        assert result.raised is None
        assert result.rows == [{"id": "ls1", "created_at": 1609869152}]
        assert all("stream_key" not in row for row in result.rows)


class TestGetValidationStatus:
    def test_returns_status_code(self) -> None:
        for status_code in (200, 401, 403):
            with scripted_network([ScriptedResponse(status=status_code)]) as network:
                assert get_validation_status("id", "secret", "/video/v1/assets") == status_code

            assert network.requests_log[0].path == "/video/v1/assets"
            assert network.requests_log[0].param("limit") == "1"


class TestOffsetPagination:
    def test_full_final_page_triggers_one_more_empty_fetch(self) -> None:
        # An exact-multiple final page can't be distinguished from a full page, so we fetch once more.
        full_page = [{"id": str(i), "created_at": "1609869152"} for i in range(100)]
        result = _driver().run(
            "live_streams", [ScriptedResponse(json={"data": full_page}), ScriptedResponse(json={"data": []})]
        )

        assert result.raised is None
        assert len(result.rows) == 100
        assert result.params("page") == ["1", "2"]

    def test_resume_from_saved_page(self) -> None:
        result = _driver().run(
            "live_streams",
            [ScriptedResponse(json={"data": [{"id": "x", "created_at": "1609869152"}]})],
            resume_state=MuxResumeConfig(page=3),
        )

        assert result.raised is None
        assert result.rows == [{"id": "x", "created_at": 1609869152}]
        assert result.params("page") == ["3"]


class TestCursorPagination:
    def test_assets_walk_via_next_cursor(self) -> None:
        result = _driver().run(
            "assets",
            [
                ScriptedResponse(json={"data": [{"id": "a1", "created_at": "1609869152"}], "next_cursor": "CURSOR2"}),
                ScriptedResponse(json={"data": [{"id": "a2", "created_at": "1609869152"}], "next_cursor": None}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1", "a2"]
        assert result.params("cursor") == [None, "CURSOR2"]
        assert result.saved_states == [MuxResumeConfig(cursor="CURSOR2")]

    def test_assets_resume_from_saved_cursor(self) -> None:
        result = _driver().run(
            "assets",
            [ScriptedResponse(json={"data": [{"id": "a9", "created_at": "1609869152"}], "next_cursor": None})],
            resume_state=MuxResumeConfig(cursor="SAVED"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a9"]
        assert result.params("cursor") == ["SAVED"]


class TestRetryableErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "live_streams",
            [
                ScriptedResponse(status=status_code),
                ScriptedResponse(json={"data": [{"id": "ok", "created_at": "1609869152"}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ok"]
        assert len(result.requests) == 2

    def test_retryable_status_eventually_raises(self) -> None:
        result = _driver().run("live_streams", always(ScriptedResponse(status=500)))

        assert isinstance(result.raised, Exception)
        # Default of 5 attempts, no early success.
        assert len(result.requests) == 5

    def test_client_error_raises_without_retry(self) -> None:
        # A 403 (missing scope) is a permanent client error — raised on the first response, not retried.
        result = _driver().run("live_streams", [ScriptedResponse(status=403)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


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
    def test_video_views_incremental_windows_from_watermark(self) -> None:
        result = _driver().run(
            "video_views",
            [ScriptedResponse(json={"data": [{"id": "v1", "view_end": "2023-02-01T00:00:00Z"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["v1"]
        assert result.requests[0].query["timeframe[]"][0] == str(1672531200 - int(INCREMENTAL_OVERLAP.total_seconds()))
        # Oldest-first so the asc watermark advances safely, and page pagination still applies.
        assert result.requests[0].param("order_direction") == "asc"
        assert result.requests[0].param("limit") == "100"
        assert result.requests[0].param("page") == "1"

    @parameterized.expand([("errors",), ("metrics_comparison",)])
    def test_single_response_endpoints_fetch_once_with_timeframe(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": [{"id": 1, "code": 500}]})])

        assert result.raised is None
        assert len(result.rows) == 1
        # Single-page paginator: exactly one request, no page/limit walking.
        assert len(result.requests) == 1
        assert "timeframe[]" in result.requests[0].query
        assert result.requests[0].param("page") is None


class TestMuxDataFanOut:
    @mock.patch.object(mux, "DATA_METRICS", ("views", "rebuffer_percentage"))
    def test_metric_timeseries_explodes_points_per_metric(self) -> None:
        result = _driver().run(
            "metric_timeseries",
            [
                ScriptedResponse(
                    json={
                        "data": [["2024-01-01T00:00:00Z", "10", "10"], ["2024-01-02T00:00:00Z", 12, None]],
                        "meta": {"granularity": "day", "aggregation": "view_end"},
                    }
                ),
                ScriptedResponse(
                    json={"data": [["2024-01-01T00:00:00Z", "0.25", "40"]], "meta": {"granularity": "day"}}
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/data/v1/metrics/views/timeseries",
            "/data/v1/metrics/rebuffer_percentage/timeseries",
        ]
        assert result.requests[0].param("group_by") == "day"
        assert "timeframe[]" in result.requests[0].query
        assert result.rows == [
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
    def test_metric_breakdowns_walk_pages_per_metric_and_dimension(self) -> None:
        full_page = [{"field": f"c{i}", "value": 1, "views": 1} for i in range(100)]

        result = _driver().run(
            "metric_breakdowns",
            [
                ScriptedResponse(json={"data": full_page}),
                ScriptedResponse(json={"data": [{"field": "US", "value": 2, "views": 5}]}),
                ScriptedResponse(json={"data": [{"field": "fastly", "value": 3, "views": 7}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/data/v1/metrics/views/breakdown"] * 3
        assert result.params("group_by") == ["country", "country", "cdn"]
        assert result.params("page") == ["1", "2", "1"]
        assert result.requests[0].param("order_by") == "field"
        assert len(result.rows) == 102
        assert result.rows[100] == {"field": "US", "value": 2, "views": 5, "metric": "views", "dimension": "country"}
        assert result.rows[101] == {"field": "fastly", "value": 3, "views": 7, "metric": "views", "dimension": "cdn"}

    def test_dimension_values_fan_out_routes_trace_dimensions_to_elements(self) -> None:
        result = _driver().run(
            "dimension_values",
            [
                ScriptedResponse(json={"data": {"basic": ["country"], "advanced": ["country", "video_cdn_trace"]}}),
                ScriptedResponse(json={"data": [{"value": "US", "total_count": 9}]}),
                ScriptedResponse(json={"data": [{"value": "fastly", "total_count": 4}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/data/v1/dimensions",
            "/data/v1/dimensions/country",
            "/data/v1/dimensions/video_cdn_trace/elements",
        ]
        assert result.rows == [
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

    def test_dimension_values_stop_at_page_cap(self) -> None:
        full_page = {"data": [{"value": str(i), "total_count": 1} for i in range(100)]}

        result = _driver().run(
            "dimension_values",
            [ScriptedResponse(json={"data": {"basic": ["view_session_id"], "advanced": []}})]
            + [ScriptedResponse(json=full_page) for _ in range(DIMENSION_VALUES_MAX_PAGES + 1)],
        )

        assert result.raised is None
        assert len(result.rows) == DIMENSION_VALUES_MAX_PAGES * 100
        assert len(result.requests) == DIMENSION_VALUES_MAX_PAGES + 1

    def test_dimensions_flatten_tiers(self) -> None:
        result = _driver().run(
            "dimensions",
            [ScriptedResponse(json={"data": {"basic": ["browser", "country"], "advanced": ["country", "asn"]}})],
        )

        assert result.raised is None
        assert result.rows == [
            {"name": "browser", "tier": "basic"},
            {"name": "country", "tier": "basic"},
            {"name": "asn", "tier": "advanced"},
        ]

    @mock.patch.object(mux, "DATA_METRICS", ("views", "rebuffer_percentage"))
    def test_fan_out_resumes_past_completed_metrics(self) -> None:
        result = _driver().run(
            "metric_timeseries",
            [ScriptedResponse(json={"data": [["2024-01-01T00:00:00Z", "0.5", "2"]]})],
            resume_state=MuxResumeConfig(
                fan_out={"completed": ["/data/v1/metrics/views/timeseries"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/data/v1/metrics/rebuffer_percentage/timeseries"]
        assert [row["metric"] for row in result.rows] == ["rebuffer_percentage"]
        assert result.saved_states[-1].fan_out["completed"] == [
            "/data/v1/metrics/rebuffer_percentage/timeseries",
            "/data/v1/metrics/views/timeseries",
        ]
