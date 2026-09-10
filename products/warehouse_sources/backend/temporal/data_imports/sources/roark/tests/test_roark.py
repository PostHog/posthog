import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark import roark
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.roark import (
    RoarkResumeConfig,
    _base_params,
    roark_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the roark module.
ROARK_SESSION_PATCH = f"{roark.__name__}.make_tracked_session"


def _resp(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _cursor_page(items: list[dict[str, Any]], has_more: bool, next_cursor: str | None = None) -> Response:
    return _resp({"data": items, "pagination": {"hasMore": has_more, "nextCursor": next_cursor}})


def _offset_page(items: list[dict[str, Any]], has_more: bool) -> Response:
    return _resp({"data": items, "pagination": {"hasMore": has_more}})


def _make_manager(resume_state: RoarkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

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


def _source(endpoint: str, manager: mock.MagicMock, api_key: str = "key"):
    return roark_source(api_key=api_key, endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestBaseParams:
    def test_cursor_endpoint_with_sort(self) -> None:
        # call supports sortBy/sortDirection and caps at 100
        params = _base_params(ROARK_ENDPOINTS["call"])
        assert params == {"limit": 100, "sortBy": "createdAt", "sortDirection": "asc"}

    def test_cursor_endpoint_without_sort(self) -> None:
        params = _base_params(ROARK_ENDPOINTS["agent"])
        assert params == {"limit": 50}
        assert "sortBy" not in params

    def test_unpaginated_endpoint_sends_no_limit(self) -> None:
        # metric_definition takes no pagination params at all
        params = _base_params(ROARK_ENDPOINTS["metric_definition"])
        assert params == {}


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_cursor_until_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _cursor_page([{"id": "1"}], has_more=True, next_cursor="c1"),
                _cursor_page([{"id": "2"}], has_more=True, next_cursor="c2"),
                _cursor_page([{"id": "3"}], has_more=False, next_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("agent", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # The `after` param advances to the cursor of the previously-fetched page; the first page
        # carries none.
        assert "after" not in params[0]
        assert params[0]["limit"] == 50
        assert params[1]["after"] == "c1"
        assert params[2]["after"] == "c2"
        # A checkpoint is saved after each non-final page, recording the NEXT page's cursor.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [RoarkResumeConfig(after="c1"), RoarkResumeConfig(after="c2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_next_cursor_missing_even_if_has_more(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_cursor_page([{"id": "1"}], has_more=True, next_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("agent", manager))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_cursor_page([{"id": "9"}], has_more=False, next_cursor=None)])

        manager = _make_manager(RoarkResumeConfig(after="saved-cursor"))
        rows = _rows(_source("agent", manager))

        assert [r["id"] for r in rows] == ["9"]
        # The initial (cursor-less) page is never fetched on resume.
        assert params[0]["after"] == "saved-cursor"


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_offset_advancing_by_rows_returned(self, MockSession) -> None:
        # A non-final page returning fewer rows than max_page_size must advance the offset by the
        # rows actually returned, or rows in the gap would be skipped on the next request.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _offset_page([{"id": "1"}, {"id": "2"}, {"id": "3"}], has_more=True),
                _offset_page([{"id": "4"}], has_more=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("issue", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3", "4"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        # Offset advances by rows RECEIVED (3), not the requested page size.
        assert params[1]["offset"] == 3
        manager.save_state.assert_called_once_with(RoarkResumeConfig(offset=3))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_has_more_false_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_offset_page([{"id": "1"}, {"id": "2"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("issue", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_offset_page([], has_more=False)])

        manager = _make_manager(RoarkResumeConfig(offset=200))
        _rows(_source("issue", manager))

        assert params[0]["offset"] == 200


class TestUnpaginated:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_fetch_envelope(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_resp({"data": [{"id": "1"}, {"id": "2"}]})])

        manager = _make_manager()
        rows = _rows(_source("metric_definition", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_handles_bare_top_level_list_response(self, MockSession) -> None:
        # Unpaginated endpoints may return a bare list instead of a `{"data": [...]}` envelope; those
        # rows must still be synced rather than silently dropped.
        session = MockSession.return_value
        _wire(session, [_resp([{"id": "1"}, {"id": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("metric_definition", manager))

        assert [r["id"] for r in rows] == ["1", "2"]


class TestRetryAndFailLoud:
    @parameterized.expand([("throttled", 429), ("server_error", 500), ("unavailable", 503)])
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_reissued_then_recovers(self, _name: str, status: int, MockSession, _sleep) -> None:
        # Roark documents 429s and transient 5xx as retryable; the client re-issues them.
        session = MockSession.return_value
        _wire(session, [_resp({}, status=status), _cursor_page([{"id": "ok"}], has_more=False)])

        rows = _rows(_source("agent", _make_manager()))
        assert [r["id"] for r in rows] == ["ok"]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persistent_5xx_exhausts_retries_and_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_resp({}, status=500) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("agent", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_fails_loud_without_retry(self, MockSession) -> None:
        # A bad/revoked token surfaces as an HTTPError from raise_for_status — retrying never helps.
        session = MockSession.return_value
        _wire(session, [_resp({"error": "unauthorized"}, status=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("agent", _make_manager()))
        assert session.send.call_count == 1


class TestRoarkSourceResponse:
    def test_response_uses_endpoint_primary_keys_and_partition(self) -> None:
        response = _source("call", _make_manager())
        assert response.name == "call"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["startedAt"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_plan_job_uses_non_id_primary_key(self) -> None:
        response = _source("simulation_plan_job", _make_manager())
        assert response.primary_keys == ["simulationRunPlanJobId"]

    def test_issue_reports_desc_sort_mode(self) -> None:
        # The issue endpoint is fixed newest-first, so we must not claim ascending order.
        response = _source("issue", _make_manager())
        assert response.sort_mode == "desc"

    def test_metric_definition_has_no_partition(self) -> None:
        response = _source("metric_definition", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ROARK_ENDPOINTS[endpoint].primary_keys


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(ROARK_SESSION_PATCH)
    def test_status_maps_to_validity(self, status: int, expected: bool, mock_session) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        mock_session.return_value = session
        assert validate_credentials("key") is expected

    @mock.patch(ROARK_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        mock_session.return_value = session
        assert validate_credentials("key") is False
