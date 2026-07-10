from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub import oncehub
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.oncehub import (
    PAGE_SIZE,
    OncehubResumeConfig,
    OncehubRetryableError,
    check_access,
    get_rows,
    oncehub_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.settings import (
    ENDPOINTS,
    ONCEHUB_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = oncehub._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: OncehubResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OncehubResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OncehubResumeConfig | None:
        return self._state

    def save_state(self, data: OncehubResumeConfig) -> None:
        self.saved.append(data)


def _full_page(prefix: str) -> list[dict]:
    return [{"id": f"{prefix}-{i}"} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], bool]],
        endpoint: str = "bookings",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, cursor: str | None, limit: int, logger: Any) -> tuple[list[dict], bool]:
            return pages[cursor]

        monkeypatch.setattr(oncehub, "_fetch_page", fake_fetch)
        monkeypatch.setattr(oncehub, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="oncehub-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_has_more_false_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": "BKNG-1"}, {"id": "BKNG-2"}], False)})
        assert rows == [{"id": "BKNG-1"}, {"id": "BKNG-2"}]
        # has_more is false, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_after_cursor_until_has_more_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # First page is full with has_more true; the cursor becomes the last item's id.
        first_page = _full_page("BKNG")
        last_id = first_page[-1]["id"]
        pages: dict[str | None, tuple[list[dict], bool]] = {
            None: (first_page, True),
            last_id: ([{"id": "BKNG-final"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (cursor advances to the last id), then we stop.
        assert [s.cursor for s in manager.saved] == [last_id]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(OncehubResumeConfig(cursor="BKNG-99"))
        # The initial (cursor=None) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {"BKNG-99": ([{"id": "BKNG-100"}], False)})
        assert rows == [{"id": "BKNG-100"}]

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
        response.json.return_value = body if body is not None else {"object": "list", "data": [], "has_more": False}
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
        with pytest.raises(OncehubRetryableError):
            _fetch_page_unwrapped(session, "/bookings", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/bookings", None, PAGE_SIZE, MagicMock())

    def test_success_returns_data_and_has_more(self) -> None:
        body = {"object": "list", "data": [{"id": "BKNG-1"}], "has_more": True}
        session = self._session_returning(200, body)
        results, has_more = _fetch_page_unwrapped(session, "/bookings", None, PAGE_SIZE, MagicMock())
        assert results == [{"id": "BKNG-1"}]
        assert has_more is True

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "BKNG-1"}])
        with pytest.raises(OncehubRetryableError):
            _fetch_page_unwrapped(session, "/bookings", None, PAGE_SIZE, MagicMock())

    def test_missing_data_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"object": "list", "has_more": False})
        with pytest.raises(OncehubRetryableError):
            _fetch_page_unwrapped(session, "/bookings", None, PAGE_SIZE, MagicMock())

    def test_first_page_uses_limit_without_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/contacts", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_page_sends_after_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/contacts", "CTC-42", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "after": "CTC-42"}


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
            ("server_error", 500, False, 500, "OnceHub returned HTTP 500"),
        ]
    )
    @patch(f"{oncehub.__name__}.make_tracked_session")
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
        assert check_access("oncehub-key") == (expected_status, expected_message)

    @patch(f"{oncehub.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("oncehub-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid OnceHub API key"),
            ("forbidden", 403, False, "Invalid OnceHub API key"),
            ("server_error", 500, False, "OnceHub returned HTTP 500"),
        ]
    )
    @patch(f"{oncehub.__name__}.make_tracked_session")
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
        assert validate_credentials("oncehub-key") == (expected_valid, expected_message)


class TestOncehubSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = oncehub_source(
            api_key="oncehub-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists paginate newest-first with no stable ascending order, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ONCEHUB_ENDPOINTS.values())
        assert set(ONCEHUB_ENDPOINTS) == set(ENDPOINTS)
