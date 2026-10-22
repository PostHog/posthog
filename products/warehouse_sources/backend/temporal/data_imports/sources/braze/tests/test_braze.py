from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import (
    BrazeHostNotAllowedError,
    BrazeResumeConfig,
    _canvas_series_rows,
    _details_row,
    _format_modified_after,
    _series_rows,
    _series_windows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    BRAZE_DETAILS_ENDPOINTS,
    BRAZE_ENDPOINTS,
    DATA_SERIES_HISTORY_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.source import BrazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braze import BrazeSourceConfig

BASE_URL = "https://rest.iad-01.braze.com"

HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe"


def _driver(url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(BrazeSource(), BrazeSourceConfig(api_key="key", url=url))


def _response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _series_response(data: Any) -> ScriptedResponse:
    return _response({"message": "success", "data": data})


class TestFormatModifiedAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_modified_after(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (403, False, "Your Braze API key does not have permission for this endpoint"),
        ],
    )
    def test_status_mapping(self, status_code, expected_valid, expected_message):
        answer = _response({"message": "x"}, status_code)
        with scripted_network(always(answer) if status_code == 500 else [answer]):
            valid, message = validate_credentials("key", BASE_URL)

        assert valid is expected_valid
        assert message == expected_message

    def test_uses_no_redirect_session_and_probes_with_bearer(self):
        with scripted_network([_response({})]) as network:
            validate_credentials("key", BASE_URL)

        assert network.session_options[0]["allow_redirects"] is False
        assert network.requests_log[0].url == f"{BASE_URL}/campaigns/list?page=0"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    @mock.patch(HOST_SAFE_PATCH)
    def test_blocks_internal_host_when_team_id_given(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        with scripted_network([]) as network:
            valid, message = validate_credentials("key", "https://10.0.0.1", team_id=42)

        assert valid is False
        assert message == "host not allowed"
        # The host is rejected before any request is dispatched.
        assert network.requests_log == []


class TestGetRows:
    def test_uses_no_redirect_session_with_redacted_key(self):
        result = _driver().run("campaigns", [_response({"campaigns": []})])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False
        assert "key" in result.session_options[0]["redact_values"]

    def test_resumes_offset_endpoint_from_saved_cursor(self):
        result = _driver().run(
            "email_templates", [_response({"templates": []})], resume_state=BrazeResumeConfig(cursor=200)
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]
        assert result.params("limit") == ["100"]

    def test_incremental_applies_modified_after_filter(self):
        result = _driver().run(
            "email_templates",
            [
                _response({"templates": [{"email_template_id": "a", "updated_at": "2026-02-01T00:00:00Z"}]}),
                _response({"templates": []}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("modified_after")[0] == "2026-01-01T00:00:00+00:00"
        # The filter is carried on every page of the run.
        assert result.params("modified_after")[1] == "2026-01-01T00:00:00+00:00"

    def test_full_refresh_endpoint_never_sends_modified_after(self):
        result = _driver().run(
            "campaigns",
            [
                _response({"campaigns": [{"id": "1"}]}),
                _response({"campaigns": []}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("modified_after") == [None, None]

    @mock.patch(HOST_SAFE_PATCH)
    def test_raises_when_host_not_allowed(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        result = _driver("https://10.0.0.1").run("campaigns", [], team_id=42)

        # No request is made once the host is rejected.
        assert isinstance(result.raised, BrazeHostNotAllowedError)
        assert result.requests == []


class TestBrazeSourceResponse:
    @pytest.mark.parametrize("config", list(BRAZE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Partition keys must be immutable creation timestamps, never updated/last-edit fields.
        if config.partition_key:
            assert config.partition_key == "created_at"


class TestSeriesRows:
    def test_injects_the_parent_id_and_encodes_varying_shapes(self):
        config = BRAZE_DATA_SERIES_ENDPOINTS["campaign_analytics"]

        rows = _series_rows(
            config,
            "campaign-1",
            {"data": [{"time": "2026-03-09", "conversions": 3, "messages": {"email": [{"sent": 5}]}}]},
        )

        assert rows == [
            {
                "time": "2026-03-09",
                "conversions": 3,
                "messages": '{"email": [{"sent": 5}]}',
                "campaign_id": "campaign-1",
            }
        ]

    @pytest.mark.parametrize("body", [{"message": "success"}, {"data": None}, {"data": "nonsense"}, "nonsense"])
    def test_missing_or_unexpected_data_yields_nothing(self, body):
        assert _series_rows(BRAZE_DATA_SERIES_ENDPOINTS["kpi_dau"], None, body) == []

    def test_canvas_rows_flatten_totals_and_encode_breakdowns(self):
        config = BRAZE_DATA_SERIES_ENDPOINTS["canvas_analytics"]

        rows = _canvas_series_rows(
            config,
            "canvas-1",
            {
                "name": "Welcome",
                "stats": [
                    {
                        "time": "2026-03-09",
                        "total_stats": {"revenue": 1.5, "conversions": 2, "entries": 7},
                        "variant_stats": {"variant-1": {"name": "A", "entries": 7}},
                        "step_stats": {"step-1": {"name": "Email", "messages": {"email": [{"sent": 7}]}}},
                    }
                ],
            },
        )

        assert rows == [
            {
                "canvas_id": "canvas-1",
                "canvas_name": "Welcome",
                "time": "2026-03-09",
                "revenue": 1.5,
                "conversions": 2,
                "entries": 7,
                "variant_stats": '{"variant-1": {"name": "A", "entries": 7}}',
                "step_stats": '{"step-1": {"name": "Email", "messages": {"email": [{"sent": 7}]}}}',
            }
        ]

    @pytest.mark.parametrize("data", [None, [], {"name": "Welcome"}])
    def test_canvas_rows_tolerate_a_missing_series(self, data):
        assert _canvas_series_rows(BRAZE_DATA_SERIES_ENDPOINTS["canvas_analytics"], "canvas-1", data) == []


class TestDataSeriesRequests:
    def test_incremental_narrows_the_window_to_the_watermark(self):
        result = _driver().run(
            "kpi_dau",
            [_series_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=4),
        )

        assert result.raised is None
        assert result.params("length") == ["5"]

    def test_campaign_series_fans_out_over_the_campaign_list(self):
        result = _driver().run(
            "campaign_analytics",
            route(
                {
                    "/campaigns/list": [
                        _response({"campaigns": [{"id": "c1"}, {"id": "c2"}]}),
                        _response({"campaigns": []}),
                    ],
                    "/campaigns/data_series": [
                        _series_response([{"time": "2026-03-09", "conversions": 1}]),
                        _series_response([{"time": "2026-03-09", "conversions": 2}]),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["campaign_id"] for row in result.rows] == ["c1", "c2"]
        assert [r.param("campaign_id") for r in result.requests if r.path == "/campaigns/data_series"] == ["c1", "c2"]

    def test_event_series_fans_out_over_the_event_names(self):
        # /events/list returns bare strings, so the fan-out reads the wrapped `event_name`.
        result = _driver().run(
            "event_analytics",
            route(
                {
                    "/events/list": [_response({"events": ["purchase"]}), _response({"events": []})],
                    "/events/data_series": [_series_response([{"time": "2026-03-09", "count": 4}])],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"time": "2026-03-09", "count": 4, "event_name": "purchase"}]
        assert [r.param("event") for r in result.requests if r.path == "/events/data_series"] == ["purchase"]

    def test_canvas_series_requests_every_window_per_canvas(self):
        windows = _series_windows(
            BRAZE_DATA_SERIES_ENDPOINTS["canvas_analytics"].max_length_days,
            DATA_SERIES_HISTORY_DAYS,
            datetime.now(tz=UTC),
        )
        result = _driver().run(
            "canvas_analytics",
            route(
                {
                    "/canvas/list": [_response({"canvases": [{"id": "cv1"}]}), _response({"canvases": []})],
                    "/canvas/data_series": [_series_response({"name": "Welcome", "stats": []}) for _ in windows],
                }
            ),
        )

        assert result.raised is None
        series_requests = [r for r in result.requests if r.path == "/canvas/data_series"]
        assert [r.param("length") for r in series_requests] == [str(length) for _, length in windows]
        assert all(r.param("canvas_id") == "cv1" for r in series_requests)
        # The breakdowns are what make the table usable per step and per variant.
        assert all(
            r.param("include_step_breakdown") == "true" and r.param("include_variant_breakdown") == "true"
            for r in series_requests
        )

    def test_segment_series_skips_segments_without_analytics_tracking(self):
        # Braze keeps no size history for an untracked segment, and asking for one errors — which
        # would abort the fan-out partway through every other segment.
        result = _driver().run(
            "segment_analytics",
            route(
                {
                    "/segments/list": [
                        _response(
                            {
                                "segments": [
                                    {"id": "s1", "analytics_tracking_enabled": True},
                                    {"id": "s2", "analytics_tracking_enabled": False},
                                    {"id": "s3", "analytics_tracking_enabled": True},
                                ]
                            }
                        ),
                        _response({"segments": []}),
                    ],
                    "/segments/data_series": [
                        _series_response([{"time": "2026-03-09", "size": 10}]),
                        _series_response([{"time": "2026-03-09", "size": 20}]),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["segment_id"] for row in result.rows] == ["s1", "s3"]
        assert [r.param("segment_id") for r in result.requests if r.path == "/segments/data_series"] == ["s1", "s3"]

    def test_uses_no_redirect_session_with_redacted_key(self):
        result = _driver().run("kpi_dau", [_series_response([])])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False
        assert "key" in result.session_options[0]["redact_values"]

    def test_raises_on_an_error_status(self):
        # raise_for_status keeps the 403 wording get_non_retryable_errors matches on.
        result = _driver().run("kpi_dau", [_response({"message": "forbidden"}, status=403)])

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error" in str(result.raised)

    @mock.patch(HOST_SAFE_PATCH)
    def test_raises_when_host_not_allowed(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        result = _driver("https://10.0.0.1").run("kpi_dau", [], team_id=42)

        assert isinstance(result.raised, BrazeHostNotAllowedError)
        assert result.requests == []


class TestBrazeDataSeriesSourceResponse:
    @pytest.mark.parametrize("config", list(BRAZE_DATA_SERIES_ENDPOINTS.values()))
    def test_primary_keys_are_unique_table_wide(self, config):
        # A fan-out child aggregates every parent's series, so `time` alone repeats across parents.
        assert "time" in config.primary_keys
        if config.parent_id_column:
            assert config.parent_id_column in config.primary_keys

    def test_series_rows_are_never_declared_sorted(self):
        # Rows arrive grouped by parent and then by window, so the watermark cannot checkpoint
        # mid-stream on `time`.
        result = _driver().run("kpi_dau", [_series_response([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode is None


class TestDetailsRows:
    @pytest.mark.parametrize("config", list(BRAZE_DETAILS_ENDPOINTS.values()))
    def test_injects_the_parent_id_and_drops_the_status_envelope(self, config):
        row = _details_row(config, "p1", {"message": "success", "name": "Welcome"})

        assert row[config.parent_id_column] == "p1"
        assert "message" not in row
        assert row["name"] == "Welcome"


class TestDetailsRequests:
    def test_campaign_details_fans_out_over_the_campaign_list(self):
        result = _driver().run(
            "campaign_details",
            route(
                {
                    "/campaigns/list": [
                        _response({"campaigns": [{"id": "c1"}, {"id": "c2"}]}),
                        _response({"campaigns": []}),
                    ],
                    "/campaigns/details": [
                        _response({"message": "success", "name": "Welcome", "channels": ["email"]}),
                        _response({"message": "success", "name": "Winback", "channels": ["sms"]}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {
                "campaign_id": "c1",
                "name": "Welcome",
                "channels": ["email"],
                "messages": "{}",
                "conversion_behaviors": "[]",
            },
            {
                "campaign_id": "c2",
                "name": "Winback",
                "channels": ["sms"],
                "messages": "{}",
                "conversion_behaviors": "[]",
            },
        ]
        detail_requests = [r for r in result.requests if r.path == "/campaigns/details"]
        assert [r.url.split("?", 1)[0] for r in detail_requests] == [f"{BASE_URL}/campaigns/details"] * 2
        assert [r.param("campaign_id") for r in detail_requests] == ["c1", "c2"]

    def test_raises_on_an_error_status(self):
        # raise_for_status keeps the 403 wording get_non_retryable_errors matches on.
        result = _driver().run(
            "campaign_details",
            route(
                {
                    "/campaigns/list": [_response({"campaigns": [{"id": "c1"}]}), _response({"campaigns": []})],
                    "/campaigns/details": [_response({"message": "forbidden"}, status=403)],
                }
            ),
        )

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error" in str(result.raised)

    @mock.patch(HOST_SAFE_PATCH)
    def test_raises_when_host_not_allowed(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        result = _driver("https://10.0.0.1").run("campaign_details", [], team_id=42)

        assert isinstance(result.raised, BrazeHostNotAllowedError)
        assert result.requests == []
