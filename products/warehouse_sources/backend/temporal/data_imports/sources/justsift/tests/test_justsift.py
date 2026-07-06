from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.justsift import justsift
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift import (
    PAGE_SIZE,
    JustSiftResumeConfig,
    JustSiftRetryableError,
    check_access,
    get_rows,
    justsift_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import (
    ENDPOINTS,
    JUSTSIFT_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = justsift._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: JustSiftResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JustSiftResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JustSiftResumeConfig | None:
        return self._state

    def save_state(self, data: JustSiftResumeConfig) -> None:
        self.saved.append(data)


def _envelope(items: list[dict], total: int | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if total is not None:
        meta["totalLength"] = total
    return {"data": items, "links": {}, "meta": meta}


def _full_page(seq: int) -> dict[str, Any]:
    # A page that is exactly PAGE_SIZE long, so termination relies on the total, not a short page.
    return _envelope([{"id": f"{seq}-{i}"} for i in range(PAGE_SIZE)])


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "people"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, page_size: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(justsift, "_fetch_page", fake_fetch)
        monkeypatch.setattr(justsift, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sift-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _envelope([{"id": "a"}, {"id": "b"}])})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A short page ends the sync, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            1: _full_page(1),
            2: _full_page(2),
            3: _envelope([{"id": "tail"}]),
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert len(rows) == PAGE_SIZE * 2 + 1
        assert rows[-1] == {"id": "tail"}

    def test_terminates_when_total_is_covered_by_full_page(self, monkeypatch: Any) -> None:
        # A final page that is exactly PAGE_SIZE long still terminates because the reported total is
        # reached — without this the loop would fetch a spurious empty page.
        rows = self._collect(
            _FakeResumableManager(), monkeypatch, {1: _full_page(1) | {"meta": {"totalLength": PAGE_SIZE}}}
        )
        assert len(rows) == PAGE_SIZE

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _full_page(1),
            2: _envelope([{"id": "last"}]),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(JustSiftResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _full_page(2),
            3: _envelope([{"id": "z"}]),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": "z"}

    def test_empty_first_page_does_not_yield(self, monkeypatch: Any) -> None:
        rows = self._collect(_FakeResumableManager(), monkeypatch, {1: _envelope([])})
        assert rows == []


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
        with pytest.raises(JustSiftRetryableError):
            _fetch_page_unwrapped(session, "/search/people", 1, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/search/people", 1, PAGE_SIZE, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _envelope([{"id": "a"}], total=1)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/search/people", 1, PAGE_SIZE, MagicMock())
        assert result == body

    def test_request_uses_page_and_page_size_params(self) -> None:
        session = self._session_returning(200, _envelope([]))
        _fetch_page_unwrapped(session, "/fields", 3, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "pageSize": PAGE_SIZE}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(justsift, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Sift returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("sift-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sift-token")
        assert status == 0
        assert message is not None and "boom" in message


class TestJustSiftSourceResponse:
    @parameterized.expand([("people", ["id"]), ("fields", ["objectKey"])])
    def test_primary_keys_match_endpoint_config(self, endpoint: str, primary_keys: list[str]) -> None:
        response = justsift_source(
            api_key="sift-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # No endpoint exposes a creation timestamp, so nothing is partitioned by datetime.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_endpoint_catalog_matches_exported_tuple(self) -> None:
        assert set(JUSTSIFT_ENDPOINTS) == set(ENDPOINTS)
