from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix import humanitix
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix import (
    PAGE_SIZE,
    HumanitixResumeConfig,
    HumanitixRetryableError,
    check_access,
    get_rows,
    humanitix_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import (
    ENDPOINTS,
    HUMANITIX_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = humanitix._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: HumanitixResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HumanitixResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HumanitixResumeConfig | None:
        return self._state

    def save_state(self, data: HumanitixResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], total: int, page: int = 1, list_key: str = "events") -> dict[str, Any]:
    return {"total": total, "page": page, "pageSize": PAGE_SIZE, list_key: items}


def _rows(count: int) -> list[dict]:
    return [{"_id": f"id-{i}"} for i in range(count)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "events"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, page_size: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(humanitix, "_fetch_page", fake_fetch)
        monkeypatch.setattr(humanitix, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="hmtx-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page(_rows(2), total=2)})
        assert rows == _rows(2)
        # A short final page means no further pages, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_total_reached(self, monkeypatch: Any) -> None:
        # Two full pages exactly cover the total; a full page whose running count hits total ends it.
        pages = {
            1: _page(_rows(PAGE_SIZE), total=PAGE_SIZE + 1, page=1),
            2: _page(_rows(1), total=PAGE_SIZE + 1, page=2),
        }
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1

    def test_stops_on_full_page_that_reaches_total(self, monkeypatch: Any) -> None:
        # A single full page whose length equals total must terminate without fetching page 2.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page(_rows(PAGE_SIZE), total=PAGE_SIZE)})
        assert len(rows) == PAGE_SIZE
        assert manager.saved == []

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        pages = {
            1: _page(_rows(PAGE_SIZE), total=PAGE_SIZE + 1, page=1),
            2: _page(_rows(1), total=PAGE_SIZE + 1, page=2),
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(HumanitixResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume. Total spans 3 pages so page 2 (a full page)
            # doesn't hit the total-based stop, and page 3 (a short page) ends the sync.
            2: _page(_rows(PAGE_SIZE), total=2 * PAGE_SIZE + 1, page=2),
            3: _page(_rows(1), total=2 * PAGE_SIZE + 1, page=3),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1

    def test_empty_page_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([], total=0)})
        assert rows == []

    def test_uses_endpoint_specific_list_key(self, monkeypatch: Any) -> None:
        # The `tags` endpoint returns its rows under a `tags` key, not `events`.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page(_rows(1), total=1, list_key="tags")}, endpoint="tags")
        assert rows == _rows(1)


class TestFetchPage:
    def _session_returning(self, status_code: int, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body or {}
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
        with pytest.raises(HumanitixRetryableError):
            _fetch_page_unwrapped(session, "/events", 1, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/events", 1, PAGE_SIZE, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page(_rows(1), total=1)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/events", 1, PAGE_SIZE, MagicMock())
        assert result == body

    def test_request_uses_page_and_page_size_params(self) -> None:
        session = self._session_returning(200, _page([], total=0))
        _fetch_page_unwrapped(session, "/tags", 3, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "pageSize": PAGE_SIZE}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(humanitix, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Humanitix returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        session = MagicMock()
        session.get.return_value = response
        with patch.object(humanitix, "make_tracked_session", return_value=session):
            assert check_access("hmtx-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("hmtx-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestHumanitixSourceResponse:
    @parameterized.expand([("events",), ("tags",)])
    def test_source_response_uses_id_primary_key(self, endpoint: str) -> None:
        response = humanitix_source(
            api_key="hmtx-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["_id"]
        # Every endpoint is full refresh only, so there is no datetime partitioning.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # Humanitix Mongo `_id`s are globally unique, so a single `_id` key is sufficient table-wide.
        assert all(config.primary_keys == ["_id"] for config in HUMANITIX_ENDPOINTS.values())
        assert set(HUMANITIX_ENDPOINTS) == set(ENDPOINTS)
