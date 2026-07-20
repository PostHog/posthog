import json
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook import (
    GITBOOK_BASE_URL,
    PAGE_SIZE,
    GitBookResumeConfig,
    gitbook_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import (
    ENDPOINTS,
    GITBOOK_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the gitbook module.
GITBOOK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook.make_tracked_session"
)

PageKey = tuple[str, Optional[str]]


def _u(path: str) -> str:
    return f"{GITBOOK_BASE_URL}{path}"


def _response(
    items: Optional[list[dict]], *, next_page: Optional[str] = None, status: int = 200, raw_body: Any = None
) -> Response:
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"items": items or []}
        if next_page is not None:
            body["next"] = {"page": next_page}
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


class _FakeManager:
    def __init__(self, state: GitBookResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GitBookResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GitBookResumeConfig | None:
        return self._state

    def save_state(self, data: GitBookResumeConfig) -> None:
        self.saved.append(data)


def _wire(session: MagicMock, pages: dict[PageKey, Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session that dispatches each request to a response keyed by (url, page token).

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy at
    prepare-request time to observe what each page actually sent.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> SimpleNamespace:
        params = dict(request.params or {})
        snapshots.append((request.url, params))
        return SimpleNamespace(url=request.url, _page=params.get("page"), is_redirect=False)

    def _send(prepared: Any, **kwargs: Any) -> Response:
        key = (prepared.url, prepared._page)
        if key not in pages:
            raise AssertionError(f"unexpected request {key}; known keys: {sorted(pages)}")
        return pages[key]

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return snapshots


def _drive(
    endpoint: str, pages: dict[PageKey, Response], manager: _FakeManager
) -> tuple[list[dict], list[tuple[str, dict[str, Any]]]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        snapshots = _wire(session, pages)
        response = gitbook_source(
            api_token="gb-token",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,  # type: ignore[arg-type]
        )
        rows = [row for page in response.items() for row in page]
    return rows, snapshots


class TestTopLevel:
    ORGS = _u("/orgs")

    def test_single_page_yields_and_stops(self) -> None:
        manager = _FakeManager()
        rows, _ = _drive("organizations", {(self.ORGS, None): _response([{"id": "org1"}, {"id": "org2"}])}, manager)
        assert rows == [{"id": "org1"}, {"id": "org2"}]
        # No next page means the sync ends without persisting resume state.
        assert manager.saved == []

    def test_follows_page_token_until_exhausted(self) -> None:
        manager = _FakeManager()
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}], next_page="tok2"),
            (self.ORGS, "tok2"): _response([{"id": "org2"}]),
        }
        rows, _ = _drive("organizations", pages, manager)
        assert rows == [{"id": "org1"}, {"id": "org2"}]
        # State is saved once — after the first page yields, pointing at the next token.
        assert [s.next_page for s in manager.saved] == ["tok2"]

    def test_resumes_from_saved_page_token(self) -> None:
        manager = _FakeManager(GitBookResumeConfig(next_page="tok2"))
        # Only the tok2 page is wired; fetching the first page would raise from the mock.
        rows, _ = _drive("organizations", {(self.ORGS, "tok2"): _response([{"id": "org2"}])}, manager)
        assert rows == [{"id": "org2"}]

    def test_empty_page_yields_nothing(self) -> None:
        manager = _FakeManager()
        rows, _ = _drive("organizations", {(self.ORGS, None): _response([])}, manager)
        assert rows == []
        assert manager.saved == []

    @parameterized.expand(
        [
            ("first_page", None, {"limit": PAGE_SIZE}),
            ("later_page", "tok2", {"limit": PAGE_SIZE, "page": "tok2"}),
        ]
    )
    def test_request_params_carry_limit_and_page_token(
        self, _name: str, page: Optional[str], expected: dict[str, Any]
    ) -> None:
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}], next_page="tok2"),
            (self.ORGS, "tok2"): _response([{"id": "org2"}]),
        }
        _, snapshots = _drive("organizations", pages, _FakeManager())
        index = 0 if page is None else 1
        url, params = snapshots[index]
        assert url == self.ORGS
        assert params == expected


class TestFanOut:
    ORGS = _u("/orgs")

    def test_org_fanout_injects_parent_id_into_rows(self) -> None:
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}, {"id": "org2"}]),
            (_u("/orgs/org1/members"), None): _response([{"id": "user1"}]),
            (_u("/orgs/org2/members"), None): _response([{"id": "user1"}, {"id": "user2"}]),
        }
        rows, _ = _drive("members", pages, _FakeManager())
        # The same user id in two orgs stays distinguishable via the injected organization_id.
        assert rows == [
            {"id": "user1", "organization_id": "org1"},
            {"id": "user1", "organization_id": "org2"},
            {"id": "user2", "organization_id": "org2"},
        ]

    def test_spaces_rows_keep_api_shape_without_injection(self) -> None:
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}]),
            (_u("/orgs/org1/spaces"), None): _response([{"id": "sp1", "organization": "org1"}]),
        }
        rows, _ = _drive("spaces", pages, _FakeManager())
        assert rows == [{"id": "sp1", "organization": "org1"}]

    def test_comments_fan_out_through_orgs_then_spaces(self) -> None:
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}]),
            (_u("/orgs/org1/spaces"), None): _response([{"id": "sp1"}, {"id": "sp2"}]),
            (_u("/spaces/sp1/comments"), None): _response([{"id": "c1"}]),
            (_u("/spaces/sp2/comments"), None): _response([{"id": "c2"}]),
        }
        rows, _ = _drive("comments", pages, _FakeManager())
        assert rows == [{"id": "c1", "space_id": "sp1"}, {"id": "c2", "space_id": "sp2"}]

    def test_saves_completed_parents_and_mid_parent_page_token(self) -> None:
        manager = _FakeManager()
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}, {"id": "org2"}]),
            (_u("/orgs/org1/teams"), None): _response([{"id": "t1"}], next_page="tok2"),
            (_u("/orgs/org1/teams"), "tok2"): _response([{"id": "t2"}]),
            (_u("/orgs/org2/teams"), None): _response([{"id": "t3"}]),
        }
        _drive("teams", pages, manager)
        states = [s.fanout_state for s in manager.saved]
        # A mid-parent checkpoint pins org1's next child page before org1 is marked complete.
        assert {"completed": [], "current": "/orgs/org1/teams", "child_state": {"cursor": "tok2"}} in states
        # Once every parent is walked, all child paths are recorded complete.
        assert states[-1]["completed"] == ["/orgs/org1/teams", "/orgs/org2/teams"]

    def test_resume_skips_completed_parents_and_resumes_current_at_token(self) -> None:
        manager = _FakeManager(
            GitBookResumeConfig(
                fanout_state={
                    "completed": ["/orgs/org1/teams"],
                    "current": "/orgs/org2/teams",
                    "child_state": {"cursor": "tok2"},
                }
            )
        )
        # org1's pages and org2's first page are not wired: fetching either would raise from the mock.
        pages = {
            (self.ORGS, None): _response([{"id": "org1"}, {"id": "org2"}, {"id": "org3"}]),
            (_u("/orgs/org2/teams"), "tok2"): _response([{"id": "t2"}]),
            (_u("/orgs/org3/teams"), None): _response([{"id": "t3"}]),
        }
        rows, _ = _drive("teams", pages, manager)
        assert rows == [
            {"id": "t2", "organization_id": "org2"},
            {"id": "t3", "organization_id": "org3"},
        ]


class TestFailLoud:
    ORGS = _u("/orgs")

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_items", {"count": 1})])
    def test_unexpected_payload_fails_loud(self, _name: str, raw_body: Any) -> None:
        # A 200 body that isn't {"items": [...]} means the response shape changed — fail loud.
        with pytest.raises(ValueError, match="matched nothing"):
            _drive("organizations", {(self.ORGS, None): _response(None, raw_body=raw_body)}, _FakeManager())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise(self, _name: str, status: int) -> None:
        with pytest.raises(HTTPError):
            _drive("organizations", {(self.ORGS, None): _response([], status=status)}, _FakeManager())


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid GitBook API token"),
            ("forbidden", 403, False, "Invalid GitBook API token"),
            ("server_error", 500, False, "GitBook returned HTTP 500"),
        ]
    )
    @mock.patch(GITBOOK_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = MagicMock(status_code=status)
        assert validate_credentials("gb-token") == (expected_valid, expected_message)

    @mock.patch(GITBOOK_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("gb-token") == (False, "Could not validate GitBook API token")


class TestSourceResponse:
    @parameterized.expand(
        [
            ("organizations", ["id"]),
            ("spaces", ["id"]),
            ("collections", ["id"]),
            ("sites", ["organization_id", "id"]),
            ("members", ["organization_id", "id"]),
            ("teams", ["organization_id", "id"]),
            ("change_requests", ["space", "id"]),
            ("comments", ["space_id", "id"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, expected_primary_keys: list[str], _mock_session: MagicMock
    ) -> None:
        response = gitbook_source(
            api_token="gb-token",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # No stable creation timestamp exists on every object, so we don't partition by datetime.
        assert response.partition_mode is None

    def test_endpoint_catalog_is_consistent(self) -> None:
        assert set(GITBOOK_ENDPOINTS) == set(ENDPOINTS)
        # Fan-out endpoints whose ids are not documented as globally unique must carry the parent
        # id in their composite key, and that column must actually be injected into rows.
        for config in GITBOOK_ENDPOINTS.values():
            if config.parent_id_key is not None and config.parent_id_key in config.primary_keys:
                assert config.parent is not None
