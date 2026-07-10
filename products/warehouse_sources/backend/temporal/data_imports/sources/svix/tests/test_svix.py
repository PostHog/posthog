from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.svix import svix
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.settings import ENDPOINTS, SVIX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix import (
    PAGE_SIZE,
    SvixResumeConfig,
    SvixRetryableError,
    check_access,
    get_rows,
    svix_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = svix._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SvixResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SvixResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SvixResumeConfig | None:
        return self._state

    def save_state(self, data: SvixResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], iterator: str | None, done: bool) -> dict:
    return {"data": items, "iterator": iterator, "done": done}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, dict],
        endpoint: str = "applications",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, iterator: str | None, limit: int, logger: Any) -> dict:
            return pages[iterator]

        monkeypatch.setattr(svix, "_fetch_page", fake_fetch)
        monkeypatch.setattr(svix, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_done_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[str | None, dict] = {None: _page([{"id": "app_1"}, {"id": "app_2"}], iterator="c1", done=True)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "app_1"}, {"id": "app_2"}]
        # `done` on the first page means we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_until_done(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: _page([{"id": "app_1"}], iterator="c1", done=False),
            "c1": _page([{"id": "app_2"}], iterator="c2", done=True),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "app_1"}, {"id": "app_2"}]
        # State saved once, carrying the cursor that fetches the second page.
        assert [s.iterator for s in manager.saved] == ["c1"]

    def test_stops_when_iterator_missing(self, monkeypatch: Any) -> None:
        # A page that isn't `done` but returns no next cursor must still terminate.
        manager = _FakeResumableManager()
        pages: dict[str | None, dict] = {None: _page([{"id": "app_1"}], iterator=None, done=False)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "app_1"}]
        assert manager.saved == []

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SvixResumeConfig(iterator="c1"))
        # The first (None) page must never be fetched on resume.
        pages: dict[str | None, dict] = {"c1": _page([{"id": "app_2"}], iterator="c2", done=True)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "app_2"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[str | None, dict] = {None: _page([], iterator=None, done=True)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": [], "done": True}
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
        with pytest.raises(SvixRetryableError):
            _fetch_page_unwrapped(session, "/app", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/app", None, PAGE_SIZE, MagicMock())

    def test_success_returns_envelope(self) -> None:
        body = {"data": [{"id": "app_1"}], "iterator": "c1", "done": True}
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/app", None, PAGE_SIZE, MagicMock())
        assert result == body

    def test_body_without_data_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(SvixRetryableError):
            _fetch_page_unwrapped(session, "/app", None, PAGE_SIZE, MagicMock())

    def test_first_request_omits_iterator_param(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/app", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_request_includes_iterator_param(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/app", "c1", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "iterator": "c1"}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(svix, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Svix returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("sk-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sk-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Svix API key"),
            (403, False, "Invalid Svix API key"),
            (500, False, "Svix returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("sk-key") == (expected_valid, expected_message)


class TestSvixSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = svix_source(
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == SVIX_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_primary_keys_per_endpoint(self) -> None:
        assert SVIX_ENDPOINTS["applications"].primary_keys == ["id"]
        assert SVIX_ENDPOINTS["event_types"].primary_keys == ["name"]
        assert set(SVIX_ENDPOINTS) == set(ENDPOINTS)
