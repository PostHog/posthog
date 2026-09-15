import json
import dataclasses
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
    BUGSNAG_ENDPOINTS,
    BugsnagResumeConfig,
    BugsnagRetryableError,
    _build_url,
    _get_headers,
    _next_offset_url,
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


def _collect_objects(
    endpoint: str,
    pages: Mapping[str, tuple[list[dict], str | None]],
    objects: Mapping[str, requests.Response],
    manager: _FakeResumableManager,
    monkeypatch: Any,
) -> list[dict]:
    """Like `_collect`, but also serves the single-object endpoints out of `objects`."""
    monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    def fake_fetch_list_page(
        session: Any, url: str, headers: Any, logger: Any, **kwargs: Any
    ) -> tuple[list[dict], str | None]:
        if url not in pages:
            raise AssertionError(f"unexpected URL requested: {url}")
        return pages[url]

    def fake_fetch_page(
        session: Any, url: str, headers: Any, logger: Any, tolerated_statuses: tuple[int, ...] = ()
    ) -> requests.Response:
        if url not in objects:
            raise AssertionError(f"unexpected object URL requested: {url}")
        return objects[url]

    monkeypatch.setattr(bugsnag, "_fetch_list_page", fake_fetch_list_page)
    monkeypatch.setattr(bugsnag, "_fetch_page", fake_fetch_page)

    rows: list[dict] = []
    for table in get_rows(
        auth_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


def _collect(
    endpoint: str,
    pages: Mapping[str, tuple[list[dict], str | None]],
    manager: _FakeResumableManager,
    monkeypatch: Any,
) -> list[dict]:
    monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    def fake_fetch_list_page(
        session: Any, url: str, headers: Any, logger: Any, **kwargs: Any
    ) -> tuple[list[dict], str | None]:
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


def _collect_via_responses(
    endpoint: str,
    responses: Mapping[str, requests.Response],
    manager: _FakeResumableManager,
    monkeypatch: Any,
) -> tuple[list[dict], list[str]]:
    """Collect rows with only the HTTP layer faked, so pagination runs for real.

    Returns (rows, requested_urls); the URL list is what proves the offset cursor and the escaped
    span group id in the path."""
    monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: MagicMock())
    requested: list[str] = []

    def fake_fetch_page(
        session: Any, url: str, headers: Any, logger: Any, tolerated_statuses: tuple[int, ...] = ()
    ) -> requests.Response:
        requested.append(url)
        if url not in responses:
            raise AssertionError(f"unexpected URL requested: {url}")
        response = responses[url]
        if not response.ok and response.status_code not in tolerated_statuses:
            raise requests.HTTPError(response=response)
        return response

    monkeypatch.setattr(bugsnag, "_fetch_page", fake_fetch_page)

    rows: list[dict] = []
    for table in get_rows(
        auth_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows, requested


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


class TestNextOffsetUrl:
    """The performance endpoints send no Link header, so the cursor is derived from the URL."""

    @parameterized.expand(
        [
            (
                "full_page_advances_offset",
                "https://api.bugsnag.com/projects/p1/span_groups?per_page=2&sort=name",
                2,
                "https://api.bugsnag.com/projects/p1/span_groups?per_page=2&sort=name&offset=2",
            ),
            (
                "existing_offset_accumulates",
                "https://api.bugsnag.com/projects/p1/span_groups?per_page=2&offset=4",
                2,
                "https://api.bugsnag.com/projects/p1/span_groups?per_page=2&offset=6",
            ),
            ("short_page_is_terminal", "https://api.bugsnag.com/projects/p1/span_groups?per_page=2", 1, None),
            ("empty_page_is_terminal", "https://api.bugsnag.com/projects/p1/span_groups?per_page=2", 0, None),
            ("no_per_page_means_unpaginated", "https://api.bugsnag.com/projects/p1/span_groups", 5, None),
        ]
    )
    def test_next_offset_url(self, _name: str, url: str, page_len: int, expected: str | None) -> None:
        assert _next_offset_url(url, page_len) == expected


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

    def test_tolerated_status_is_returned_instead_of_raising(self) -> None:
        # Fanning out a single-object endpoint reaches projects it has no data for. Those answers
        # are expected, so they must come back as a response rather than an error log plus a raise.
        not_found = _make_response(404, body={"errors": ["Project not found"]})
        session = _FakeSession([not_found])
        logger = MagicMock()
        returned = bugsnag._fetch_page(
            session,  # type: ignore[arg-type]
            "https://api.bugsnag.com/x",
            {},
            logger,
            tolerated_statuses=(404,),
        )
        assert returned is not_found
        logger.error.assert_not_called()

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

    def _collect_with_pages(
        self,
        endpoint: str,
        pages: Mapping[str, tuple[list[dict], str | None] | Exception],
        manager: _FakeResumableManager,
        monkeypatch: Any,
    ) -> list[dict]:
        # Like `_collect`, but a page value may be an Exception to raise instead of a (items, next)
        # tuple — used to drive the graceful-stop-on-422 pagination path.
        monkeypatch.setattr(bugsnag, "make_tracked_session", lambda *args, **kwargs: MagicMock())

        def fake_fetch_list_page(
            session: Any, url: str, headers: Any, logger: Any, **kwargs: Any
        ) -> tuple[list[dict], str | None]:
            if url not in pages:
                raise AssertionError(f"unexpected URL requested: {url}")
            page = pages[url]
            if isinstance(page, Exception):
                raise page
            return page

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

    def test_pagination_ceiling_422_stops_parent_and_continues(self, monkeypatch: Any) -> None:
        # BugSnag advertises a `next` cursor past its depth ceiling, then 422s the very cursor it
        # gave us. The sync must keep the rows already pulled from p1, stop that parent, and move on
        # to p2 — rather than failing the whole errors sync.
        p1_page2 = "https://api.bugsnag.com/projects/p1/errors?base=t&offset=500&per_page=100"
        ceiling = requests.HTTPError(response=_make_response(422))
        pages: dict[str, tuple[list[dict], str | None] | Exception] = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}, {"id": "p2"}], None),
            "https://api.bugsnag.com/projects/p1/errors?per_page=100": ([{"id": "e1"}], p1_page2),
            p1_page2: ceiling,
            "https://api.bugsnag.com/projects/p2/errors?per_page=100": ([{"id": "e2"}], None),
        }
        rows = self._collect_with_pages("errors", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "e1", "organization_id": "o1", "project_id": "p1"},
            {"id": "e2", "organization_id": "o1", "project_id": "p2"},
        ]

    def test_pagination_ceiling_422_on_first_page_propagates(self, monkeypatch: Any) -> None:
        # A 422 on a parent's first page isn't a cursor BugSnag handed us, so it must surface rather
        # than silently yielding an empty table.
        pages: dict[str, tuple[list[dict], str | None] | Exception] = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/errors?per_page=100": requests.HTTPError(response=_make_response(422)),
        }
        with pytest.raises(requests.HTTPError):
            self._collect_with_pages("errors", pages, _FakeResumableManager(), monkeypatch)

    def test_releases_caps_page_size_at_ten(self, monkeypatch: Any) -> None:
        # The releases endpoint rejects per_page above 10 with a 400, so it must request per_page=10
        # while the parent enumeration keeps the default 100. A per_page=100 releases URL is absent
        # from `pages`, so a regression would raise on the unexpected URL.
        pages = {
            "https://api.bugsnag.com/user/organizations?per_page=100": ([{"id": "o1"}], None),
            "https://api.bugsnag.com/organizations/o1/projects?per_page=100": ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/releases?per_page=10": ([{"id": "r1"}], None),
        }
        rows = _collect("releases", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": "r1", "organization_id": "o1", "project_id": "p1"}]


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


_ORGS_URL = "https://api.bugsnag.com/user/organizations?per_page=100"
_PROJECTS_URL = "https://api.bugsnag.com/organizations/o1/projects?per_page=100"


class TestStabilityTrend:
    """The endpoint answers with a single object per project rather than a list, so the connector
    flattens its nested timeline points into one row per project per day."""

    def test_flattens_timeline_points_carrying_the_object_scalars(self, monkeypatch: Any) -> None:
        pages = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}], None),
        }
        objects = {
            "https://api.bugsnag.com/projects/p1/stability_trend": _make_response(
                200,
                body={
                    "project_id": "p1",
                    "release_stage_name": "production",
                    "timeline_points": [
                        {"bucket_start": "2019-03-02T00:00:00.000Z", "total_sessions_count": 10},
                        {"bucket_start": "2019-03-03T00:00:00.000Z", "total_sessions_count": 20},
                    ],
                },
            )
        }
        rows = _collect_objects("stability_trend", pages, objects, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "project_id": "p1",
                "release_stage_name": "production",
                "bucket_start": "2019-03-02T00:00:00.000Z",
                "total_sessions_count": 10,
                "organization_id": "o1",
            },
            {
                "project_id": "p1",
                "release_stage_name": "production",
                "bucket_start": "2019-03-03T00:00:00.000Z",
                "total_sessions_count": 20,
                "organization_id": "o1",
            },
        ]

    @parameterized.expand([("no_sessions_yet", 204), ("no_primary_release_stage", 404)])
    def test_project_without_stability_data_is_skipped(self, _name: str, status_code: int) -> None:
        # Every project is fanned out over, including ones the endpoint has nothing for. Those
        # answers must produce no rows instead of failing the whole table's sync.
        pages = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}, {"id": "p2"}], None),
        }
        objects = {
            "https://api.bugsnag.com/projects/p1/stability_trend": _make_response(status_code),
            "https://api.bugsnag.com/projects/p2/stability_trend": _make_response(
                200,
                body={"project_id": "p2", "timeline_points": [{"bucket_start": "2019-03-02T00:00:00.000Z"}]},
            ),
        }
        with pytest.MonkeyPatch.context() as mp:
            rows = _collect_objects("stability_trend", pages, objects, _FakeResumableManager(), mp)
        assert rows == [{"bucket_start": "2019-03-02T00:00:00.000Z", "project_id": "p2", "organization_id": "o1"}]


class TestProjectTrend:
    def test_requests_fixed_width_buckets_and_no_per_page(self, monkeypatch: Any) -> None:
        # The endpoint takes no per_page and rejects a request carrying neither `resolution` nor
        # `buckets_count`; a URL that drifts from this shape is absent from `pages` and raises.
        pages: dict[str, tuple[list[dict], str | None]] = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/trend?resolution=12h": (
                [{"from": "2017-04-03T22:43:49Z", "to": "2017-04-04T10:43:49Z", "events_count": 3}],
                None,
            ),
        }
        rows = _collect("trend", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "from": "2017-04-03T22:43:49Z",
                "to": "2017-04-04T10:43:49Z",
                "events_count": 3,
                "organization_id": "o1",
                "project_id": "p1",
            }
        ]


class TestReleaseGroups:
    def test_fans_out_once_per_release_stage(self, monkeypatch: Any) -> None:
        # The stage is a required query parameter, and a project can have several, so each stage
        # is its own fan-out parent.
        pages: dict[str, tuple[list[dict], str | None]] = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1", "release_stages": ["production", "staging"]}], None),
            "https://api.bugsnag.com/projects/p1/release_groups?per_page=30&release_stage_name=production": (
                [{"id": "rg1"}],
                None,
            ),
            "https://api.bugsnag.com/projects/p1/release_groups?per_page=30&release_stage_name=staging": (
                [{"id": "rg2"}],
                None,
            ),
        }
        rows = _collect("release_groups", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "rg1", "organization_id": "o1", "project_id": "p1"},
            {"id": "rg2", "organization_id": "o1", "project_id": "p1"},
        ]

    def test_release_stage_count_is_capped_per_project(self, monkeypatch: Any) -> None:
        # Release stages come from client-reported event data, so a project can accumulate any
        # number of them and each is a paginated collection. Only the capped prefix is requested —
        # the stage past the cap is absent from `pages`, so requesting it would raise.
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["release_groups"], max_parents_per_project=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "release_groups", capped)
        base = "https://api.bugsnag.com/projects/p1/release_groups?per_page=30&release_stage_name="
        pages: dict[str, tuple[list[dict], str | None]] = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1", "release_stages": ["s1", "s2", "s3"]}], None),
            f"{base}s1": ([{"id": "rg1"}], None),
            f"{base}s2": ([{"id": "rg2"}], None),
        }
        rows = _collect("release_groups", pages, _FakeResumableManager(), monkeypatch)
        assert [row["id"] for row in rows] == ["rg1", "rg2"]

    def test_project_without_release_stages_is_skipped(self, monkeypatch: Any) -> None:
        # A project that has seen no events has no stages, and the endpoint rejects a request
        # without one — so it must not be requested at all.
        pages: dict[str, tuple[list[dict], str | None]] = {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}, {"id": "p2", "release_stages": []}], None),
        }
        rows = _collect("release_groups", pages, _FakeResumableManager(), monkeypatch)
        assert rows == []


class TestPivotValues:
    def _pivot_pages(self) -> dict[str, tuple[list[dict], str | None]]:
        return {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/pivots?per_page=100": (
                [{"event_field_display_id": "app.release_stage"}],
                None,
            ),
        }

    def test_fans_out_over_project_pivots_and_injects_the_display_id(self, monkeypatch: Any) -> None:
        # The display id only exists in the request path, so without injection the rows could not be
        # told apart per pivot and the primary key would collapse.
        pages = self._pivot_pages()
        pages["https://api.bugsnag.com/projects/p1/pivots/app.release_stage/values?per_page=30&sort=unsorted"] = (
            [{"event_field_value": "production", "events": 23}],
            None,
        )
        rows = _collect("pivot_values", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "event_field_value": "production",
                "events": 23,
                "organization_id": "o1",
                "project_id": "p1",
                "event_field_display_id": "app.release_stage",
            }
        ]

    def test_page_cap_stops_a_high_cardinality_pivot(self, monkeypatch: Any) -> None:
        # A pivot over a field like user id has a value per user, and the API keeps handing out
        # cursors. The cap must stop that parent — the third page is absent from `pages`, so
        # following it would raise.
        values_url = "https://api.bugsnag.com/projects/p1/pivots/app.release_stage/values?per_page=30&sort=unsorted"
        page2 = f"{values_url}&offset=2"
        pages = self._pivot_pages()
        pages[values_url] = ([{"event_field_value": "v1"}], page2)
        pages[page2] = ([{"event_field_value": "v2"}], f"{values_url}&offset=3")

        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["pivot_values"], max_pages=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "pivot_values", capped)

        rows = _collect("pivot_values", pages, _FakeResumableManager(), monkeypatch)
        assert [row["event_field_value"] for row in rows] == ["v1", "v2"]


class TestErrorTrend:
    def _error_pages(self, errors: list[dict], per_page: int) -> dict[str, tuple[list[dict], str | None]]:
        return {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}], None),
            f"https://api.bugsnag.com/projects/p1/errors?per_page={per_page}": (errors, None),
        }

    def test_fans_out_per_error_injecting_the_error_id(self, monkeypatch: Any) -> None:
        # The error id only exists in the request path, so without injection every error's buckets
        # would collapse onto the same primary key.
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["error_trend"], max_errors_per_project=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "error_trend", capped)
        pages = self._error_pages([{"id": "e1"}, {"id": "e2"}], per_page=3)
        bucket = {"from": "2017-04-03T22:43:49Z", "to": "2017-04-04T10:43:49Z", "events_count": 3}
        for error_id in ("e1", "e2"):
            pages[f"https://api.bugsnag.com/projects/p1/errors/{error_id}/trend?resolution=12h"] = ([bucket], None)

        rows = _collect("error_trend", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {**bucket, "organization_id": "o1", "project_id": "p1", "error_id": "e1"},
            {**bucket, "organization_id": "o1", "project_id": "p1", "error_id": "e2"},
        ]

    def test_error_count_is_capped_per_project(self, monkeypatch: Any) -> None:
        # One request per error with no server-side filter to narrow the list, so the cap is the
        # only thing bounding the table. The third error's trend URL is absent from `pages`, so
        # fanning out over it would raise.
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["error_trend"], max_errors_per_project=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "error_trend", capped)
        pages = self._error_pages([{"id": "e1"}, {"id": "e2"}, {"id": "e3"}], per_page=3)
        for error_id in ("e1", "e2"):
            pages[f"https://api.bugsnag.com/projects/p1/errors/{error_id}/trend?resolution=12h"] = (
                [{"from": "2017-04-03T22:43:49Z", "events_count": 1}],
                None,
            )

        rows = _collect("error_trend", pages, _FakeResumableManager(), monkeypatch)
        assert [row["error_id"] for row in rows] == ["e1", "e2"]

    def test_error_deleted_between_listing_and_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        # A long sync can reach an error that was merged or deleted after the listing; its 404 must
        # produce no rows rather than fail the whole table.
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["error_trend"], max_errors_per_project=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "error_trend", capped)
        responses = {
            _ORGS_URL: _make_response(200, body=[{"id": "o1"}]),
            _PROJECTS_URL: _make_response(200, body=[{"id": "p1"}]),
            "https://api.bugsnag.com/projects/p1/errors?per_page=3": _make_response(
                200, body=[{"id": "e1"}, {"id": "e2"}]
            ),
            "https://api.bugsnag.com/projects/p1/errors/e1/trend?resolution=12h": _make_response(
                404, body={"errors": ["Error not found"]}
            ),
            "https://api.bugsnag.com/projects/p1/errors/e2/trend?resolution=12h": _make_response(
                200, body=[{"from": "2017-04-03T22:43:49Z", "events_count": 1}]
            ),
        }
        rows, _requested = _collect_via_responses("error_trend", responses, _FakeResumableManager(), monkeypatch)
        assert [row["error_id"] for row in rows] == ["e2"]


class TestErrorPivotValues:
    def _pages(self, errors: list[dict], per_page: int) -> dict[str, tuple[list[dict], str | None]]:
        return {
            _ORGS_URL: ([{"id": "o1"}], None),
            _PROJECTS_URL: ([{"id": "p1"}], None),
            "https://api.bugsnag.com/projects/p1/pivots?per_page=100": (
                [{"event_field_display_id": "app.release_stage"}, {"event_field_display_id": "user.id"}],
                None,
            ),
            f"https://api.bugsnag.com/projects/p1/errors?per_page={per_page}": (errors, None),
        }

    def _values_url(self, error_id: str, display_id: str) -> str:
        return (
            f"https://api.bugsnag.com/projects/p1/errors/{error_id}/pivots/{display_id}"
            "/values?per_page=30&sort=unsorted"
        )

    def test_crosses_errors_with_pivots_and_injects_both_ids(self, monkeypatch: Any) -> None:
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["error_pivot_values"], max_errors_per_project=1)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "error_pivot_values", capped)
        pages = self._pages([{"id": "e1"}], per_page=2)
        for display_id in ("app.release_stage", "user.id"):
            pages[self._values_url("e1", display_id)] = ([{"event_field_value": "production"}], None)

        rows = _collect("error_pivot_values", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "event_field_value": "production",
                "organization_id": "o1",
                "project_id": "p1",
                "error_id": "e1",
                "event_field_display_id": "app.release_stage",
            },
            {
                "event_field_value": "production",
                "organization_id": "o1",
                "project_id": "p1",
                "error_id": "e1",
                "event_field_display_id": "user.id",
            },
        ]

    def test_error_pivot_product_is_capped_per_project(self, monkeypatch: Any) -> None:
        # Every (error, pivot) pair is its own paginated request, so the product needs a cap of its
        # own on top of the error cap. The fourth pair's URL is absent from `pages`, so requesting
        # it would raise.
        capped = dataclasses.replace(
            BUGSNAG_ENDPOINTS["error_pivot_values"], max_errors_per_project=2, max_parents_per_project=3
        )
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "error_pivot_values", capped)
        pages = self._pages([{"id": "e1"}, {"id": "e2"}], per_page=3)
        for error_id, display_id in (("e1", "app.release_stage"), ("e1", "user.id"), ("e2", "app.release_stage")):
            pages[self._values_url(error_id, display_id)] = ([{"event_field_value": f"{error_id}:{display_id}"}], None)

        rows = _collect("error_pivot_values", pages, _FakeResumableManager(), monkeypatch)
        assert [row["event_field_value"] for row in rows] == [
            "e1:app.release_stage",
            "e1:user.id",
            "e2:app.release_stage",
        ]


class TestSpanGroups:
    """The performance endpoints page by a numeric offset and send no Link header, so these tests
    fake only the HTTP layer and let the real paginator derive its own cursors."""

    def test_follows_the_offset_cursor_until_a_short_page(self, monkeypatch: Any) -> None:
        paged = dataclasses.replace(BUGSNAG_ENDPOINTS["span_groups"], page_size=2)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "span_groups", paged)
        page1 = "https://api.bugsnag.com/projects/p1/span_groups?per_page=2&sort=name&direction=asc"
        page2 = f"{page1}&offset=2"
        responses = {
            _ORGS_URL: _make_response(200, body=[{"id": "o1"}]),
            _PROJECTS_URL: _make_response(200, body=[{"id": "p1"}]),
            page1: _make_response(200, body=[{"id": "1.app_start.Cold"}, {"id": "1.network.GET"}]),
            page2: _make_response(200, body=[{"id": "1.page_load./home"}]),
        }
        rows, requested = _collect_via_responses("span_groups", responses, _FakeResumableManager(), monkeypatch)
        assert [row["id"] for row in rows] == ["1.app_start.Cold", "1.network.GET", "1.page_load./home"]
        assert requested[-2:] == [page1, page2]


class TestSpanGroupSpans:
    def test_escapes_the_span_group_id_into_the_path_and_injects_the_raw_id(self, monkeypatch: Any) -> None:
        # A span group id is `{version}.{category}.{name}` and the name can carry slashes, so an
        # unescaped id would address a different route entirely. The row keeps the raw id, which is
        # what joins these spans back to the span_groups table.
        group_id = "1.app_start.AppStart/Cold"
        spans_url = (
            "https://api.bugsnag.com/projects/p1/span_groups/1.app_start.AppStart%2FCold"
            "/spans?per_page=100&sort=timestamp&direction=desc"
        )
        responses = {
            _ORGS_URL: _make_response(200, body=[{"id": "o1"}]),
            _PROJECTS_URL: _make_response(200, body=[{"id": "p1"}]),
            "https://api.bugsnag.com/projects/p1/span_groups?per_page=100&sort=name&direction=asc": _make_response(
                200, body=[{"id": group_id}]
            ),
            spans_url: _make_response(200, body=[{"id": "s1", "duration": 1000}]),
        }
        rows, requested = _collect_via_responses("span_group_spans", responses, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "id": "s1",
                "duration": 1000,
                "organization_id": "o1",
                "project_id": "p1",
                "span_group_id": group_id,
            }
        ]
        assert spans_url in requested

    def test_span_group_count_is_capped_per_project(self, monkeypatch: Any) -> None:
        # Each span group costs a request, and a project accumulates one per grouped operation. The
        # second group's spans URL is absent from `responses`, so fanning out over it would raise.
        capped = dataclasses.replace(BUGSNAG_ENDPOINTS["span_group_spans"], max_parents_per_project=1)
        monkeypatch.setitem(BUGSNAG_ENDPOINTS, "span_group_spans", capped)
        responses = {
            _ORGS_URL: _make_response(200, body=[{"id": "o1"}]),
            _PROJECTS_URL: _make_response(200, body=[{"id": "p1"}]),
            "https://api.bugsnag.com/projects/p1/span_groups?per_page=100&sort=name&direction=asc": _make_response(
                200, body=[{"id": "1.app_start.Cold"}, {"id": "1.network.GET"}]
            ),
            (
                "https://api.bugsnag.com/projects/p1/span_groups/1.app_start.Cold"
                "/spans?per_page=100&sort=timestamp&direction=desc"
            ): _make_response(200, body=[{"id": "s1"}]),
        }
        rows, _requested = _collect_via_responses("span_group_spans", responses, _FakeResumableManager(), monkeypatch)
        assert [row["span_group_id"] for row in rows] == ["1.app_start.Cold"]
