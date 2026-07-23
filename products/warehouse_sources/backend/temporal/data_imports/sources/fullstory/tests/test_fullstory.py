import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory import (
    FullStoryResumeConfig,
    fullstory_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the fullstory module.
FULLSTORY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, next_token: str | None = None, drop_results: bool = False
) -> Response:
    body: dict[str, Any] = {}
    if not drop_results:
        body["results"] = items or []
    if next_token:
        body["next_page_token"] = next_token
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FullStoryResumeConfig | None = None) -> mock.MagicMock:
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


def _source(manager: mock.MagicMock):
    return fullstory_source("key", "users", team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_page_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "u1"}], next_token="tok1"), _response([{"id": "u2"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == ["u1", "u2"]
        # First page has no cursor; second page carries the saved token.
        assert "page_token" not in params[0]
        assert params[1]["page_token"] == "tok1"
        # Checkpoint saved once after the first page (points at the next page); the tokenless page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FullStoryResumeConfig(next_page_token="tok1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "u_resumed"}])])

        manager = _make_manager(FullStoryResumeConfig(next_page_token="tok_resume"))
        _rows(_source(manager))

        assert params[0]["page_token"] == "tok_resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_even_with_cursor_and_no_checkpoint(self, MockSession) -> None:
        # A tokened-but-empty page must not loop; stop after one request without saving state.
        session = MockSession.return_value
        _wire(session, [_response([], next_token="tok_loop")])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tokenless_page_stops_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "u1"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == ["u1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_is_empty_page(self, MockSession) -> None:
        # Matches the old `data.get("results", []) or []` — a missing key is 0 rows, not an error.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_results=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_data_path_authorizes_with_basic_scheme(self, MockSession) -> None:
        # The api_key auth carries the "Basic <raw key>" value onto the Authorization header when
        # requests prepares the request. Prove the RESTClient session is constructed with the raw
        # key registered for redaction (which is derived from the same auth value).
        _wire(MockSession.return_value, [_response([{"id": "u1"}])])

        _rows(_source(_make_manager()))

        assert MockSession.call_args.kwargs["redact_values"] == ("Basic key",)


class TestSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata(self, MockSession) -> None:
        _wire(MockSession.return_value, [_response([{"id": "u1"}])])
        response = _source(_make_manager())

        assert response.name == "users"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(FULLSTORY_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is expected

    @mock.patch(FULLSTORY_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(FULLSTORY_SESSION_PATCH)
    def test_probe_sends_basic_auth_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key123")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Basic key123"
