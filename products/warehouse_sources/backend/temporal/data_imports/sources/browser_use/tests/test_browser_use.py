from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use import browser_use
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use import (
    BrowserUseResumeConfig,
    browser_use_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import BROWSER_USE_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: BrowserUseResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BrowserUseResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BrowserUseResumeConfig | None:
        return self._state

    def save_state(self, data: BrowserUseResumeConfig) -> None:
        self.saved.append(data)


def _run(endpoint: str, fetch: Any, manager: _FakeResumableManager | None = None) -> list[dict]:
    manager = manager or _FakeResumableManager()
    rows: list[dict] = []
    with patch.object(browser_use, "make_tracked_session", return_value=MagicMock()):
        with patch.object(browser_use, "_fetch_page", side_effect=fetch):
            for batch in get_rows(
                api_key="bu_test",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            ):
                rows.extend(batch)
    return rows


def _paged_fetch(data_key: str, page_param: str, pages: list[list[dict]], include_total: bool):
    """A fetch stub that returns the page indexed by the request's page/pageNumber param."""
    requested: list[int] = []
    total = sum(len(p) for p in pages)

    def fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
        qs = parse_qs(urlparse(url).query)
        page = int(qs[page_param][0])
        requested.append(page)
        items = pages[page - 1] if page - 1 < len(pages) else []
        body: dict = {data_key: items}
        if include_total:
            body["total" if page_param == "page" else "totalItems"] = total
        return body

    fetch.requested = requested  # type: ignore[attr-defined]
    return fetch


class TestPagination:
    @parameterized.expand(
        [
            ("sessions", "sessions", "page"),
            ("browser_sessions", "items", "pageNumber"),
            ("profiles", "items", "pageNumber"),
            ("workspaces", "items", "pageNumber"),
        ]
    )
    def test_all_pages_aggregated_and_terminates(self, endpoint: str, data_key: str, page_param: str) -> None:
        # Two full pages (100 each) then a short page: guards both that every page is collected and
        # that a short page terminates the loop instead of paging forever.
        size = BROWSER_USE_ENDPOINTS[endpoint].page_size
        pages = [
            [{"id": f"a{i}"} for i in range(size)],
            [{"id": f"b{i}"} for i in range(size)],
            [{"id": "c0"}, {"id": "c1"}],
        ]
        fetch = _paged_fetch(data_key, page_param, pages, include_total=False)
        rows = _run(endpoint, fetch)

        assert len(rows) == size * 2 + 2
        assert fetch.requested == [1, 2, 3]

    def test_total_stops_before_an_empty_page(self) -> None:
        # A full final page whose count equals `total` must not trigger one more (empty) request.
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        pages = [[{"id": f"a{i}"} for i in range(size)], [{"id": "b0"}]]
        fetch = _paged_fetch("sessions", "page", pages, include_total=True)
        rows = _run("sessions", fetch)

        assert len(rows) == size + 1
        assert fetch.requested == [1, 2]

    def test_correct_pagination_param_sent(self) -> None:
        # /browsers uses pageNumber/pageSize, not page/page_size — sending the wrong name would
        # silently return page 1 forever (or 422).
        seen: list[str] = []

        def fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
            seen.append(urlparse(url).query)
            return {"items": []}

        _run("browser_sessions", fetch)
        assert "pageNumber=1" in seen[0]
        assert "pageSize=100" in seen[0]

    def test_state_saved_after_each_yield(self) -> None:
        # Resume state must advance to the NEXT page and only be saved when more pages remain, so a
        # crash re-yields the last page rather than skipping it.
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        pages = [[{"id": f"a{i}"} for i in range(size)], [{"id": "b0"}]]
        fetch = _paged_fetch("sessions", "page", pages, include_total=False)
        manager = _FakeResumableManager()
        _run("sessions", fetch, manager)

        # Only the first (full) page has a successor, so exactly one save advancing to page 2.
        assert [s.page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self) -> None:
        requested: list[int] = []

        def fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
            page = int(parse_qs(urlparse(url).query)["page"][0])
            requested.append(page)
            return {"sessions": [{"id": "p3"}] if page == 3 else []}

        manager = _FakeResumableManager(BrowserUseResumeConfig(page=3))
        rows = _run("sessions", fetch, manager)

        assert rows == [{"id": "p3"}]
        assert requested == [3]


class TestSessionMessagesFanOut:
    def _fetch(self, sessions_pages: list[list[dict]], messages_by_session: dict[str, list[list[dict]]]):
        def fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if parsed.path.endswith("/sessions"):
                page = int(qs["page"][0])
                items = sessions_pages[page - 1] if page - 1 < len(sessions_pages) else []
                return {"sessions": items}
            # /sessions/{id}/messages
            session_id = parsed.path.split("/")[-2]
            batches = messages_by_session[session_id]
            after = qs.get("after", [None])[0]
            if after is None:
                batch = batches[0]
            else:
                # Find the batch after the one ending in `after`.
                idx = next(i for i, b in enumerate(batches) if b and b[-1]["id"] == after)
                batch = batches[idx + 1] if idx + 1 < len(batches) else []
            has_more = batch != batches[-1] and bool(batch)
            return {"messages": batch, "hasMore": has_more}

        return fetch

    def test_fans_out_over_sessions_with_cursor(self) -> None:
        # Two sessions, one paginated via the `after` cursor; every message must be collected and
        # stamped with its parent session id. The raw child payload omits `sessionId`, so the source
        # has to inject it — the composite [sessionId, id] primary key depends on it being present.
        sessions_pages = [[{"id": "s1"}, {"id": "s2"}]]
        messages = {
            "s1": [
                [{"id": "m1"}, {"id": "m2"}],
                [{"id": "m3"}],
            ],
            "s2": [[{"id": "m9"}]],
        }
        rows = _run("session_messages", self._fetch(sessions_pages, messages))

        assert [r["id"] for r in rows] == ["m1", "m2", "m3", "m9"]
        assert {r["id"] for r in rows if r["sessionId"] == "s1"} == {"m1", "m2", "m3"}
        assert {r["id"] for r in rows if r["sessionId"] == "s2"} == {"m9"}

    def test_resumes_cursor_within_bookmarked_session(self) -> None:
        # The saved `after` cursor must apply only to the bookmarked session (s2 continues from m8).
        # Earlier sessions are re-walked rather than sliced away: the API has no stable ordering, so
        # skipping them would drop rows for any session that reordered ahead of the bookmark. Merge
        # dedupes the re-pulled rows downstream on the [sessionId, id] primary key.
        sessions_pages = [[{"id": "s1"}, {"id": "s2"}]]
        messages = {
            "s1": [[{"id": "m1", "sessionId": "s1"}]],
            "s2": [[{"id": "m8", "sessionId": "s2"}], [{"id": "m9", "sessionId": "s2"}]],
        }
        manager = _FakeResumableManager(BrowserUseResumeConfig(session_id="s2", after="m8"))
        rows = _run("session_messages", self._fetch(sessions_pages, messages), manager)

        assert [r["id"] for r in rows] == ["m1", "m9"]

    def test_missing_bookmark_restarts_from_first_session(self) -> None:
        # If the bookmarked session was deleted between runs, fan-out restarts (merge dedupes).
        sessions_pages = [[{"id": "s1"}]]
        messages = {"s1": [[{"id": "m1", "sessionId": "s1"}]]}
        manager = _FakeResumableManager(BrowserUseResumeConfig(session_id="gone", after="x"))
        rows = _run("session_messages", self._fetch(sessions_pages, messages), manager)

        assert [r["id"] for r in rows] == ["m1"]


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable(self, _name: str, status: int) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = False
        session = MagicMock()
        session.get.return_value = response

        with patch.object(browser_use._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(browser_use.BrowserUseRetryableError):
                browser_use._fetch_page(session, "https://api.browser-use.com/api/v3/sessions", {}, MagicMock())
        # Retried up to the 5-attempt cap before giving up.
        assert session.get.call_count == 5

    def test_client_error_raises_for_status(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            browser_use._fetch_page(session, "https://api.browser-use.com/api/v3/sessions", {}, MagicMock())
        # A credential error is terminal — no retry.
        assert session.get.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(browser_use, "make_tracked_session", return_value=session):
            assert validate_credentials("bu_test") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(browser_use, "make_tracked_session", return_value=session):
            assert validate_credentials("bu_test") is False


class TestHttpSampleCapture:
    # Every Browser Use endpoint returns free-form agent content — session titles and
    # session_messages.data hold whatever a user's agent typed or browsed, which the name-based
    # scrubbers can't recognise. So both the export path and the credential probe must build their
    # tracked session with capture=False. A regression that drops the flag (falling back to the
    # capture=True default) would serialize that tenant content into the HTTP sample bucket.
    def test_get_rows_disables_capture(self) -> None:
        session = MagicMock()
        with (
            patch.object(browser_use, "make_tracked_session", return_value=session) as mock_session,
            patch.object(browser_use, "_fetch_page", return_value={"sessions": []}),
        ):
            list(
                get_rows(
                    api_key="bu_test",
                    endpoint="sessions",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert mock_session.call_args.kwargs["capture"] is False

    def test_validate_credentials_disables_capture(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(browser_use, "make_tracked_session", return_value=session) as mock_session:
            validate_credentials("bu_test")
        assert mock_session.call_args.kwargs["capture"] is False


class TestRedirectsDisabled:
    # The API key rides in the custom X-Browser-Use-API-Key header, which requests preserves across
    # a cross-host 3xx (it only strips Authorization). Both sessions must pin allow_redirects=False
    # so the key can't replay to a redirect target; a regression that drops the flag re-opens that leak.
    def test_get_rows_disables_redirects(self) -> None:
        session = MagicMock()
        with (
            patch.object(browser_use, "make_tracked_session", return_value=session) as mock_session,
            patch.object(browser_use, "_fetch_page", return_value={"sessions": []}),
        ):
            list(
                get_rows(
                    api_key="bu_test",
                    endpoint="sessions",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_disables_redirects(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(browser_use, "make_tracked_session", return_value=session) as mock_session:
            validate_credentials("bu_test")
        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("sessions", ["id"], "createdAt"),
            ("browser_sessions", ["id"], "startedAt"),
            ("profiles", ["id"], "createdAt"),
            ("workspaces", ["id"], "createdAt"),
            ("session_messages", ["sessionId", "id"], "createdAt"),
        ]
    )
    def test_primary_keys_and_partition(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        response = browser_use_source("bu_test", endpoint, MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
