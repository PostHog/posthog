import json
from collections.abc import Mapping
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag import bugsnag
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.bugsnag import (
    BUGSNAG_BASE_URL,
    BugsnagResumeConfig,
    BugsnagRetryableError,
    _build_url,
    _get_headers,
    _parse_next_url,
    get_rows,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: BugsnagResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BugsnagResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BugsnagResumeConfig | None:
        return self._state

    def save_state(self, data: BugsnagResumeConfig) -> None:
        self.saved.append(data)


def _make_response(status_code: int, body: Any = None, link: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if link is not None:
        response.headers["Link"] = link
    if body is not None:
        response._content = json.dumps(body).encode()
    return response


class _FakeSession:
    """Returns queued responses in order, recording the URLs requested."""

    def __init__(self, responses: list[requests.Response]) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> requests.Response:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _collect(
    endpoint: str,
    pages: Mapping[str, tuple[list[dict], str | None]],
    manager: _FakeResumableManager,
    monkeypatch: Any,
) -> list[dict]:
    monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    def fake_fetch_list_page(session: Any, url: str, headers: Any, logger: Any) -> tuple[list[dict], str | None]:
        if url not in pages:
            raise AssertionError(f"unexpected URL requested: {url}")
        return pages[url]

    monkeypatch.setattr(bugsnag, "_fetch_list_page", fake_fetch_list_page)

    rows: list[dict] = []
    for table in get_rows(
        auth_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestParseNextUrl:
    @parameterized.expand(
        [
            (
                "single_next",
                '<https://api.bugsnag.com/projects/p1/errors?offset=abc>; rel="next"',
                "https://api.bugsnag.com/projects/p1/errors?offset=abc",
            ),
            (
                "next_among_others",
                '<https://api.bugsnag.com/x?o=1>; rel="prev", <https://api.bugsnag.com/x?o=2>; rel="next"',
                "https://api.bugsnag.com/x?o=2",
            ),
            ("no_next", '<https://api.bugsnag.com/x?o=1>; rel="prev"', None),
            ("empty", "", None),
        ]
    )
    def test_parse_next_url(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_url(header) == expected


class TestHelpers:
    def test_get_headers_sets_token_and_version(self) -> None:
        headers = _get_headers("tok_123")
        assert headers["Authorization"] == "token tok_123"
        assert headers["X-Version"] == "2"

    def test_build_url_encodes_params(self) -> None:
        assert _build_url(f"{BUGSNAG_BASE_URL}/user/organizations", {"per_page": 100}) == (
            "https://api.bugsnag.com/user/organizations?per_page=100"
        )

    def test_build_url_no_params(self) -> None:
        assert _build_url("https://api.bugsnag.com/x", {}) == "https://api.bugsnag.com/x"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = _FakeSession([_make_response(status_code) for _ in range(5)])
        # tenacity exposes retry_with on the decorated callable to rebuild it with different
        # retry settings; here we drop the backoff so the test doesn't actually sleep.
        fast_fetch = bugsnag._fetch_page.retry_with(wait=wait_none(), stop=stop_after_attempt(3))  # type: ignore[attr-defined]
        with pytest.raises(BugsnagRetryableError):
            fast_fetch(session, "https://api.bugsnag.com/x", {}, MagicMock())

    def test_client_error_raises_http_error_without_retry(self) -> None:
        session = _FakeSession([_make_response(404, body={"errors": ["Not Found"]})])
        with pytest.raises(requests.HTTPError):
            bugsnag._fetch_page(session, "https://api.bugsnag.com/x", {}, MagicMock())  # type: ignore[arg-type]
        # 404 is not retryable, so only one request is made.
        assert len(session.requested_urls) == 1

    def test_ok_response_returned(self) -> None:
        ok = _make_response(200, body=[{"id": "o1"}])
        session = _FakeSession([ok])
        assert bugsnag._fetch_page(session, "https://api.bugsnag.com/x", {}, MagicMock()) is ok  # type: ignore[arg-type]


class TestTopLevelOrganizations:
    def test_paginates_following_link_header(self, monkeypatch: Any) -> None:
        page1 = "https://api.bugsnag.com/user/organizations?per_page=100"
        page2 = "https://api.bugsnag.com/user/organizations?offset=2"
        pages = {
            page1: ([{"id": "o1"}], page2),
            page2: ([{"id": "o2"}], None),
        }
        rows = _collect("organizations", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": "o1"}, {"id": "o2"}]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        page2 = "https://api.bugsnag.com/user/organizations?offset=2"
        pages = {page2: ([{"id": "o2"}], None)}
        manager = _FakeResumableManager(BugsnagResumeConfig(next_url=page2))
        rows = _collect("organizations", pages, manager, monkeypatch)
        assert rows == [{"id": "o2"}]


class TestPerOrgFanOut:
    def test_injects_organization_id(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}, {"id": "p2"}], None),
        }
        rows = _collect("projects", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "p1", "organization_id": "o1"},
            {"id": "p2", "organization_id": "o1"},
        ]


class TestPerProjectFanOut:
    def _two_project_pages(self) -> dict[str, tuple[list[dict], str | None]]:
        return {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}, {"id": "p2"}], None),
            "https://api.bugsnag.com/projects/p1/errors?per_page=100": ([{"id": "e1"}], None),
            "https://api.bugsnag.com/projects/p2/errors?per_page=100": ([{"id": "e2"}], None),
        }

    def test_walks_org_then_project_and_injects_both_ids(self, monkeypatch: Any) -> None:
        rows = _collect("errors", self._two_project_pages(), _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "e1", "organization_id": "o1", "project_id": "p1"},
            {"id": "e2", "organization_id": "o1", "project_id": "p2"},
        ]

    def test_follows_child_pagination(self, monkeypatch: Any) -> None:
        next_url = "https://api.bugsnag.com/projects/p1/errors?offset=2"
        pages = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/errors?per_page=100": ([{"id": "e1"}], next_url),
            next_url: ([{"id": "e2"}], None),
        }
        rows = _collect("errors", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "e1", "organization_id": "o1", "project_id": "p1"},
            {"id": "e2", "organization_id": "o1", "project_id": "p1"},
        ]

    def test_no_bookmark_advanced_across_parents_without_a_yield(self, monkeypatch: Any) -> None:
        # Small syncs never fill the batcher, so nothing is checkpointed — and crucially the bookmark
        # is never advanced at parent boundaries. Advancing it there (the old behavior) would skip
        # rows still buffered in the shared batcher if a crash hit between parents.
        manager = _FakeResumableManager()
        _collect("errors", self._two_project_pages(), manager, monkeypatch)
        assert manager.saved == []

    def test_resume_refetches_checkpointed_page_then_continues(self, monkeypatch: Any) -> None:
        # A checkpoint points at the CURRENT page of the in-flight parent; resume re-fetches that
        # page (merge dedupes already-yielded rows) and then proceeds to later parents.
        p1_page2 = "https://api.bugsnag.com/projects/p1/errors?offset=2"
        pages = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}, {"id": "p2"}], None),
            p1_page2: ([{"id": "e1b"}], None),
            "https://api.bugsnag.com/projects/p2/errors?per_page=100": ([{"id": "e2"}], None),
        }
        manager = _FakeResumableManager(BugsnagResumeConfig(next_url=p1_page2, parent_id="p1"))
        rows = _collect("errors", pages, manager, monkeypatch)
        assert rows == [
            {"id": "e1b", "organization_id": "o1", "project_id": "p1"},
            {"id": "e2", "organization_id": "o1", "project_id": "p2"},
        ]

    def test_resume_skips_already_processed_parents(self, monkeypatch: Any) -> None:
        # Bookmarked at p2: p1 must not be re-fetched (its errors URL is absent from `pages`, so a
        # fetch would raise), only p2's rows are produced.
        pages = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}, {"id": "p2"}], None),
            "https://api.bugsnag.com/projects/p2/errors?per_page=100": ([{"id": "e2"}], None),
        }
        manager = _FakeResumableManager(BugsnagResumeConfig(next_url=None, parent_id="p2"))
        rows = _collect("errors", pages, manager, monkeypatch)
        assert rows == [{"id": "e2", "organization_id": "o1", "project_id": "p2"}]

    def test_resume_from_deleted_parent_restarts_from_first(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(BugsnagResumeConfig(next_url=None, parent_id="GONE"))
        rows = _collect("errors", self._two_project_pages(), manager, monkeypatch)
        assert rows == [
            {"id": "e1", "organization_id": "o1", "project_id": "p1"},
            {"id": "e2", "organization_id": "o1", "project_id": "p2"},
        ]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        session = _FakeSession([_make_response(status_code, body=[])])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: session)
            ok, _error = validate_credentials("tok")
        assert ok is expected_ok

    def test_request_exception_is_failure(self, monkeypatch: Any) -> None:
        class _BoomSession:
            def get(self, *args: Any, **kwargs: Any) -> requests.Response:
                raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: _BoomSession())
        ok, error = validate_credentials("tok")
        assert ok is False
        assert error is not None


class TestTokenRedaction:
    """The token rides in a custom `Authorization: token …` scheme the tracked transport's
    scrubber doesn't recognise, so every session it builds must redact the token by value."""

    def test_validate_credentials_redacts_token(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeSession([_make_response(200, body=[])])

        monkeypatch.setattr(bugsnag, "make_tracked_session", fake_make_session)
        validate_credentials("super-secret-token")
        assert captured.get("redact_values") == ("super-secret-token",)

    def test_get_rows_redacts_token(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(bugsnag, "make_tracked_session", fake_make_session)
        monkeypatch.setattr(bugsnag, "_fetch_list_page", lambda *args, **kwargs: ([], None))
        list(
            get_rows(
                auth_token="super-secret-token",
                endpoint="organizations",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert captured.get("redact_values") == ("super-secret-token",)
