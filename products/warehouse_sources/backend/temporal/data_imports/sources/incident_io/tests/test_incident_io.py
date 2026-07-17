import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    _build_params,
    _build_url,
    _format_filter_value,
    _params_from_url,
    incident_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    ENDPOINTS,
    INCIDENT_IO_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the incident_io module.
INCIDENT_IO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
)


def _page_body(data_key: str, items: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
    return {data_key: items, "pagination_meta": {"after": after, "page_size": 250}}


def _response(body: dict[str, Any], status_code: int = 200, retry_after: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if retry_after is not None:
        resp.headers["Retry-After"] = retry_after
    return resp


def _make_manager(resume_state: IncidentIoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

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


def _source(session: mock.MagicMock, responses: list[Response], endpoint: str, manager: mock.MagicMock, **kwargs):
    params = _wire(session, responses)
    response = incident_io_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
    rows = [row for page in response.items() for row in page]
    return rows, params


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (datetime(2024, 5, 1, 12, 30, tzinfo=UTC), "2024-05-01"),
            (datetime(2024, 5, 1, 12, 30), "2024-05-01"),
            (date(2024, 5, 1), "2024-05-01"),
            ("2024-05-01T12:30:00Z", "2024-05-01"),
            ("2024-05-01T12:30:00+00:00", "2024-05-01"),
            ("2024-05-01", "2024-05-01"),
            ("not-a-date", None),
            (1700000000, None),
        ],
    )
    def test_format_filter_value(self, value, expected):
        assert _format_filter_value(value) == expected


class TestBuildParams:
    def test_incidents_include_page_size_and_sort(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], None, None)
        assert params == {"page_size": 250, "sort_by": "created_at_oldest_first"}

    def test_incremental_filter_included_when_set(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", "2024-05-01")
        assert params["updated_at[gte]"] == "2024-05-01"

    def test_incremental_filter_omitted_without_value(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", None)
        assert "updated_at[gte]" not in params

    def test_non_paginated_endpoint_has_no_params(self):
        assert _build_params(INCIDENT_IO_ENDPOINTS["severities"], None, None) == {}

    @pytest.mark.parametrize("endpoint", ["alerts", "escalations"])
    def test_small_page_endpoints_use_capped_page_size(self, endpoint):
        params = _build_params(INCIDENT_IO_ENDPOINTS[endpoint], None, None)
        assert params == {"page_size": 50}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v1/severities", {}) == "https://api.incident.io/v1/severities"

    def test_drops_none_values_and_encodes_brackets(self):
        url = _build_url("/v2/incidents", {"page_size": 250, "after": None, "updated_at[gte]": "2024-05-01"})
        assert url == "https://api.incident.io/v2/incidents?page_size=250&updated_at%5Bgte%5D=2024-05-01"


class TestParamsFromUrl:
    def test_strips_after_and_keeps_filters(self):
        url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01H"},
        )
        params = _params_from_url(url)
        assert params == {
            "page_size": "250",
            "sort_by": "created_at_oldest_first",
            "updated_at[gte]": "2024-05-01",
        }

    def test_url_without_query(self):
        assert _params_from_url("https://api.incident.io/v1/severities") == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_status_mapping_at_source_create(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, _ = validate_credentials("key")

        assert is_valid is expected_valid

    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_status_mapping_with_schema_name(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, error = validate_credentials("key", schema_name="alerts")

        assert is_valid is expected_valid
        if status_code == 403:
            assert error is not None and "alerts" in error

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_probes_incidents_with_minimal_page_at_source_create(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key")

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.incident.io/v2/incidents?page_size=1"

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_probes_non_paginated_endpoint_without_page_size(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key", schema_name="severities")

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.incident.io/v1/severities"

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_sends_bearer_auth_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("secret-key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_swallows_network_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("key")

        assert is_valid is False
        assert error is not None


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_pagination_meta_after(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, params = _source(
            session,
            [
                _response(_page_body("incidents", [{"id": "01A"}, {"id": "01B"}], "01B")),
                _response(_page_body("incidents", [{"id": "01C"}], None)),
            ],
            "incidents",
            manager,
        )

        assert [r["id"] for r in rows] == ["01A", "01B", "01C"]
        assert "after" not in params[0]
        assert params[1]["after"] == "01B"
        # State is saved only while a next page exists, after the batch was yielded.
        manager.save_state.assert_called_once()
        assert "after=01B" in manager.save_state.call_args.args[0].next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_filter_and_sort(self, MockSession):
        session = MockSession.return_value
        _, params = _source(
            session,
            [_response(_page_body("incidents", [], None))],
            "incidents",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 12, 30, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert params[0]["updated_at[gte]"] == "2024-05-01"
        assert params[0]["sort_by"] == "created_at_oldest_first"
        assert params[0]["page_size"] == 250

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_incremental_value(self, MockSession):
        session = MockSession.return_value
        _, params = _source(
            session,
            [_response(_page_body("incidents", [], None))],
            "incidents",
            _make_manager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert not any("gte" in key for key in params[0])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state_and_preserves_filters(self, MockSession):
        session = MockSession.return_value
        resume_url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01B"},
        )
        manager = _make_manager(IncidentIoResumeConfig(next_url=resume_url))
        _, params = _source(
            session,
            [
                _response(_page_body("incidents", [{"id": "01C"}], "01C")),
                _response(_page_body("incidents", [], None)),
            ],
            "incidents",
            manager,
        )

        # First request replays the saved cursor and keeps the original chain's filter.
        assert params[0]["after"] == "01B"
        assert params[0]["updated_at[gte]"] == "2024-05-01"
        # The next page swaps in the new cursor but keeps the filter.
        assert params[1]["after"] == "01C"
        assert params[1]["updated_at[gte]"] == "2024-05-01"
        assert "after=01C" in manager.save_state.call_args.args[0].next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession):
        session = MockSession.return_value
        # Body carries an `after`, but a non-paginated endpoint must still fetch exactly once.
        body = {"severities": [{"id": "01A"}], "pagination_meta": {"after": "01A"}}
        manager = _make_manager()
        rows, _ = _source(session, [_response(body)], "severities", manager)

        assert session.send.call_count == 1
        assert [r["id"] for r in rows] == ["01A"]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(session, [_response(_page_body("alerts", [], None))], "alerts", manager)

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession):
        session = MockSession.return_value
        rows, _ = _source(session, [_response({"pagination_meta": {"after": None}})], "incidents", _make_manager())

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429_honoring_retry_after(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(
            session,
            [
                _response({}, status_code=429, retry_after="0"),
                _response(_page_body("incidents", [{"id": "01A"}], None)),
            ],
            "incidents",
            manager,
        )

        assert session.send.call_count == 2
        assert [r["id"] for r in rows] == ["01A"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_5xx(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(
            session,
            [
                _response({}, status_code=500, retry_after="0"),
                _response(_page_body("incidents", [{"id": "01A"}], None)),
            ],
            "incidents",
            manager,
        )

        assert session.send.call_count == 2
        assert [r["id"] for r in rows] == ["01A"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_client_error(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=404)])

        response = incident_io_source(
            "key", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        with pytest.raises(Exception):
            [row for page in response.items() for row in page]


class TestIncidentIoSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = INCIDENT_IO_ENDPOINTS[endpoint]
        response = incident_io_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_endpoint_paths_are_versioned(self, config):
        assert config.path.startswith(("/v1/", "/v2/"))
