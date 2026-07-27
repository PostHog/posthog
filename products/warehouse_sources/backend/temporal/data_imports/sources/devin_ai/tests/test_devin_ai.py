import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    PAGE_SIZE,
    DevinAIResumeConfig,
    _endpoint_path,
    devin_ai_source,
    get_status_code,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import DEVIN_AI_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_status_code builds its own tracked session in the devin_ai module.
DEVIN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, has_next_page: bool = False, end_cursor: str | None = None
) -> Response:
    body: dict[str, Any] = {"has_next_page": has_next_page, "end_cursor": end_cursor}
    if items is not None:
        body["items"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: DevinAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared rather than inspecting the final state after the run.
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
    return devin_ai_source(
        api_key="cog_test",
        org_id="org-abc",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestEndpointPath:
    @parameterized.expand(
        [
            ("sessions", "/v3/organizations/org-abc/sessions"),
            ("playbooks", "/v3/organizations/org-abc/playbooks"),
            ("knowledge_notes", "/v3/organizations/org-abc/knowledge/notes"),
            ("secrets", "/v3/organizations/org-abc/secrets"),
        ]
    )
    def test_org_id_is_interpolated_into_path(self, endpoint: str, expected: str) -> None:
        assert _endpoint_path(endpoint, "org-abc") == expected

    @parameterized.expand(
        [
            ("path_traversal", "org-abc/../billing"),
            ("query_injection", "org-abc?first=1"),
            ("slash", "org/abc"),
            ("empty", ""),
            ("whitespace_only", "   "),
        ]
    )
    def test_malicious_org_id_is_rejected(self, _name: str, org_id: str) -> None:
        # A malformed org_id must not be able to inject `/` or `?` to route the stored key elsewhere.
        with pytest.raises(ValueError):
            _endpoint_path("sessions", org_id)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_items_as_dicts(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"session_id": "s1"}, {"session_id": "s2"}])])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_has_no_after_and_uses_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"session_id": "s1"}])])

        _rows(_source("sessions", _make_manager()))
        assert params[0] == {"first": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"session_id": "s1"}], has_next_page=True, end_cursor="cur1"),
                _response([{"session_id": "s2"}], has_next_page=False, end_cursor=None),
            ],
        )

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]
        # The second request must carry the cursor from the first page's end_cursor.
        assert params[1] == {"first": PAGE_SIZE, "after": "cur1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_next_page_false_even_if_cursor_present(self, MockSession) -> None:
        session = MockSession.return_value
        # A defensive guard: a cursor with has_next_page false must not loop.
        _wire(session, [_response([{"session_id": "s1"}], has_next_page=False, end_cursor="cur1")])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"session_id": "s3"}])])

        _rows(_source("sessions", _make_manager(DevinAIResumeConfig(after="saved_cursor"))))
        assert params[0] == {"first": PAGE_SIZE, "after": "saved_cursor"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_cursor_at_page_boundary_only(self, MockSession) -> None:
        session = MockSession.return_value
        # State is saved once per completed page that has a successor, after the page is yielded — so a
        # crash re-fetches the last page (merge dedupes) rather than skipping its tail. No save after the
        # final page (nothing left to resume into).
        _wire(
            session,
            [
                _response([{"session_id": "s1"}], has_next_page=True, end_cursor="cur1"),
                _response([{"session_id": "s2"}], has_next_page=True, end_cursor="cur2"),
                _response([{"session_id": "s3"}], has_next_page=False, end_cursor=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("sessions", manager))
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert saved == [DevinAIResumeConfig(after="cur1"), DevinAIResumeConfig(after="cur2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_items_key_yields_no_rows_without_raising(self, MockSession) -> None:
        session = MockSession.return_value
        # The Devin envelope tolerates a page with no `items` key (defaults to empty) rather than failing.
        _wire(session, [_response(None, has_next_page=False, end_cursor=None)])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"session_id": "s1"}])])

        _rows(_source("sessions", _make_manager()))
        # The token is applied via the framework auth (redacted), not a hand-built header on the session.
        assert session.headers.get("Authorization") is None
        assert session.auth is not None


class TestGetStatusCode:
    def test_returns_status_and_probes_with_first_one(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch(DEVIN_SESSION_PATCH, return_value=session):
            status = get_status_code("cog_test", "org-abc", "sessions")

        assert status == 200
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"first": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer cog_test"


class TestDevinAISource:
    @parameterized.expand(list(DEVIN_AI_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        cfg = DEVIN_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # created_at is a stable field — never updated_at — so partitions don't rewrite each sync.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
