from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr import ruddr
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.ruddr import (
    PAGE_SIZE,
    RuddrResumeConfig,
    RuddrRetryableError,
    check_access,
    get_rows,
    ruddr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.settings import ENDPOINTS, RUDDR_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = ruddr._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: RuddrResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RuddrResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RuddrResumeConfig | None:
        return self._state

    def save_state(self, data: RuddrResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    # Ruddr resource ids are strings, and the cursor (RuddrResumeConfig.cursor) is typed str | None.
    return [{"id": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], bool]],
        endpoint: str = "clients",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, cursor: str | None, limit: int, logger: Any) -> tuple[list[dict], bool]:
            return pages[cursor]

        monkeypatch.setattr(ruddr, "_fetch_page", fake_fetch)
        monkeypatch.setattr(ruddr, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="ruddr-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_hasmore_false_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": 1}, {"id": 2}], False)})
        assert rows == [{"id": 1}, {"id": 2}]
        # hasMore is false, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_pagination_until_hasmore_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # First page is full with hasMore true; the cursor becomes the last item's id (PAGE_SIZE - 1).
        last_id = str(PAGE_SIZE - 1)
        pages: dict[str | None, tuple[list[dict], bool]] = {
            None: (_full_page(0), True),
            last_id: ([{"id": "999"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (cursor advances to the last id), then we stop.
        assert [s.cursor for s in manager.saved] == [last_id]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(RuddrResumeConfig(cursor="cur-99"))
        # The initial (cursor=None) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {"cur-99": ([{"id": "5"}], False)})
        assert rows == [{"id": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], False)})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [], "hasMore": False}
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
        with pytest.raises(RuddrRetryableError):
            _fetch_page_unwrapped(session, "/clients", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/clients", None, PAGE_SIZE, MagicMock())

    def test_success_returns_results_and_hasmore(self) -> None:
        body = {"results": [{"id": 1}], "hasMore": True}
        session = self._session_returning(200, body)
        results, has_more = _fetch_page_unwrapped(session, "/clients", None, PAGE_SIZE, MagicMock())
        assert results == [{"id": 1}]
        assert has_more is True

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        with pytest.raises(RuddrRetryableError):
            _fetch_page_unwrapped(session, "/clients", None, PAGE_SIZE, MagicMock())

    def test_missing_results_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"hasMore": False})
        with pytest.raises(RuddrRetryableError):
            _fetch_page_unwrapped(session, "/clients", None, PAGE_SIZE, MagicMock())

    def test_first_page_uses_limit_without_cursor(self) -> None:
        session = self._session_returning(200, {"results": [], "hasMore": False})
        _fetch_page_unwrapped(session, "/projects", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_page_sends_starting_after_cursor(self) -> None:
        session = self._session_returning(200, {"results": [], "hasMore": False})
        _fetch_page_unwrapped(session, "/projects", "cur-42", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "startingAfter": "cur-42"}


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
            ("server_error", 500, False, 500, "Ruddr returned HTTP 500"),
        ]
    )
    @patch(f"{ruddr.__name__}.make_tracked_session")
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
        assert check_access("ruddr-key") == (expected_status, expected_message)

    @patch(f"{ruddr.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("ruddr-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Ruddr API key"),
            ("forbidden", 403, False, "Invalid Ruddr API key"),
            ("server_error", 500, False, "Ruddr returned HTTP 500"),
        ]
    )
    @patch(f"{ruddr.__name__}.make_tracked_session")
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
        assert validate_credentials("ruddr-key") == (expected_valid, expected_message)


class TestRuddrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = ruddr_source(
            api_key="ruddr-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RUDDR_ENDPOINTS.values())
        assert set(RUDDR_ENDPOINTS) == set(ENDPOINTS)
