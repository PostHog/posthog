import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.plausible import plausible as plausible_module
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.plausible import (
    PlausibleResumeConfig,
    _normalize_row,
    hostname_of,
    normalize_host,
    plausible_source,
    resolve_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    ENDPOINTS,
    PLAUSIBLE_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.plausible.plausible"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _result(dimensions: list[Any], metrics: list[Any]) -> dict[str, Any]:
    return {"dimensions": dimensions, "metrics": metrics}


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PlausibleResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's JSON body AT SEND TIME.

    The paginator mutates ``request.json`` in place across pages, so inspecting it after the run shows
    only the final state — snapshot a deep copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(copy.deepcopy(request.json) or {})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(**overrides: Any):
    kwargs: dict[str, Any] = {
        "host": "https://plausible.io",
        "site_id": "example.com",
        "api_key": "key",
        "endpoint": "timeseries",
        "team_id": 1,
        "job_id": "j",
        "resumable_source_manager": _make_manager(),
    }
    kwargs.update(overrides)
    return plausible_source(**kwargs)


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://plausible.io", "https://plausible.io"),
            ("plausible.example.com", "https://plausible.example.com"),
            ("https://analytics.example.com/", "https://analytics.example.com"),
            ("http://analytics.internal:8080", "http://analytics.internal:8080"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    @pytest.mark.parametrize("value", [None, ""])
    def test_resolve_host_defaults_to_cloud(self, value):
        assert resolve_host(value) == "https://plausible.io"

    def test_hostname_of(self):
        assert hostname_of("https://analytics.example.com/path") == "analytics.example.com"
        assert hostname_of(None) == "plausible.io"


class TestNormalizeRow:
    def test_maps_dimensions_and_metrics_to_named_columns(self):
        config = PLAUSIBLE_ENDPOINTS["sources"]
        row = _normalize_row(config, _result(["2024-01-01", "Google"], [10, 12, 30, 0.5, 60, 40]))

        assert row == {
            "date": "2024-01-01",
            "source": "Google",
            "visitors": 10,
            "visits": 12,
            "pageviews": 30,
            "bounce_rate": 0.5,
            "visit_duration": 60,
            "events": 40,
        }

    def test_timeseries_has_only_date_dimension(self):
        config = PLAUSIBLE_ENDPOINTS["timeseries"]
        row = _normalize_row(config, _result(["2024-01-01"], [10, 12, 30, 0.5, 60, 40]))

        assert row["date"] == "2024-01-01"
        assert "source" not in row


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials(self, mock_session):
        mock_session.return_value.post.return_value = mock.MagicMock(status_code=200)

        ok, error = validate_credentials("https://plausible.io", "example.com", "key")
        assert ok is True
        assert error is None
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["site_id"] == "example.com"
        assert body["metrics"] == ["visitors"]
        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer key"

    @pytest.mark.parametrize(
        "status_code, fragment",
        [
            (401, "API key"),
            (403, "API key"),
            (404, "site"),
            (400, "status 400"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_failure_status_codes(self, mock_session, status_code, fragment):
        resp = mock.MagicMock(status_code=status_code)
        resp.json.return_value = {}
        mock_session.return_value.post.return_value = resp

        ok, error = validate_credentials("https://plausible.io", "example.com", "bad")
        assert ok is False
        assert error is not None and fragment in error

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unreachable_host(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("dns failure")

        ok, error = validate_credentials("https://bad.example", "example.com", "key")
        assert ok is False
        assert error is not None and "reach" in error


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_builds_query_and_yields_normalized_rows(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response(
                    {
                        "results": [_result(["2024-01-01", "Google"], [10, 12, 30, 0.5, 60, 40])],
                        "meta": {"total_rows": 1},
                    }
                )
            ],
        )

        rows = _rows(_source(endpoint="sources"))

        assert rows == [
            {
                "date": "2024-01-01",
                "source": "Google",
                "visitors": 10,
                "visits": 12,
                "pageviews": 30,
                "bounce_rate": 0.5,
                "visit_duration": 60,
                "events": 40,
            }
        ]
        assert bodies[0]["dimensions"] == ["time:day", "visit:source"]
        assert bodies[0]["order_by"] == [["time:day", "asc"]]
        assert bodies[0]["include"] == {"total_rows": True}
        assert bodies[0]["pagination"]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state(self, MockSession):
        session = MockSession.return_value
        # Shrink the page size so two small pages exercise the offset pagination loop.
        with mock.patch.object(plausible_module, "DEFAULT_PAGE_LIMIT", 2):
            page1 = {
                "results": [_result(["2024-01-01"], [1, 1, 1, 0, 0, 1]), _result(["2024-01-02"], [2, 2, 2, 0, 0, 2])],
                "meta": {"total_rows": 3},
            }
            page2 = {"results": [_result(["2024-01-03"], [3, 3, 3, 0, 0, 3])], "meta": {"total_rows": 3}}
            bodies = _wire(session, [_response(page1), _response(page2)])

            manager = _make_manager()
            batches = list(_source(endpoint="timeseries", resumable_source_manager=manager).items())

        assert [len(batch) for batch in batches] == [2, 1]
        # The second request advances the offset past the first page.
        assert bodies[1]["pagination"]["offset"] == 2
        # State is saved once, after the first page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_watermark_slides_window_back_by_lookback(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"results": [], "meta": {"total_rows": 0}})])

        _rows(
            _source(
                endpoint="timeseries",
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-06-01",
            )
        )

        expected_start = (datetime(2024, 6, 1, tzinfo=UTC).date() - timedelta(days=REPORT_LOOKBACK_DAYS)).isoformat()
        assert bodies[0]["date_range"][0] == expected_start

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_state_pins_offset_and_window(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"results": [], "meta": {"total_rows": 0}})])

        manager = _make_manager(
            PlausibleResumeConfig(offset=4, date_range_start="2024-01-01", date_range_end="2024-01-31")
        )
        _rows(_source(endpoint="timeseries", resumable_source_manager=manager))

        assert bodies[0]["pagination"]["offset"] == 4
        assert bodies[0]["date_range"] == ["2024-01-01", "2024-01-31"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_error_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"error": "bad query"}, status_code=400)])

        with pytest.raises(Exception, match="400"):
            _rows(_source(endpoint="timeseries"))


class TestPlausibleSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = PLAUSIBLE_ENDPOINTS[endpoint]
        response = _source(endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert "date" in (response.primary_keys or [])
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
