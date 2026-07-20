from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor import tickettailor
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import (
    ENDPOINTS,
    TICKET_TAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.tickettailor import (
    PAGE_SIZE,
    TicketTailorResumeConfig,
    TicketTailorRetryableError,
    _make_session,
    check_access,
    get_rows,
    tickettailor_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = tickettailor._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: TicketTailorResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TicketTailorResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TicketTailorResumeConfig | None:
        return self._state

    def save_state(self, data: TicketTailorResumeConfig) -> None:
        self.saved.append(data)


class TestMakeSession:
    @patch(f"{tickettailor.__name__}.make_tracked_session")
    def test_uses_basic_auth_with_key_as_username(self, mock_make_session: MagicMock) -> None:
        session = MagicMock()
        mock_make_session.return_value = session
        _make_session("tt-key")
        # Ticket Tailor authenticates via HTTP Basic with the key as the username and no password —
        # switching to e.g. a Bearer header would break every sync.
        assert session.auth == ("tt-key", "")
        assert mock_make_session.call_args.kwargs["redact_values"] == ("tt-key",)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], bool]],
        endpoint: str = "orders",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, cursor: str | None, limit: int, logger: Any) -> tuple[list[dict], bool]:
            return pages[cursor]

        monkeypatch.setattr(tickettailor, "_fetch_page", fake_fetch)
        monkeypatch.setattr(tickettailor, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="tt-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_without_next_link_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": "or_1"}, {"id": "or_2"}], False)})
        assert rows == [{"id": "or_1"}, {"id": "or_2"}]
        # No next link, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_pagination_until_no_next_link(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_page = [{"id": f"or_{i}"} for i in range(PAGE_SIZE)]
        pages: dict[str | None, tuple[list[dict], bool]] = {
            None: (first_page, True),
            "or_99": ([{"id": "or_100"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (cursor advances to the last id), then we stop.
        assert [s.cursor for s in manager.saved] == ["or_99"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(TicketTailorResumeConfig(cursor="or_50"))
        # The initial (cursor=None) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {"or_50": ([{"id": "or_51"}], False)})
        assert rows == [{"id": "or_51"}]

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
        response.json.return_value = body if body is not None else {"data": [], "links": {"next": None}}
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
        with pytest.raises(TicketTailorRetryableError):
            _fetch_page_unwrapped(session, "/v1/orders", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/v1/orders", None, PAGE_SIZE, MagicMock())

    @parameterized.expand(
        [
            ("next_link_present", {"next": "/v1/orders?starting_after=or_120", "previous": None}, True),
            ("next_link_null", {"next": None, "previous": None}, False),
            ("links_missing", None, False),
        ]
    )
    def test_has_more_follows_next_link(self, _name: str, links: dict | None, expected_has_more: bool) -> None:
        body: dict[str, Any] = {"data": [{"id": "or_1"}]}
        if links is not None:
            body["links"] = links
        session = self._session_returning(200, body)
        items, has_more = _fetch_page_unwrapped(session, "/v1/orders", None, PAGE_SIZE, MagicMock())
        assert items == [{"id": "or_1"}]
        assert has_more is expected_has_more

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "or_1"}])
        with pytest.raises(TicketTailorRetryableError):
            _fetch_page_unwrapped(session, "/v1/orders", None, PAGE_SIZE, MagicMock())

    def test_missing_data_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"links": {"next": None}})
        with pytest.raises(TicketTailorRetryableError):
            _fetch_page_unwrapped(session, "/v1/orders", None, PAGE_SIZE, MagicMock())

    def test_first_page_uses_limit_without_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/v1/events", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_page_sends_starting_after_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/v1/events", "ev_42", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "starting_after": "ev_42"}


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
            # Ticket Tailor answers invalid/deleted keys with 403, not 401.
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Ticket Tailor returned HTTP 500"),
        ]
    )
    @patch(f"{tickettailor.__name__}.make_tracked_session")
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
        assert check_access("tt-key") == (expected_status, expected_message)

    @patch(f"{tickettailor.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("tt-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Ticket Tailor API key"),
            ("forbidden", 403, False, "Invalid Ticket Tailor API key"),
            ("server_error", 500, False, "Ticket Tailor returned HTTP 500"),
        ]
    )
    @patch(f"{tickettailor.__name__}.make_tracked_session")
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
        assert validate_credentials("tt-key") == (expected_valid, expected_message)


class TestTicketTailorSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = tickettailor_source(
            api_key="tt-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists come back newest-first; declaring asc would corrupt a future incremental watermark.
        assert response.sort_mode == "desc"
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in TICKET_TAILOR_ENDPOINTS.values())
        assert set(TICKET_TAILOR_ENDPOINTS) == set(ENDPOINTS)
