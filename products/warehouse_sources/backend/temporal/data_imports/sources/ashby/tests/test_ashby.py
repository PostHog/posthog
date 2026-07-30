import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby import (
    ASHBY_BASE_URL,
    AUTH_ERROR_HINT,
    AshbyAPIError,
    AshbyResumeConfig,
    _classify_failure_message,
    _errors_from_payload,
    ashby_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the ashby module.
ASHBY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(
    items: list[dict[str, Any]],
    *,
    more: bool = False,
    next_cursor: Optional[str] = None,
) -> Response:
    body: dict[str, Any] = {"success": True, "results": items, "moreDataAvailable": more}
    if next_cursor is not None:
        body["nextCursor"] = next_cursor
    return _response(body)


def _make_manager(resume_state: AshbyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "url": request.url,
                "method": request.method,
                "json": dict(request.json or {}),
                "auth": request.auth,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "candidates", manager: Optional[mock.MagicMock] = None, api_key: str = "dummy-key"):
    return ashby_source(
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


class TestClassifyFailureMessage:
    @pytest.mark.parametrize(
        "errors, expected_auth",
        [
            (["Invalid API key"], True),
            (["You are not authorized to perform this action"], True),
            (["Missing permission: candidatesRead"], True),
            (["Forbidden"], True),
            (["sync_token_expired"], False),
            (["Some random validation error"], False),
            ([], False),
        ],
    )
    def test_classify(self, errors: list[str], expected_auth: bool) -> None:
        is_auth, message = _classify_failure_message(errors)
        assert is_auth is expected_auth
        assert isinstance(message, str)


class TestErrorsFromPayload:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"errors": ["a", "b"]}, ["a", "b"]),
            ({"errors": "single"}, ["single"]),
            ({"error": "legacy"}, ["legacy"]),
            ({"success": False}, []),
        ],
    )
    def test_errors_from_payload(self, payload: dict[str, Any], expected: list[Any]) -> None:
        assert _errors_from_payload(payload) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_more_data(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "1"}], more=True, next_cursor="c1"),
                _page([{"id": "2"}], more=False),
            ],
        )

        rows = _rows(_source("candidates"))

        assert rows == [{"id": "1"}, {"id": "2"}]
        # First call has no cursor, second forwards nextCursor; limit is sent in the JSON body.
        assert "cursor" not in snapshots[0]["json"]
        assert snapshots[1]["json"]["cursor"] == "c1"
        assert snapshots[0]["json"]["limit"] == 100
        assert snapshots[0]["url"] == f"{ASHBY_BASE_URL}/candidate.list"
        assert snapshots[0]["method"] == "POST"
        # Ashby authenticates via HTTP Basic: API key as username, empty password.
        assert snapshots[0]["auth"].username == "dummy-key"
        assert snapshots[0]["auth"].password == ""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "1"}], more=True, next_cursor="c1"),
                _page([{"id": "2"}], more=False),
            ],
        )
        manager = _make_manager()

        _rows(_source("candidates", manager))

        manager.save_state.assert_called_once_with(AshbyResumeConfig(cursor="c1"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([{"id": "9"}], more=False)])
        manager = _make_manager(AshbyResumeConfig(cursor="resume-cursor"))

        rows = _rows(_source("candidates", manager))

        assert rows == [{"id": "9"}]
        assert snapshots[0]["json"]["cursor"] == "resume-cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_results_yield_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], more=False)])

        assert _rows(_source("users")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_more_data_unavailable_even_with_cursor(self, MockSession) -> None:
        # Ashby can return a nextCursor alongside moreDataAvailable=false — that must terminate.
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], more=False, next_cursor="c9")])
        manager = _make_manager()

        rows = _rows(_source("candidates", manager))

        assert rows == [{"id": "1"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("status_code", [401, 403])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_auth_errors_raise_matchable_error(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=status_code)])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("candidates"))
        assert f"{status_code} Client Error" in str(exc.value)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_success_false_auth_error_raises_matchable_api_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"success": False, "errors": ["Missing permission: candidatesRead"]})])

        with pytest.raises(AshbyAPIError) as exc:
            _rows(_source("candidates"))
        assert AUTH_ERROR_HINT in str(exc.value)
        assert "Missing permission: candidatesRead" in str(exc.value)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_success_false_non_auth_error_raises_without_auth_hint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"success": False, "errors": ["validation failed"]})])

        with pytest.raises(AshbyAPIError) as exc:
            _rows(_source("candidates"))
        assert AUTH_ERROR_HINT not in str(exc.value)
        assert "validation failed" in str(exc.value)


class FakeResponse:
    def __init__(
        self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None, raise_json: bool = False
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = str(self._json)
        self._raise_json = raise_json

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        if self._raise_json:
            raise ValueError("no json")
        return self._json


class TestCheckAccess:
    @pytest.mark.parametrize(
        "response, expected_status",
        [
            (FakeResponse(json_data={"success": True, "results": []}), 200),
            (FakeResponse(status_code=401), 401),
            (FakeResponse(status_code=403), 403),
            (FakeResponse(json_data={"success": False, "errors": ["Missing permission"]}), 403),
            (FakeResponse(json_data={"success": False, "errors": ["bad request"]}), 400),
            (FakeResponse(status_code=500), 500),
            (FakeResponse(raise_json=True), 0),
        ],
    )
    def test_status_mapping(self, response: FakeResponse, expected_status: int) -> None:
        session = mock.MagicMock()
        session.post.return_value = response
        with mock.patch(ASHBY_SESSION_PATCH, return_value=session):
            status, _message = check_access("k", "department.list")
        assert status == expected_status

    def test_probes_endpoint_with_basic_auth(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = FakeResponse(json_data={"success": True, "results": []})
        with mock.patch(ASHBY_SESSION_PATCH, return_value=session):
            check_access("k", "department.list")
        call = session.post.call_args
        assert call.args[0] == f"{ASHBY_BASE_URL}/department.list"
        assert call.kwargs["auth"] == ("k", "")
        assert call.kwargs["json"] == {"limit": 1}

    def test_connection_error_returns_zero(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = Exception("boom")
        with mock.patch(ASHBY_SESSION_PATCH, return_value=session):
            status, message = check_access("k", "department.list")
        assert status == 0
        assert message is not None


class TestAshbySourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_candidates_partitioned_by_created_at(self, MockSession) -> None:
        response = _source("candidates")
        assert response.name == "candidates"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["createdAt"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_is_unpartitioned(self, MockSession) -> None:
        response = _source("users")
        assert response.partition_mode is None
        assert response.partition_format is None
        assert response.partition_keys is None
        assert response.primary_keys == ["id"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_all_endpoints_buildable(self, MockSession) -> None:
        for endpoint in ENDPOINTS:
            response = _source(endpoint)
            assert response.primary_keys == ["id"]
