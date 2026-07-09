import base64
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo import wufoo
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import ENDPOINTS, WUFOO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo import (
    PAGE_SIZE,
    WufooResumeConfig,
    WufooRetryableError,
    _headers,
    get_rows,
    validate_credentials,
    wufoo_source,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = wufoo._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: WufooResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[WufooResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> WufooResumeConfig | None:
        return self._state

    def save_state(self, data: WufooResumeConfig) -> None:
        self.saved.append(data)


def _page(count: int, data_key: str = "Forms") -> dict[str, Any]:
    return {data_key: [{"Hash": f"h{i}"} for i in range(count)]}


class TestHeaders:
    def test_basic_auth_uses_api_key_as_username_with_any_password(self) -> None:
        # Wufoo authenticates with HTTP Basic where the API key is the username; a wrong header
        # construction silently 401s every request, so pin the exact encoding.
        header = _headers("secret-key")["Authorization"]
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
        assert decoded == "secret-key:footastic"


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "forms"
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, page_start: int, logger: Any) -> dict:
            return pages[page_start]

        monkeypatch.setattr(wufoo, "_fetch_page", fake_fetch)
        monkeypatch.setattr(wufoo, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="wufoo-key",
            subdomain="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _page(2)})
        assert len(rows) == 2
        # The first page was short (< PAGE_SIZE), so no further page is requested or checkpointed.
        assert manager.saved == []

    def test_follows_offset_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: _page(PAGE_SIZE), PAGE_SIZE: _page(PAGE_SIZE), 2 * PAGE_SIZE: _page(3)}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == 2 * PAGE_SIZE + 3
        # State advances by PAGE_SIZE after each full page, and is never saved for the final short page.
        assert [s.page_start for s in manager.saved] == [PAGE_SIZE, 2 * PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(WufooResumeConfig(page_start=PAGE_SIZE))
        # Offset 0 must never be fetched on resume.
        pages = {PAGE_SIZE: _page(2)}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == 2

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _page(0)})
        assert rows == []

    def test_uses_endpoint_data_key(self, monkeypatch: Any) -> None:
        # Each endpoint wraps its rows under a distinct key; selecting the wrong one drops all rows.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _page(1, data_key="Users")}, endpoint="users")
        assert len(rows) == 1


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
        with pytest.raises(WufooRetryableError):
            _fetch_page_unwrapped(session, "https://acme.wufoo.com/api/v3/forms.json", 0, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://acme.wufoo.com/api/v3/forms.json", 0, MagicMock())

    def test_request_sends_pagestart_and_pagesize(self) -> None:
        session = self._session_returning(200, _page(0))
        _fetch_page_unwrapped(session, "https://acme.wufoo.com/api/v3/forms.json", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"pageStart": PAGE_SIZE, "pageSize": PAGE_SIZE}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [(200, 200), (401, 401), (403, 403), (500, 500)],
    )
    def test_returns_status_code(self, monkeypatch: Any, status: int, expected: int) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(wufoo, "make_tracked_session", lambda **kwargs: session)
        assert validate_credentials("wufoo-key", "acme") == expected

    def test_invalid_subdomain_short_circuits_without_request(self, monkeypatch: Any) -> None:
        session = MagicMock()
        monkeypatch.setattr(wufoo, "make_tracked_session", lambda **kwargs: session)
        assert validate_credentials("wufoo-key", "bad subdomain!") is None
        session.get.assert_not_called()

    def test_connection_error_maps_to_none(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(wufoo, "make_tracked_session", lambda **kwargs: session)
        assert validate_credentials("wufoo-key", "acme") is None


class TestWufooSourceResponse:
    @parameterized.expand([("forms",), ("reports",), ("users",)])
    def test_uses_hash_primary_key(self, endpoint: str) -> None:
        response = wufoo_source(
            api_key="wufoo-key",
            subdomain="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["Hash"]

    def test_every_endpoint_uses_hash_primary_key(self) -> None:
        assert all(config.primary_keys == ["Hash"] for config in WUFOO_ENDPOINTS.values())
        assert set(WUFOO_ENDPOINTS) == set(ENDPOINTS)
