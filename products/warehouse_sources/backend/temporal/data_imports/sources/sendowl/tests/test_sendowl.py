import base64
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl import sendowl
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl import (
    SendowlResumeConfig,
    SendowlRetryableError,
    _headers,
    check_access,
    get_rows,
    sendowl_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import (
    ENDPOINTS,
    SENDOWL_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = sendowl._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SendowlResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SendowlResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SendowlResumeConfig | None:
        return self._state

    def save_state(self, data: SendowlResumeConfig) -> None:
        self.saved.append(data)


def _wrapped(wrapper_key: str, rows: list[dict]) -> list[dict]:
    # SendOwl returns each list item under a single-key wrapper, e.g. `{"product": {...}}`.
    return [{wrapper_key: row} for row in rows]


class TestHeaders:
    def test_builds_basic_auth_from_key_and_secret(self) -> None:
        headers = _headers("key123", "secret456")
        expected = base64.b64encode(b"key123:secret456").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, list[dict]], endpoint: str = "products"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, wrapper_key: str, page: int, per_page: int, logger: Any) -> list[dict]:
            return pages[page]

        monkeypatch.setattr(sendowl, "_fetch_page", fake_fetch)
        monkeypatch.setattr(sendowl, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sendowl-key",
            api_secret="sendowl-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: [{"id": 1}, {"id": 2}]})
        assert rows == [{"id": 1}, {"id": 2}]
        # A short page ends the sync, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_short_page(self, monkeypatch: Any) -> None:
        full_page = [{"id": i} for i in range(sendowl.PER_PAGE)]
        pages = {1: full_page, 2: [{"id": 999}]}
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [*full_page, {"id": 999}]

    def test_saves_next_page_after_yielding_full_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        full_page = [{"id": i} for i in range(sendowl.PER_PAGE)]
        pages = {1: full_page, 2: [{"id": 999}]}
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER the full page 1 is yielded (pointing at page 2), never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SendowlResumeConfig(next_page=2))
        full_page = [{"id": i} for i in range(sendowl.PER_PAGE)]
        # Page 1 must never be fetched on resume.
        pages = {2: full_page, 3: [{"id": 7}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [*full_page, {"id": 7}]

    def test_empty_page_does_not_yield(self, monkeypatch: Any) -> None:
        rows = self._collect(_FakeResumableManager(), monkeypatch, {1: []})
        assert rows == []


class TestFetchPage:
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
        with pytest.raises(SendowlRetryableError):
            _fetch_page_unwrapped(session, "/api/v1/products", "product", 1, 50, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/api/v1/products", "product", 1, 50, MagicMock())

    def test_success_unwraps_single_key_wrapper(self) -> None:
        body = _wrapped("product", [{"id": 1, "name": "Ebook"}, {"id": 2, "name": "Course"}])
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/api/v1/products", "product", 1, 50, MagicMock())
        assert result == [{"id": 1, "name": "Ebook"}, {"id": 2, "name": "Course"}]

    def test_non_list_payload_raises_retryable(self) -> None:
        session = self._session_returning(200, {"error": "unexpected"})
        with pytest.raises(SendowlRetryableError):
            _fetch_page_unwrapped(session, "/api/v1/products", "product", 1, 50, MagicMock())

    def test_request_uses_page_and_per_page_params(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "/api/v1_3/orders", "order", 3, 50, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "per_page": 50}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(sendowl, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            ("reachable", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "SendOwl returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        with pytest.MonkeyPatch.context() as mp:
            self._patch_session(mp, response)
            assert check_access("sendowl-key", "sendowl-secret") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sendowl-key", "sendowl-secret")
        assert status == 0
        assert message is not None and "boom" in message


class TestSendowlSourceResponse:
    @parameterized.expand([("products",), ("orders",), ("subscriptions",), ("discount_codes",)])
    def test_response_uses_id_primary_key(self, endpoint: str) -> None:
        response = sendowl_source(
            api_key="sendowl-key",
            api_secret="sendowl-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SENDOWL_ENDPOINTS.values())
        assert set(SENDOWL_ENDPOINTS) == set(ENDPOINTS)
