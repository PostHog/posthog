import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import (
    PAGE_SIZE,
    DeelResumeConfig,
    deel_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import DEEL_ENDPOINTS, ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the deel module.
DEEL_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session"


def _response(items: list[dict[str, Any]] | None, *, cursor: str | None = None, drop_data: bool = False) -> Response:
    page: dict[str, Any] = {"total_rows": len(items or [])}
    if cursor is not None:
        page["cursor"] = cursor
    body: dict[str, Any] = {"page": page}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: DeelResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy
    when each request is prepared instead of inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return deel_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, None)),
            # A valid token without people:read still 403s; only 401 means the token is bad.
            (403, (True, None)),
            (401, (False, "Invalid Deel API token")),
        ],
    )
    @mock.patch(DEEL_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") == expected

    @mock.patch(DEEL_SESSION_PATCH)
    def test_validate_credentials_reports_network_error_distinctly(self, mock_session):
        # A transient network failure must not masquerade as a bad token.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, error = validate_credentials("token")
        assert valid is False
        assert error is not None and error.startswith("Could not reach Deel")


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession):
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the first full page; the short page ends the walk.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DeelResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([])])

        manager = _make_manager(DeelResumeConfig(offset=150))
        _rows(_source("people", manager))

        assert params[0]["offset"] == 150

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_lenient_empty_page(self, MockSession):
        # Deel's hand-rolled walk used `body.get("data", [])`, so a body without `data`
        # is a zero-row page, not a hard failure.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_after_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], cursor="cur_abc"), _response([{"id": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("contracts", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert params[0]["limit"] == PAGE_SIZE
        assert "after_cursor" not in params[0]
        assert params[1]["after_cursor"] == "cur_abc"
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DeelResumeConfig(cursor="cur_abc")

    @pytest.mark.parametrize("num_pages", [2, 3])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, MockSession, num_pages):
        # Pages 1..n-1 carry a cursor; the terminal page has none, so state is saved
        # exactly n - 1 times — once after every page that advances the walk.
        session = MockSession.return_value
        responses = [_response([{"id": str(i)}], cursor=f"cur_{i}") for i in range(1, num_pages)]
        responses.append(_response([{"id": str(num_pages)}]))
        _wire(session, responses)

        manager = _make_manager()
        _rows(_source("contracts", manager))

        assert manager.save_state.call_count == num_pages - 1
        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        assert saved_cursors == [f"cur_{i}" for i in range(1, num_pages)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([])])

        manager = _make_manager(DeelResumeConfig(cursor="cur_resume"))
        _rows(_source("contracts", manager))

        assert params[0]["after_cursor"] == "cur_resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_cursor_stops(self, MockSession):
        # A cursor echoed alongside an empty page must terminate rather than loop.
        session = MockSession.return_value
        _wire(session, [_response([], cursor="cur_loop")])

        manager = _make_manager()
        rows = _rows(_source("contracts", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestDeelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DEEL_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(DEEL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
