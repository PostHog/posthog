from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.rss import rss
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.rss import (
    PAGE_SIZE,
    RssResumeConfig,
    RssRetryableError,
    check_access,
    get_rows,
    rss_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.settings import ENDPOINTS, RSS_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_list_unwrapped = rss._fetch_list.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: RssResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RssResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RssResumeConfig | None:
        return self._state

    def save_state(self, data: RssResumeConfig) -> None:
        self.saved.append(data)


def _episodes(start_id: int, count: int) -> list[dict]:
    return [{"id": start_id + i, "title": f"ep {start_id + i}"} for i in range(count)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[tuple[str, int | None], list[dict]],
        endpoint: str,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], logger: Any) -> list[dict]:
            calls.append({"path": path, "params": params})
            return pages[(path, params.get("page"))]

        monkeypatch.setattr(rss, "_fetch_list", fake_fetch)
        monkeypatch.setattr(rss, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="rss-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows, calls

    def test_unpaginated_endpoints_are_a_single_request(self, monkeypatch: Any) -> None:
        # parameterized.expand doesn't compose with pytest fixtures, so loop instead.
        for endpoint, path in (("podcasts", "/podcasts"), ("categories", "/categories")):
            manager = _FakeResumableManager()
            rows, calls = self._collect(manager, monkeypatch, {(path, None): [{"id": 1}, {"id": 2}]}, endpoint)
            assert rows == [{"id": 1}, {"id": 2}]
            assert calls == [{"path": path, "params": {}}]
            assert manager.saved == []

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, {("/podcasts", None): []}, "podcasts")
        assert rows == []

    def test_episodes_fan_out_injects_podcast_id_into_every_row(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/podcasts", None): [{"id": 1}, {"id": 2}],
            ("/podcasts/1/episodes", 1): _episodes(10, 2),
            ("/podcasts/2/episodes", 1): _episodes(20, 1),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "episodes")
        assert [(r["podcast_id"], r["id"]) for r in rows] == [(1, 10), (1, 11), (2, 20)]
        # Each finished podcast is marked completed so a resumed sync never re-walks it.
        assert [s.completed_podcast_ids for s in manager.saved] == [[1], [1, 2]]

    def test_episodes_paginate_with_stable_oldest_order_and_save_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/podcasts", None): [{"id": 7}],
            ("/podcasts/7/episodes", 1): _episodes(0, PAGE_SIZE),
            ("/podcasts/7/episodes", 2): _episodes(PAGE_SIZE, 3),
        }
        rows, calls = self._collect(manager, monkeypatch, pages, "episodes")
        assert len(rows) == PAGE_SIZE + 3
        episode_calls = [c for c in calls if c["path"] == "/podcasts/7/episodes"]
        assert all(c["params"]["order"] == "oldest" and c["params"]["limit"] == PAGE_SIZE for c in episode_calls)
        # Page-cursor state is saved after the full first page, then the podcast is marked complete.
        assert [(s.current_podcast_id, s.next_page, s.completed_podcast_ids) for s in manager.saved] == [
            (7, 2, []),
            (None, 1, [7]),
        ]

    def test_episodes_resume_skips_completed_podcasts_and_resumes_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(RssResumeConfig(completed_podcast_ids=[1], current_podcast_id=2, next_page=3))
        # Pages 1 and 2 of podcast 2 (and all of podcast 1) must never be re-fetched on resume.
        pages = {
            ("/podcasts", None): [{"id": 1}, {"id": 2}],
            ("/podcasts/2/episodes", 3): _episodes(30, 1),
        }
        rows, calls = self._collect(manager, monkeypatch, pages, "episodes")
        assert [(r["podcast_id"], r["id"]) for r in rows] == [(2, 30)]
        assert all(c["path"] != "/podcasts/1/episodes" for c in calls)

    def test_episodes_resume_page_only_applies_to_the_podcast_in_flight(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(RssResumeConfig(completed_podcast_ids=[], current_podcast_id=1, next_page=2))
        pages = {
            ("/podcasts", None): [{"id": 1}, {"id": 2}],
            ("/podcasts/1/episodes", 2): _episodes(10, 1),
            ("/podcasts/2/episodes", 1): _episodes(20, 1),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "episodes")
        assert [(r["podcast_id"], r["id"]) for r in rows] == [(1, 10), (2, 20)]

    def test_episodes_no_podcasts_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, calls = self._collect(manager, monkeypatch, {("/podcasts", None): []}, "episodes")
        assert rows == []
        assert calls == [{"path": "/podcasts", "params": {}}]


class TestFetchList:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
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
        with pytest.raises(RssRetryableError):
            _fetch_list_unwrapped(session, "/podcasts", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("payment_required", 402), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_list_unwrapped(session, "/podcasts", {}, MagicMock())

    def test_success_returns_list(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        assert _fetch_list_unwrapped(session, "/podcasts", {}, MagicMock()) == [{"id": 1}]

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"message": "unexpected"})
        with pytest.raises(RssRetryableError):
            _fetch_list_unwrapped(session, "/podcasts", {}, MagicMock())

    def test_params_are_forwarded(self) -> None:
        session = self._session_returning(200, [])
        _fetch_list_unwrapped(
            session, "/podcasts/1/episodes", {"page": 2, "limit": 100, "order": "oldest"}, MagicMock()
        )
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 2, "limit": 100, "order": "oldest"}


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
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
            ("payment_required", 402, False, 402, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "RSS.com returned HTTP 500"),
        ]
    )
    @patch(f"{rss.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("rss-key") == (expected_status, expected_message)

    @patch(f"{rss.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("rss-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid RSS.com API key"),
            ("forbidden", 403, False, "Invalid RSS.com API key"),
            (
                "payment_required",
                402,
                False,
                "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect.",
            ),
            ("server_error", 500, False, "RSS.com returned HTTP 500"),
        ]
    )
    @patch(f"{rss.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("rss-key") == (expected_valid, expected_message)


class TestRssSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = rss_source(
            api_key="rss-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == RSS_ENDPOINTS[endpoint].primary_keys
        # Episodes carry no stable creation timestamp (only mutable publish/schedule fields), so we
        # don't partition any endpoint.
        assert response.partition_mode is None

    def test_episodes_key_includes_parent_id(self) -> None:
        # Fan-out child rows aggregate every podcast's episodes into one table; the spec doesn't
        # document episode ids as globally unique, so the key must include the parent id.
        assert RSS_ENDPOINTS["episodes"].primary_keys == ["podcast_id", "id"]
