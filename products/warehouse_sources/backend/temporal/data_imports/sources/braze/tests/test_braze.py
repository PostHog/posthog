import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import (
    BrazeHostNotAllowedError,
    BrazeResumeConfig,
    _canvas_series_rows,
    _details_row,
    _format_modified_after,
    _series_rows,
    _series_windows,
    braze_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    BRAZE_DETAILS_ENDPOINTS,
    BRAZE_ENDPOINTS,
    DATA_SERIES_HISTORY_DAYS,
)

BASE_URL = "https://rest.iad-01.braze.com"

# Both the data path and the credential probe build their session via
# make_tracked_session imported into the braze module.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session"
HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BrazeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return braze_source(
        "key",
        BASE_URL,
        endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
            (200, True, None),
            (401, False, "Invalid Braze API key"),
            (403, False, "Your Braze API key does not have permission for this endpoint"),
            (500, False, "Braze API returned status 500"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({"message": "x"}, status_code=status_code)

        valid, message = validate_credentials("key", BASE_URL)

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(SESSION_PATCH)
    def test_uses_no_redirect_session_and_probes_with_bearer(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("key", BASE_URL)

        assert mock_session.call_args.kwargs["allow_redirects"] is False
        get_call = mock_session.return_value.get.call_args
        assert get_call.args[0] == f"{BASE_URL}/campaigns/list?page=0"
        assert get_call.kwargs["headers"]["Authorization"] == "Bearer key"

    @mock.patch(SESSION_PATCH)
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = ConnectionError("boom")

        valid, message = validate_credentials("key", BASE_URL)

        assert valid is False
        assert message == "Could not reach the Braze API"

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_blocks_internal_host_when_team_id_given(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        valid, message = validate_credentials("key", "https://10.0.0.1", team_id=42)

        assert valid is False
        assert message == "host not allowed"
        # The host is rejected before any request is dispatched.
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(SESSION_PATCH)
    def test_uses_no_redirect_session_with_redacted_key(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": []})])

        _rows(_source("campaigns"))

        assert MockSession.call_args.kwargs["allow_redirects"] is False
        assert "key" in MockSession.call_args.kwargs["redact_values"]

    @mock.patch(SESSION_PATCH)
    def test_resumes_offset_endpoint_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"templates": []})])

        _rows(_source("email_templates", _make_manager(BrazeResumeConfig(cursor=200))))

        assert params[0]["offset"] == 200
        assert params[0]["limit"] == 100

    @mock.patch(SESSION_PATCH)
    def test_incremental_applies_modified_after_filter(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"templates": [{"email_template_id": "a", "updated_at": "2026-02-01T00:00:00Z"}]}),
                _response({"templates": []}),
            ],
        )

        _rows(
            _source(
                "email_templates",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["modified_after"] == "2026-01-01T00:00:00+00:00"
        # The filter is carried on every page of the run.
        assert params[1]["modified_after"] == "2026-01-01T00:00:00+00:00"

    @mock.patch(SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_modified_after(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"campaigns": [{"id": "1"}]}),
                _response({"campaigns": []}),
            ],
        )

        _rows(
            _source(
                "campaigns",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert all("modified_after" not in p for p in params)

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        response = braze_source(
            "key",
            "https://10.0.0.1",
            "campaigns",
            team_id=42,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        with pytest.raises(BrazeHostNotAllowedError):
            list(cast("Iterable[Any]", response.items()))

        # No request is made once the host is rejected.
        MockSession.return_value.send.assert_not_called()


class TestBrazeSourceResponse:
    @pytest.mark.parametrize("config", list(BRAZE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Partition keys must be immutable creation timestamps, never updated/last-edit fields.
        if config.partition_key:
            assert config.partition_key == "created_at"


def _series_response(data: Any) -> Response:
    return _response({"message": "success", "data": data})


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
    @mock.patch(SESSION_PATCH)
    def test_incremental_narrows_the_window_to_the_watermark(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [_series_response([])]

        _rows(
            _source(
                "kpi_dau",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.now(tz=UTC) - timedelta(days=4),
            )
        )

        assert session.get.call_args.kwargs["params"]["length"] == 5

    @mock.patch(SESSION_PATCH)
    def test_campaign_series_fans_out_over_the_campaign_list(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": "c1"}, {"id": "c2"}]}), _response({"campaigns": []})])
        session.get.side_effect = [
            _series_response([{"time": "2026-03-09", "conversions": 1}]),
            _series_response([{"time": "2026-03-09", "conversions": 2}]),
        ]

        rows = _rows(_source("campaign_analytics"))

        assert [row["campaign_id"] for row in rows] == ["c1", "c2"]
        assert [call.kwargs["params"]["campaign_id"] for call in session.get.call_args_list] == ["c1", "c2"]

    @mock.patch(SESSION_PATCH)
    def test_event_series_fans_out_over_the_event_names(self, MockSession):
        # /events/list returns bare strings, so the fan-out reads the wrapped `event_name`.
        session = MockSession.return_value
        _wire(session, [_response({"events": ["purchase"]}), _response({"events": []})])
        session.get.side_effect = [_series_response([{"time": "2026-03-09", "count": 4}])]

        rows = _rows(_source("event_analytics"))

        assert rows == [{"time": "2026-03-09", "count": 4, "event_name": "purchase"}]
        assert session.get.call_args.kwargs["params"]["event"] == "purchase"

    @mock.patch(SESSION_PATCH)
    def test_canvas_series_requests_every_window_per_canvas(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"canvases": [{"id": "cv1"}]}), _response({"canvases": []})])
        windows = _series_windows(
            BRAZE_DATA_SERIES_ENDPOINTS["canvas_analytics"].max_length_days,
            DATA_SERIES_HISTORY_DAYS,
            datetime.now(tz=UTC),
        )
        session.get.side_effect = [_series_response({"name": "Welcome", "stats": []}) for _ in windows]

        _rows(_source("canvas_analytics"))

        params = [call.kwargs["params"] for call in session.get.call_args_list]
        assert [p["length"] for p in params] == [length for _, length in windows]
        assert all(p["canvas_id"] == "cv1" for p in params)
        # The breakdowns are what make the table usable per step and per variant.
        assert all(p["include_step_breakdown"] == "true" and p["include_variant_breakdown"] == "true" for p in params)

    @mock.patch(SESSION_PATCH)
    def test_segment_series_skips_segments_without_analytics_tracking(self, MockSession):
        # Braze keeps no size history for an untracked segment, and asking for one errors — which
        # would abort the fan-out partway through every other segment.
        session = MockSession.return_value
        _wire(
            session,
            [
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
        )
        session.get.side_effect = [
            _series_response([{"time": "2026-03-09", "size": 10}]),
            _series_response([{"time": "2026-03-09", "size": 20}]),
        ]

        rows = _rows(_source("segment_analytics"))

        assert [row["segment_id"] for row in rows] == ["s1", "s3"]
        assert [call.kwargs["params"]["segment_id"] for call in session.get.call_args_list] == ["s1", "s3"]

    @mock.patch(SESSION_PATCH)
    def test_uses_no_redirect_session_with_redacted_key(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [_series_response([])]

        _rows(_source("kpi_dau"))

        assert MockSession.call_args.kwargs["allow_redirects"] is False
        assert "key" in MockSession.call_args.kwargs["redact_values"]

    @mock.patch(SESSION_PATCH)
    def test_raises_on_an_error_status(self, MockSession):
        # raise_for_status keeps the 403 wording get_non_retryable_errors matches on.
        session = MockSession.return_value
        session.get.side_effect = [_response({"message": "forbidden"}, status_code=403)]

        with pytest.raises(HTTPError, match="403 Client Error"):
            _rows(_source("kpi_dau"))

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        response = braze_source(
            "key",
            "https://10.0.0.1",
            "kpi_dau",
            team_id=42,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        with pytest.raises(BrazeHostNotAllowedError):
            list(cast("Iterable[Any]", response.items()))

        MockSession.return_value.get.assert_not_called()


class TestBrazeDataSeriesSourceResponse:
    @pytest.mark.parametrize("config", list(BRAZE_DATA_SERIES_ENDPOINTS.values()))
    def test_primary_keys_are_unique_table_wide(self, config):
        # A fan-out child aggregates every parent's series, so `time` alone repeats across parents.
        assert "time" in config.primary_keys
        if config.parent_id_column:
            assert config.parent_id_column in config.primary_keys

    @mock.patch(SESSION_PATCH)
    def test_series_rows_are_never_declared_sorted(self, MockSession):
        # Rows arrive grouped by parent and then by window, so the watermark cannot checkpoint
        # mid-stream on `time`.
        session = MockSession.return_value
        session.get.side_effect = [_series_response([])]

        assert _source("kpi_dau").sort_mode is None


class TestDetailsRows:
    @pytest.mark.parametrize("config", list(BRAZE_DETAILS_ENDPOINTS.values()))
    def test_injects_the_parent_id_and_drops_the_status_envelope(self, config):
        row = _details_row(config, "p1", {"message": "success", "name": "Welcome"})

        assert row[config.parent_id_column] == "p1"
        assert "message" not in row
        assert row["name"] == "Welcome"


class TestDetailsRequests:
    @mock.patch(SESSION_PATCH)
    def test_campaign_details_fans_out_over_the_campaign_list(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": "c1"}, {"id": "c2"}]}), _response({"campaigns": []})])
        session.get.side_effect = [
            _response({"message": "success", "name": "Welcome", "channels": ["email"]}),
            _response({"message": "success", "name": "Winback", "channels": ["sms"]}),
        ]

        rows = _rows(_source("campaign_details"))

        assert rows == [
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
        assert [call.args[0] for call in session.get.call_args_list] == [f"{BASE_URL}/campaigns/details"] * 2
        assert [call.kwargs["params"] for call in session.get.call_args_list] == [
            {"campaign_id": "c1"},
            {"campaign_id": "c2"},
        ]

    @mock.patch(SESSION_PATCH)
    def test_raises_on_an_error_status(self, MockSession):
        # raise_for_status keeps the 403 wording get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": "c1"}]}), _response({"campaigns": []})])
        session.get.side_effect = [_response({"message": "forbidden"}, status_code=403)]

        with pytest.raises(HTTPError, match="403 Client Error"):
            _rows(_source("campaign_details"))

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        response = braze_source(
            "key",
            "https://10.0.0.1",
            "campaign_details",
            team_id=42,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        with pytest.raises(BrazeHostNotAllowedError):
            list(cast("Iterable[Any]", response.items()))

        MockSession.return_value.get.assert_not_called()
