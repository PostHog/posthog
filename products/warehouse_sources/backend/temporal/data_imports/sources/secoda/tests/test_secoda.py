from typing import Any, Optional

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.secoda import secoda
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.secoda import (
    SECODA_BASE_URL,
    SecodaResumeConfig,
    SecodaRetryableError,
    check_access,
    get_rows,
    secoda_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.settings import ENDPOINTS, SECODA_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = secoda._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SecodaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SecodaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SecodaResumeConfig | None:
        return self._state

    def save_state(self, data: SecodaResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, tuple[list[dict], Optional[str]]],
        endpoint: str = "tables",
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, logger: Any) -> tuple[list[dict], Optional[str]]:
            return pages[url]

        monkeypatch.setattr(secoda, "_fetch_page", fake_fetch)
        monkeypatch.setattr(secoda, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first = f"{SECODA_BASE_URL}/api/v1/table/tables"
        rows = self._collect(manager, monkeypatch, {first: ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A null next link ends the sync without persisting resume state.
        assert manager.saved == []

    def test_follows_next_url_cursor_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first = f"{SECODA_BASE_URL}/api/v1/table/tables"
        second = f"{SECODA_BASE_URL}/api/v1/table/tables?page=2"
        pages = {first: ([{"id": "a"}], second), second: ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "a"}, {"id": "b"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        second = f"{SECODA_BASE_URL}/api/v1/table/tables?page=2"
        manager = _FakeResumableManager(SecodaResumeConfig(next_url=second))
        # The first page URL must never be fetched on resume.
        pages = {second: ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "b"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first = f"{SECODA_BASE_URL}/api/v1/table/tables"
        rows = self._collect(manager, monkeypatch, {first: ([], None)})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [], "links": {"next": None}}
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
        with pytest.raises(SecodaRetryableError):
            _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/table/tables", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/table/tables", MagicMock())

    def test_success_returns_results_and_links_next(self) -> None:
        next_url = f"{SECODA_BASE_URL}/api/v1/table/tables?page=2"
        body = {"results": [{"id": "a"}], "links": {"next": next_url}, "count": 5}
        session = self._session_returning(200, body)
        rows, returned_next = _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/table/tables", MagicMock())
        assert rows == [{"id": "a"}]
        assert returned_next == next_url

    def test_top_level_next_is_accepted(self) -> None:
        next_url = f"{SECODA_BASE_URL}/api/v1/tag?page=2"
        body = {"results": [{"id": "a"}], "next": next_url}
        session = self._session_returning(200, body)
        _, returned_next = _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/tag", MagicMock())
        assert returned_next == next_url

    def test_null_next_returns_none(self) -> None:
        body = {"results": [{"id": "a"}], "links": {"next": None, "previous": None}}
        session = self._session_returning(200, body)
        _, returned_next = _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/user", MagicMock())
        assert returned_next is None

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_results", {"count": 1})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(SecodaRetryableError):
            _fetch_page_unwrapped(session, f"{SECODA_BASE_URL}/api/v1/user", MagicMock())

    def test_request_uses_absolute_url_without_params(self) -> None:
        session = self._session_returning(200, {"results": [], "links": {"next": None}})
        url = f"{SECODA_BASE_URL}/api/v1/table/columns?page=3"
        _fetch_page_unwrapped(session, url, MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == url
        # The cursor URL already carries paging; we must not re-send page params.
        assert "params" not in kwargs


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(secoda, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Secoda returned HTTP 500"),
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
            (401, False, "Invalid Secoda API key"),
            (403, False, "Invalid Secoda API key"),
            (500, False, "Secoda returned HTTP 500"),
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


class TestSecodaSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = secoda_source(
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SECODA_ENDPOINTS.values())
        assert set(SECODA_ENDPOINTS) == set(ENDPOINTS)
