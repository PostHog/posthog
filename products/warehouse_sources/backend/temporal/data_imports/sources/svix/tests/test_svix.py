import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.svix.settings import ENDPOINTS, SVIX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix import (
    PAGE_SIZE,
    SvixResumeConfig,
    check_access,
    svix_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the svix module.
SVIX_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix.make_tracked_session"


def _response(items: list[dict[str, Any]], iterator: str | None, done: bool, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"iterator": iterator, "done": done}
    if not drop_data:
        body["data"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.svix.com/api/v1/app"
    return resp


def _make_manager(resume_state: SvixResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Wire a mock session; return (param_snapshots, request_capture).

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy at
    prepare-request time. ``request_capture`` keeps the last prepared request for auth/header checks.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    capture: dict[str, Any] = {}

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        capture["auth"] = request.auth
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, capture


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "applications"):
    return svix_source("sk-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_done_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "app_1"}, {"id": "app_2"}], iterator="c1", done=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "app_1"}, {"id": "app_2"}]
        assert session.send.call_count == 1
        # `done` on the first page means we stop without persisting resume state, even though the
        # server echoes a non-null cursor.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_done(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response([{"id": "app_1"}], iterator="c1", done=False),
                _response([{"id": "app_2"}], iterator="c2", done=True),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "app_1"}, {"id": "app_2"}]
        # First request carries no cursor; the second carries the cursor from page one.
        assert "iterator" not in params[0]
        assert params[1]["iterator"] == "c1"
        # State saved once, carrying the cursor that fetches the second page (not the terminal one).
        manager.save_state.assert_called_once_with(SvixResumeConfig(iterator="c1"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_iterator_missing(self, MockSession) -> None:
        # A page that isn't `done` but returns no next cursor must still terminate.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "app_1"}], iterator=None, done=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "app_1"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": "app_2"}], iterator="c2", done=True)])

        manager = _make_manager(SvixResumeConfig(iterator="c1"))
        rows = _rows(_source(manager))

        # The first (cursorless) page must never be fetched on resume — one request, seeded with c1.
        assert rows == [{"id": "app_2"}]
        assert session.send.call_count == 1
        assert params[0]["iterator"] == "c1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], iterator=None, done=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_carries_limit_no_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": "app_1"}], iterator="c1", done=True)])

        _rows(_source(_make_manager()))
        assert params[0] == {"limit": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_not_placed_in_headers(self, MockSession) -> None:
        # The key rides in the framework Bearer auth (redacted from logs/errors), never a hand-set
        # header — only the non-secret Accept header is on the session.
        session = MockSession.return_value
        _, capture = _wire(session, [_response([{"id": "app_1"}], iterator="c1", done=True)])

        _rows(_source(_make_manager()))
        assert "sk-key" not in json.dumps(session.headers)
        assert capture["auth"] is not None

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_body_without_data_key_is_retried_then_recovers(self, MockSession, _sleep) -> None:
        # A 200 whose body lacks the `data` envelope is a transient bad shape — retry, don't fail.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([], iterator=None, done=True, drop_data=True),
                _response([{"id": "app_1"}], iterator="c1", done=True),
            ],
        )

        rows = _rows(_source(_make_manager()))
        assert rows == [{"id": "app_1"}]
        assert session.send.call_count == 2


class TestCheckAccess:
    def _patch_session(self, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (200, None)),
            (401, (401, None)),
            (403, (403, None)),
            (500, (500, "Svix returned HTTP 500")),
        ],
    )
    def test_status_mapping(self, status: int, expected: tuple[int, str | None]) -> None:
        response = mock.MagicMock()
        response.status_code = status
        session = self._patch_session(response)
        with mock.patch(SVIX_SESSION_PATCH, return_value=session):
            assert check_access("sk-key") == expected

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._patch_session(ConnectionError("boom"))
        with mock.patch(SVIX_SESSION_PATCH, return_value=session):
            status, message = check_access("sk-key")
        assert status == 0
        assert message == "Could not connect to Svix"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Svix API key"),
            (403, False, "Invalid Svix API key"),
            (500, False, "Svix returned HTTP 500"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix.check_access")
    def test_validate_credentials(
        self, mock_check: mock.MagicMock, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        message = "Svix returned HTTP 500" if status == 500 else None
        mock_check.return_value = (status, message)
        assert validate_credentials("sk-key") == (expected_valid, expected_message)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix.check_access")
    def test_connection_error_message(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (0, "Could not connect to Svix")
        assert validate_credentials("sk-key") == (False, "Could not connect to Svix")


class TestSvixSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == SVIX_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_primary_keys_per_endpoint(self) -> None:
        assert SVIX_ENDPOINTS["applications"].primary_keys == ["id"]
        assert SVIX_ENDPOINTS["event_types"].primary_keys == ["name"]
        assert set(SVIX_ENDPOINTS) == set(ENDPOINTS)
