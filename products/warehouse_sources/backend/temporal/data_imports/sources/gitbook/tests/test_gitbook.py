from collections.abc import Mapping
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook import gitbook
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook import (
    GITBOOK_BASE_URL,
    PAGE_SIZE,
    GitBookResumeConfig,
    GitBookRetryableError,
    check_access,
    get_rows,
    gitbook_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import (
    ENDPOINTS,
    GITBOOK_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = gitbook._fetch_page.__wrapped__  # type: ignore[attr-defined]

PageKey = tuple[str, Optional[str]]


class _FakeResumableManager:
    def __init__(self, state: GitBookResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GitBookResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GitBookResumeConfig | None:
        return self._state

    def save_state(self, data: GitBookResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: Mapping[PageKey, tuple[list[dict], Optional[str]]],
    endpoint: str,
) -> list[dict]:
    def fake_fetch(session: Any, url: str, page: Optional[str], logger: Any) -> tuple[list[dict], Optional[str]]:
        return pages[(url, page)]

    monkeypatch.setattr(gitbook, "_fetch_page", fake_fetch)
    monkeypatch.setattr(gitbook, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        api_token="gb-token",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestGetRowsTopLevel:
    ORGS_URL = f"{GITBOOK_BASE_URL}/orgs"

    def test_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect(
            manager, monkeypatch, {(self.ORGS_URL, None): ([{"id": "org1"}, {"id": "org2"}], None)}, "organizations"
        )
        assert rows == [{"id": "org1"}, {"id": "org2"}]
        # No next page means the sync ends without persisting resume state.
        assert manager.saved == []

    def test_follows_page_token_until_exhausted(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}], "tok2"),
            (self.ORGS_URL, "tok2"): ([{"id": "org2"}], None),
        }
        rows = _collect(manager, monkeypatch, pages, "organizations")
        assert rows == [{"id": "org1"}, {"id": "org2"}]
        # State is saved once — after the first page yields, pointing at the next token.
        assert [s.next_page for s in manager.saved] == ["tok2"]

    def test_resumes_from_saved_page_token(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(GitBookResumeConfig(next_page="tok2"))
        # The first page must never be fetched on resume.
        rows = _collect(manager, monkeypatch, {(self.ORGS_URL, "tok2"): ([{"id": "org2"}], None)}, "organizations")
        assert rows == [{"id": "org2"}]

    def test_empty_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, {(self.ORGS_URL, None): ([], None)}, "organizations")
        assert rows == []
        assert manager.saved == []


class TestGetRowsFanOut:
    ORGS_URL = f"{GITBOOK_BASE_URL}/orgs"

    def test_org_fanout_injects_parent_id_into_rows(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}, {"id": "org2"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org1/members", None): ([{"id": "user1"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org2/members", None): ([{"id": "user1"}, {"id": "user2"}], None),
        }
        rows = _collect(manager, monkeypatch, pages, "members")
        # The same user id in two orgs stays distinguishable via the injected organization_id.
        assert rows == [
            {"id": "user1", "organization_id": "org1"},
            {"id": "user1", "organization_id": "org2"},
            {"id": "user2", "organization_id": "org2"},
        ]

    def test_spaces_rows_keep_api_shape_without_injection(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org1/spaces", None): ([{"id": "sp1", "organization": "org1"}], None),
        }
        rows = _collect(manager, monkeypatch, pages, "spaces")
        assert rows == [{"id": "sp1", "organization": "org1"}]

    def test_comments_fan_out_through_orgs_then_spaces(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org1/spaces", None): ([{"id": "sp1"}, {"id": "sp2"}], None),
            (f"{GITBOOK_BASE_URL}/spaces/sp1/comments", None): ([{"id": "c1"}], None),
            (f"{GITBOOK_BASE_URL}/spaces/sp2/comments", None): ([{"id": "c2"}], None),
        }
        rows = _collect(manager, monkeypatch, pages, "comments")
        assert rows == [{"id": "c1", "space_id": "sp1"}, {"id": "c2", "space_id": "sp2"}]

    def test_saves_completed_parents_and_mid_parent_page_token(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}, {"id": "org2"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org1/teams", None): ([{"id": "t1"}], "tok2"),
            (f"{GITBOOK_BASE_URL}/orgs/org1/teams", "tok2"): ([{"id": "t2"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org2/teams", None): ([{"id": "t3"}], None),
        }
        _collect(manager, monkeypatch, pages, "teams")
        assert [(s.completed_parent_ids, s.current_parent_id, s.next_page) for s in manager.saved] == [
            ([], "org1", "tok2"),
            (["org1"], None, None),
            (["org1", "org2"], None, None),
        ]

    def test_resume_skips_completed_parents_and_resumes_current_at_token(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(
            GitBookResumeConfig(completed_parent_ids=["org1"], current_parent_id="org2", next_page="tok2")
        )
        # org1's pages and org2's first page must never be fetched on resume.
        pages: dict[PageKey, tuple[list[dict], Optional[str]]] = {
            (self.ORGS_URL, None): ([{"id": "org1"}, {"id": "org2"}, {"id": "org3"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org2/teams", "tok2"): ([{"id": "t2"}], None),
            (f"{GITBOOK_BASE_URL}/orgs/org3/teams", None): ([{"id": "t3"}], None),
        }
        rows = _collect(manager, monkeypatch, pages, "teams")
        assert rows == [
            {"id": "t2", "organization_id": "org2"},
            {"id": "t3", "organization_id": "org3"},
        ]


class TestFetchPage:
    URL = f"{GITBOOK_BASE_URL}/orgs"

    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"items": []}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(GitBookRetryableError):
            _fetch_page_unwrapped(session, self.URL, None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, self.URL, None, MagicMock())

    def test_success_returns_items_and_next_page_token(self) -> None:
        body = {"items": [{"id": "org1"}], "next": {"page": "tok2"}, "count": 5}
        session = self._session_returning(200, body)
        rows, next_page = _fetch_page_unwrapped(session, self.URL, None, MagicMock())
        assert rows == [{"id": "org1"}]
        assert next_page == "tok2"

    def test_missing_next_returns_none(self) -> None:
        session = self._session_returning(200, {"items": [{"id": "org1"}]})
        _, next_page = _fetch_page_unwrapped(session, self.URL, None, MagicMock())
        assert next_page is None

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_items", {"count": 1})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(GitBookRetryableError):
            _fetch_page_unwrapped(session, self.URL, None, MagicMock())

    @parameterized.expand(
        [
            ("first_page", None, {"limit": PAGE_SIZE}),
            ("later_page", "tok2", {"limit": PAGE_SIZE, "page": "tok2"}),
        ]
    )
    def test_request_params_carry_limit_and_page_token(
        self, _name: str, page: Optional[str], expected_params: dict
    ) -> None:
        session = self._session_returning(200, {"items": []})
        _fetch_page_unwrapped(session, self.URL, page, MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == self.URL
        assert kwargs["params"] == expected_params


class TestCheckAccess:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
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
            ("server_error", 500, False, 500, "GitBook returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(gitbook, "make_tracked_session", return_value=self._session(response)):
            assert check_access("gb-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(gitbook, "make_tracked_session", return_value=session):
            status, message = check_access("gb-token")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid GitBook API token"),
            ("forbidden", 403, False, "Invalid GitBook API token"),
            ("server_error", 500, False, "GitBook returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(gitbook, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("gb-token") == (expected_valid, expected_message)


class TestGitBookSourceResponse:
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
    def test_source_response_shape(self, endpoint: str, expected_primary_keys: list[str]) -> None:
        response = gitbook_source(
            api_token="gb-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
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
