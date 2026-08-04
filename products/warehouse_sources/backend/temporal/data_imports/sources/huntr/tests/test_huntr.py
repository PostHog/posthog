import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr import (
    PAGE_SIZE,
    HuntrResumeConfig,
    huntr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import ENDPOINTS, HUNTR_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the huntr module.
HUNTR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr.make_tracked_session"
)


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: list[dict[str, Any]] | None, next_cursor: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items if items is not None else []}
    if next_cursor is not None:
        body["next"] = next_cursor
    return _response(body)


def _make_manager(resume_state: HuntrResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "members"):
    return huntr_source(
        access_token="huntr-token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_no_next_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # `next` is null, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_next_is_null(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": "a"}], next_cursor="a"), _page([{"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        # First request omits `next`; the second passes the cursor from the previous page.
        assert "next" not in params[0]
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["next"] == "a"
        assert params[1]["limit"] == PAGE_SIZE
        # State is saved after the first page (cursor advances to "a"); the null cursor stops us.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HuntrResumeConfig(next="a")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": "b"}])])

        manager = _make_manager(HuntrResumeConfig(next="a"))
        rows = _rows(_source(manager))

        # The first (cursorless) page must never be fetched on resume.
        assert rows == [{"id": "b"}]
        assert session.send.call_count == 1
        assert params[0]["next"] == "a"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_next_terminates(self, MockSession) -> None:
        # A lingering cursor on an empty page must not loop forever.
        session = MockSession.return_value
        _wire(session, [_page([], next_cursor="a")])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch("time.sleep")
    def test_retryable_statuses_are_reissued(self, _name: str, status: int, _sleep, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status), _page([{"id": "a"}])])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status=status)])

        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried(self, MockSession, _sleep) -> None:
        # A 200 whose body isn't the expected {"data": [...]} shape is transient — reissue it.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}]), _page([{"id": "a"}])])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_data_field_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": {"id": "a"}}), _page([{"id": "a"}])])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2


class TestValidateCredentials:
    def _patch_session(self, mock_session, response: Any) -> None:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        mock_session.return_value = session

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Huntr access token"),
            (403, False, "Invalid Huntr access token"),
            (500, False, "Huntr returned HTTP 500"),
        ],
    )
    @mock.patch(HUNTR_SESSION_PATCH)
    def test_status_mapping(
        self, mock_session, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        self._patch_session(mock_session, mock.MagicMock(status_code=status))
        assert validate_credentials("huntr-token") == (expected_valid, expected_message)

    @mock.patch(HUNTR_SESSION_PATCH)
    def test_connection_error_is_not_valid(self, mock_session) -> None:
        # validate_via_probe swallows transport errors; the token is simply "not validated".
        self._patch_session(mock_session, ConnectionError("boom"))
        assert validate_credentials("huntr-token") == (False, "Could not validate Huntr access token")


class TestHuntrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in HUNTR_ENDPOINTS.values())
        assert set(HUNTR_ENDPOINTS) == set(ENDPOINTS)
