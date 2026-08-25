import json
from typing import Any

from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import (
    DELETE_LOG_LIMIT,
    PER_PAGE,
    FloatAppResumeConfig,
    float_app_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the float_app module.
FLOAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app.make_tracked_session"
)


def _response(items: list[dict[str, Any]], headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    if headers:
        resp.headers.update(headers)
    return resp


def _make_manager(resume_state: FloatAppResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
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


def _source(endpoint: str, manager: mock.MagicMock):
    return float_app_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page_via_header(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"people_id": "1"}, {"people_id": "2"}], {"X-Pagination-Pages": "2"}),
                _response([{"people_id": "3"}], {"X-Pagination-Pages": "2"}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert [r["people_id"] for r in rows] == ["1", "2", "3"]
        assert params[0]["per-page"] == PER_PAGE
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_falls_back_to_full_page_heuristic_when_header_absent(self, MockSession) -> None:
        # No X-Pagination-Pages header: a full page (== PER_PAGE) implies another page may follow; a
        # short page ends the walk. Without this fallback a header-less response truncates at page 1.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": str(i)} for i in range(PER_PAGE)], {}),
                _response([{"id": "last"}], {}),
            ],
        )

        rows = _rows(_source("roles", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], {"X-Pagination-Pages": "1"})])

        assert _rows(_source("projects", _make_manager())) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_after_each_page_except_last(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"people_id": "1"}], {"X-Pagination-Pages": "2"}),
                _response([{"people_id": "2"}], {"X-Pagination-Pages": "2"}),
            ],
        )

        manager = _make_manager()
        _rows(_source("people", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FloatAppResumeConfig(next_page=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"people_id": "2"}], {"X-Pagination-Pages": "2"})])

        rows = _rows(_source("people", _make_manager(FloatAppResumeConfig(next_page=2))))

        assert [r["people_id"] for r in rows] == ["2"]
        assert params[0]["page"] == 2
        assert session.send.call_count == 1


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_via_cursor_and_stops_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(
                    [{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                    {"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
                ),
                _response(
                    [{"task_id": 999}],
                    {"X-Pagination-Next-Cursor": "", "X-Pagination-Has-More": "false"},
                ),
            ],
        )

        rows = _rows(_source("deleted_tasks", _make_manager()))

        assert len(rows) == DELETE_LOG_LIMIT + 1
        assert params[0]["limit"] == DELETE_LOG_LIMIT
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "c2"
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_when_full_page_has_no_advancing_cursor(self, MockSession) -> None:
        # A full page whose cursor header is missing must NOT loop forever — the defensive guard stops
        # after one page rather than re-requesting the same cursor endlessly.
        session = MockSession.return_value
        _wire(session, [_response([{"task_id": i} for i in range(DELETE_LOG_LIMIT)], {})])

        rows = _rows(_source("deleted_tasks", _make_manager()))

        assert len(rows) == DELETE_LOG_LIMIT
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_cursor_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                    {"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
                ),
                _response([{"task_id": 999}], {}),
            ],
        )

        manager = _make_manager()
        _rows(_source("deleted_tasks", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert FloatAppResumeConfig(next_cursor="c2") in saved

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"task_id": 999}], {})])

        rows = _rows(_source("deleted_tasks", _make_manager(FloatAppResumeConfig(next_cursor="c2"))))

        assert [r["task_id"] for r in rows] == [999]
        assert params[0]["cursor"] == "c2"
        assert session.send.call_count == 1


class TestValidateCredentials:
    @mock.patch(FLOAT_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok") == (True, 200)

    @mock.patch(FLOAT_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("tok") == (False, 401)

    @mock.patch(FLOAT_SESSION_PATCH)
    def test_forbidden(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
        assert validate_credentials("tok") == (False, 403)

    @mock.patch(FLOAT_SESSION_PATCH)
    def test_transport_error_returns_none_status(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("connection reset")
        assert validate_credentials("tok") == (False, None)
