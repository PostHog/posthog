import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey import (
    ChurnkeyResumeConfig,
    churnkey_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
    CHURNKEY_ENDPOINTS,
    DEFAULT_PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the churnkey module.
CHURNKEY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ChurnkeyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; return (param snapshots, auth snapshots) captured AT SEND TIME.

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


def _source(manager: mock.MagicMock):
    return churnkey_source("data_key", "app_123", "Sessions", team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (404, (False, 404)),
            (500, (False, 500)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple[bool, int]) -> None:
        with mock.patch(CHURNKEY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            assert validate_credentials("key", "app") == expected

    def test_network_failure_returns_none_status(self) -> None:
        with mock.patch(CHURNKEY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key", "app") == (False, None)

    def test_probe_sends_both_auth_headers(self) -> None:
        with mock.patch(CHURNKEY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("data_abc", "app_123")
            headers = mock_session.return_value.get.call_args.kwargs["headers"]
            assert headers["x-ck-api-key"] == "data_abc"
            assert headers["x-ck-app"] == "app_123"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fresh_run_pages_and_saves_after_each_non_terminal_page(self, MockSession) -> None:
        session = MockSession.return_value
        pages = [
            [{"_id": "1"}, {"_id": "2"}],
            [{"_id": "3"}, {"_id": "4"}],
            [{"_id": "5"}],  # short page → terminal
        ]
        with mock.patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2):
            params, _ = _wire(session, [_response(p) for p in pages])
            manager = _make_manager()
            rows = _rows(_source(manager))

        assert [r["_id"] for r in rows] == ["1", "2", "3", "4", "5"]
        # skip advances by the page size (2) each request, starting at 0.
        assert [(p["skip"], p["limit"]) for p in params] == [(0, 2), (2, 2), (4, 2)]
        # State saved only after the two full (non-terminal) pages, never after the short one.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ChurnkeyResumeConfig(skip=2), ChurnkeyResumeConfig(skip=4)]
        manager.load_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_skip(self, MockSession) -> None:
        session = MockSession.return_value
        with mock.patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2):
            params, _ = _wire(session, [_response([{"_id": "5"}])])
            manager = _make_manager(ChurnkeyResumeConfig(skip=4))
            rows = _rows(_source(manager))

        assert [r["_id"] for r in rows] == ["5"]
        assert params[0]["skip"] == 4
        manager.load_state.assert_called_once()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminal_single_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        with mock.patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2):
            _wire(session, [_response([{"_id": "only"}])])
            manager = _make_manager()
            rows = _rows(_source(manager))

        assert [r["_id"] for r in rows] == ["only"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unexpected envelope"})])

        # The endpoint returns a bare array — a non-list 200 body means the response shape
        # changed, so fail loud instead of syncing garbage.
        with pytest.raises(ValueError, match="Required a list response body"):
            _rows(_source(_make_manager()))


class TestAuthAndHeaders:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_auth_and_app_header(self, MockSession) -> None:
        session = MockSession.return_value
        _, auths = _wire(session, [_response([{"_id": "a"}])])
        _rows(_source(_make_manager()))

        # Non-secret headers live on the session; the API key goes through framework auth so it
        # gets redacted from logs.
        assert session.headers["x-ck-app"] == "app_123"
        assert session.headers["content-type"] == "application/json"
        auth = auths[0]
        assert auth.name == "x-ck-api-key"
        assert auth.api_key == "data_key"
        assert auth.location == "header"


class TestChurnkeySource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, MockSession) -> None:
        _wire(MockSession.return_value, [])
        response = _source(_make_manager())

        assert response.name == "Sessions"
        assert response.primary_keys == ["_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["createdAt"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_items_is_lazy(self, MockSession) -> None:
        # Building the SourceResponse must not perform any HTTP — items is a thunk.
        session = MockSession.return_value
        _wire(session, [_response([])])
        response = _source(_make_manager())
        assert session.send.call_count == 0

        list(response.items())
        assert session.send.call_count == 1

    def test_default_page_size_within_api_cap(self) -> None:
        # The API rejects limit > 10,000.
        assert 0 < DEFAULT_PAGE_SIZE <= 10_000
