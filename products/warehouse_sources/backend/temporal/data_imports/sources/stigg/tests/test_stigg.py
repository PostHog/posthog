from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.stigg import stigg
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import ENDPOINTS, STIGG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.stigg import (
    PAGE_SIZE,
    StiggResumeConfig,
    StiggRetryableError,
    check_access,
    get_rows,
    stigg_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = stigg._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: StiggResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[StiggResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> StiggResumeConfig | None:
        return self._state

    def save_state(self, data: StiggResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], str | None]],
        endpoint: str = "customers",
    ) -> list[dict]:
        def fake_fetch(
            session: Any, path: str, cursor: str | None, limit: int, logger: Any
        ) -> tuple[list[dict], str | None]:
            return pages[cursor]

        monkeypatch.setattr(stigg, "_fetch_page", fake_fetch)
        monkeypatch.setattr(stigg, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="stigg-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_null_next_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # pagination.next is null, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_next_cursor_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[str | None, tuple[list[dict], str | None]] = {
            None: ([{"id": "1"}, {"id": "2"}], "cursor-page-2"),
            "cursor-page-2": ([{"id": "3"}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # State is saved after the first page (cursor advances to pagination.next), then we stop.
        assert [s.cursor for s in manager.saved] == ["cursor-page-2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(StiggResumeConfig(cursor="cur-99"))
        # The initial (cursor=None) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {"cur-99": ([{"id": "5"}], None)})
        assert rows == [{"id": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], None)})
        assert rows == []
        assert manager.saved == []

    def test_empty_page_with_cursor_stops_without_saving(self, monkeypatch: Any) -> None:
        # Defensive: an empty page terminates even if the API still returns a next cursor,
        # so a buggy upstream cursor can't loop us forever.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], "phantom-cursor")})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": [], "pagination": {"next": None}}
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
        with pytest.raises(StiggRetryableError):
            _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())

    def test_success_returns_items_and_next_cursor(self) -> None:
        body = {"data": [{"id": "1"}], "pagination": {"next": "abc", "prev": None}}
        session = self._session_returning(200, body)
        items, next_cursor = _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())
        assert items == [{"id": "1"}]
        assert next_cursor == "abc"

    def test_null_next_cursor_maps_to_none(self) -> None:
        body = {"data": [{"id": "1"}], "pagination": {"next": None, "prev": "xyz"}}
        session = self._session_returning(200, body)
        _, next_cursor = _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())
        assert next_cursor is None

    def test_missing_pagination_maps_to_none(self) -> None:
        session = self._session_returning(200, {"data": [{"id": "1"}]})
        _, next_cursor = _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())
        assert next_cursor is None

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "1"}])
        with pytest.raises(StiggRetryableError):
            _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())

    def test_missing_data_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"pagination": {"next": None}})
        with pytest.raises(StiggRetryableError):
            _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())

    def test_first_page_uses_limit_without_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/plans", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_page_sends_after_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/plans", "cur-42", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "after": "cur-42"}


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
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Stigg returned HTTP 500"),
        ]
    )
    @patch(f"{stigg.__name__}.make_tracked_session")
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
        assert check_access("stigg-key") == (expected_status, expected_message)

    @patch(f"{stigg.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("stigg-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            ("server_error", 500, False, "Stigg returned HTTP 500"),
        ]
    )
    @patch(f"{stigg.__name__}.make_tracked_session")
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
        assert validate_credentials("stigg-key") == (expected_valid, expected_message)


class TestStiggSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = stigg_source(
            api_key="stigg-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == STIGG_ENDPOINTS[endpoint].primary_keys
        # createdAt is required on every list DTO and never changes, so it's a stable partition key.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @parameterized.expand([("plans",), ("addons",)])
    def test_versioned_packages_use_composite_primary_key(self, endpoint: str) -> None:
        # Plans and addons share their `id` slug across versions; dropping `versionNumber` from
        # the key would seed duplicate rows and multi-match every later merge.
        assert STIGG_ENDPOINTS[endpoint].primary_keys == ["id", "versionNumber"]
