import json
from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import (
    EXTERNAL_APPLICATION_NAME,
    ClockodoResumeConfig,
    _endpoint_params,
    _format_z,
    clockodo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the clockodo module.
CLOCKODO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    data_key: str = "customers",
    count_pages: int | None = None,
    drop_data: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if count_pages is not None:
        body["paging"] = {"count_pages": count_pages}
    if not drop_data:
        body[data_key] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ClockodoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; capture each request's params and auth AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return clockodo_source(
        api_user="me@example.com",
        api_key="key123",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestFormatZ:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("with_micros_truncated", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
        ]
    )
    def test_format_z(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_z(value) == expected


class TestEndpointParams:
    @freeze_time("2026-06-29T12:00:00Z")
    def test_entries_requires_time_window(self) -> None:
        params = _endpoint_params("entries")
        # Listing entries without a time range is rejected by the API.
        assert params["time_since"] == "2000-01-01T00:00:00Z"
        # time_until is pushed a year past now to also capture planned (future) entries.
        assert params["time_until"] == "2027-06-29T12:00:00Z"

    @parameterized.expand([("customers",), ("projects",), ("services",), ("users",)])
    def test_non_entries_have_no_time_window(self, endpoint: str) -> None:
        params = _endpoint_params(endpoint)
        assert "time_since" not in params
        assert "time_until" not in params


class TestHeadersAndAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_identification_headers_and_api_key_auth(self, MockSession) -> None:
        session = MockSession.return_value
        _params, auths = _wire(session, [_response([{"id": 1}], count_pages=1)])

        _rows(_source("customers", _make_manager()))

        # The API rejects every request without the identification headers.
        assert session.headers["X-ClockodoApiUser"] == "me@example.com"
        assert session.headers["X-Clockodo-External-Application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"
        # The API key travels via the framework auth config so its value is redacted from logs.
        auth = auths[0]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "X-ClockodoApiKey"
        assert auth.api_key == "key123"
        assert auth.location == "header"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginated_walks_all_pages_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], count_pages=2),
                _response([{"id": 3}], count_pages=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page (points at the next page to fetch); the paging
        # block says page 2 is the last, so no further checkpoint is written.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ClockodoResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_after_count_pages_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], count_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_before_count_pages(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], count_pages=3),
                _response([], count_pages=3),
            ],
        )

        rows = _rows(_source("customers", _make_manager()))

        # An empty page ends the walk even when the paging block promises more pages.
        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response([{"id": 3}], count_pages=2)])

        manager = _make_manager(ClockodoResumeConfig(next_page=2))
        rows = _rows(_source("customers", manager))

        # Picks up at the saved page rather than restarting at page 1.
        assert params[0]["page"] == 2
        assert [r["id"] for r in rows] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_single_fetch(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response([{"id": 1}, {"id": 2}], data_key="services")])

        manager = _make_manager()
        rows = _rows(_source("services", manager))

        assert session.send.call_count == 1
        # Non-paginated endpoints never send a page param.
        assert "page" not in params[0]
        assert [r["id"] for r in rows] == [1, 2]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    @freeze_time("2026-06-29T12:00:00Z")
    def test_entries_sends_time_window(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response([{"id": 1}], data_key="entries", count_pages=1)])

        _rows(_source("entries", _make_manager()))

        assert params[0]["time_since"] == "2000-01-01T00:00:00Z"
        assert params[0]["time_until"] == "2027-06-29T12:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], count_pages=1)])

        rows = _rows(_source("customers", _make_manager()))

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, count_pages=1, drop_data=True)])

        rows = _rows(_source("customers", _make_manager()))

        assert rows == []


class TestClockodoSourceResponse:
    @parameterized.expand([("customers",), ("entries",), ("users",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_default_to_id(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("u", "k") is expected

    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_validate_credentials_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("u", "k") is False

    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_probe_sends_credentials(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("me@example.com", "key123")
        _args, kwargs = mock_session.return_value.get.call_args
        headers = kwargs["headers"]
        assert headers["X-ClockodoApiUser"] == "me@example.com"
        assert headers["X-ClockodoApiKey"] == "key123"
        assert headers["X-Clockodo-External-Application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"
