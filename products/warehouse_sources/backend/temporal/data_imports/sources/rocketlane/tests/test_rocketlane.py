import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane import rocketlane
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
    check_access,
    rocketlane_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import (
    ENDPOINTS,
    ROCKETLANE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    rows: list[dict[str, Any]] | None, *, has_more: bool, next_token: str | None, drop_data: bool = False
) -> Response:
    body: dict[str, Any] = {
        "pagination": {
            "pageSize": 100,
            "hasMore": has_more,
            "totalRecordCount": len(rows or []),
            "nextPageToken": next_token,
        },
    }
    if not drop_data:
        body["data"] = rows or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.rocketlane.com/api/1.0/projects"
    return resp


def _make_manager(resume_state: RocketlaneResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

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


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_rows_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"projectId": 1}, {"projectId": 2}], has_more=False, next_token=None)])

        manager = _make_manager()
        rows = _rows(rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"projectId": 1}, {"projectId": 2}]
        assert session.send.call_count == 1
        # No further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_has_more_is_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"projectId": 1}], has_more=True, next_token="t2"),
                _response([{"projectId": 2}], has_more=True, next_token="t3"),
                _response([{"projectId": 3}], has_more=False, next_token=None),
            ],
        )

        rows = _rows(
            rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert rows == [{"projectId": 1}, {"projectId": 2}, {"projectId": 3}]
        # First request omits the token; subsequent requests carry the previous page's nextPageToken.
        assert "pageToken" not in params[0]
        assert params[0]["pageSize"] == 100
        assert params[1]["pageToken"] == "t2"
        assert params[2]["pageToken"] == "t3"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_next_token_missing_even_if_has_more(self, MockSession) -> None:
        # A page advertising hasMore but no token cannot be followed — stop rather than loop.
        session = MockSession.return_value
        _wire(session, [_response([{"projectId": 1}], has_more=True, next_token=None)])

        manager = _make_manager()
        rows = _rows(rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"projectId": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_token_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"projectId": 1}], has_more=True, next_token="t2"),
                _response([{"projectId": 2}], has_more=False, next_token=None),
            ],
        )

        manager = _make_manager()
        _rows(rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        # State is saved AFTER the first page is yielded (pointing at the next token), never for the last.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [RocketlaneResumeConfig(page_token="t2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_token(self, MockSession) -> None:
        session = MockSession.return_value
        # The first page (token None) must never be fetched on resume.
        params = _wire(
            session,
            [
                _response([{"projectId": 2}], has_more=True, next_token="t3"),
                _response([{"projectId": 3}], has_more=False, next_token=None),
            ],
        )

        manager = _make_manager(RocketlaneResumeConfig(page_token="t2"))
        rows = _rows(rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"projectId": 2}, {"projectId": 3}]
        # The seeded resume cursor is sent on the very first request.
        assert params[0]["pageToken"] == "t2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_does_not_yield_and_terminates(self, MockSession) -> None:
        # An empty page terminates the stream even if the API keeps advertising a cursor.
        session = MockSession.return_value
        _wire(session, [_response([], has_more=True, next_token="t2")])

        manager = _make_manager()
        rows = _rows(rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, has_more=False, next_token=None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(
                rocketlane_source("rl-key", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )


class TestCheckAccess:
    @staticmethod
    def _session_for(response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Rocketlane returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = ok
        session = self._session_for(response)
        with mock.patch.object(rocketlane, "make_tracked_session", lambda **kwargs: session):
            assert check_access("rl-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session_for(requests.ConnectionError("boom"))
        with mock.patch.object(rocketlane, "make_tracked_session", lambda **kwargs: session):
            status, message = check_access("rl-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestRocketlaneSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectId"]),
            ("tasks", ["taskId"]),
            ("time_entries", ["timeEntryId"]),
            ("users", ["userId"]),
            ("fields", ["fieldId"]),
        ]
    )
    def test_response_uses_endpoint_primary_key(self, endpoint: str, primary_keys: list[str]) -> None:
        response = rocketlane_source(
            api_key="rl-key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # Every endpoint exposes a stable `createdAt`, so all partition by datetime.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_endpoint_keys_match_endpoints_tuple(self) -> None:
        assert set(ROCKETLANE_ENDPOINTS) == set(ENDPOINTS)
