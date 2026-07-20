from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail import flexmail
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail import (
    PAGE_SIZE,
    FlexmailResumeConfig,
    FlexmailRetryableError,
    check_access,
    flexmail_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import (
    ENDPOINTS,
    FLEXMAIL_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = flexmail._fetch_page.__wrapped__  # type: ignore[attr-defined]


def _envelope(items: list[dict], total: int, offset: int = 0) -> dict[str, Any]:
    return {"total": total, "limit": PAGE_SIZE, "offset": offset, "_embedded": {"item": items}}


class _FakeResumableManager:
    def __init__(self, state: FlexmailResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FlexmailResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FlexmailResumeConfig | None:
        return self._state

    def save_state(self, data: FlexmailResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int | None, dict[str, Any]],
        endpoint: str = "contacts",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, params: dict | None, logger: Any) -> dict[str, Any]:
            offset = params["offset"] if params is not None else None
            return pages[offset]

        monkeypatch.setattr(flexmail, "_fetch_page", fake_fetch)
        monkeypatch.setattr(flexmail, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            account_id="12345",
            personal_access_token="flexmail-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _envelope([{"id": 1}, {"id": 2}], total=2)})
        assert rows == [{"id": 1}, {"id": 2}]
        # total is within the first page, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_offset_pagination_until_total(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_page = [{"id": i} for i in range(PAGE_SIZE)]
        pages: dict[int | None, dict[str, Any]] = {
            0: _envelope(first_page, total=PAGE_SIZE + 1),
            PAGE_SIZE: _envelope([{"id": 999}], total=PAGE_SIZE + 1, offset=PAGE_SIZE),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (offset advances by the page size), then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FlexmailResumeConfig(offset=PAGE_SIZE))
        # The initial (offset=0) page must never be fetched on resume.
        pages: dict[int | None, dict[str, Any]] = {
            PAGE_SIZE: _envelope([{"id": 5}], total=PAGE_SIZE + 1, offset=PAGE_SIZE)
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 5}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _envelope([], total=0)})
        assert rows == []
        assert manager.saved == []

    def test_empty_page_mid_collection_stops(self, monkeypatch: Any) -> None:
        # Rows deleted mid-sync can shrink the collection; an empty page must terminate the loop
        # even when `total` still claims more rows.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _envelope([], total=PAGE_SIZE * 2)})
        assert rows == []
        assert manager.saved == []

    def test_missing_embedded_key_yields_nothing(self, monkeypatch: Any) -> None:
        # HAL omits `_embedded` entirely for empty collections.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: {"total": 0, "limit": PAGE_SIZE, "offset": 0}})
        assert rows == []

    def test_links_are_stripped_from_rows(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        items = [{"id": 1, "email": "a@b.co", "_links": {"self": {"href": "/contacts/1"}}}]
        rows = self._collect(manager, monkeypatch, {0: _envelope(items, total=1)})
        assert rows == [{"id": 1, "email": "a@b.co"}]

    @parameterized.expand([("segments",), ("opt_in_forms",), ("custom_fields",)])
    def test_unpaginated_endpoint_fetches_once_and_never_saves_state(self, endpoint: str) -> None:
        manager = _FakeResumableManager()
        rows = self._collect_unpaginated(manager, endpoint)
        assert rows == [{"id": "u-1"}]
        assert manager.saved == []

    @staticmethod
    def _collect_unpaginated(manager: _FakeResumableManager, endpoint: str) -> list[dict]:
        calls: list[dict | None] = []

        def fake_fetch(session: Any, path: str, params: dict | None, logger: Any) -> dict[str, Any]:
            calls.append(params)
            return {"_embedded": {"item": [{"id": "u-1"}]}}

        with (
            patch.object(flexmail, "_fetch_page", fake_fetch),
            patch.object(flexmail, "make_tracked_session", return_value=MagicMock()),
        ):
            rows: list[dict] = []
            for batch in get_rows(
                account_id="12345",
                personal_access_token="flexmail-token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            ):
                rows.extend(batch)
        # A single request with no pagination params.
        assert calls == [None]
        return rows


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else _envelope([], total=0)
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
        with pytest.raises(FlexmailRetryableError):
            _fetch_page_unwrapped(session, "/contacts", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/contacts", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())

    def test_success_returns_body(self) -> None:
        body = _envelope([{"id": 1}], total=1)
        session = self._session_returning(200, body)
        assert _fetch_page_unwrapped(session, "/contacts", {"limit": PAGE_SIZE, "offset": 0}, MagicMock()) == body

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        with pytest.raises(FlexmailRetryableError):
            _fetch_page_unwrapped(session, "/contacts", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())

    def test_pagination_params_are_sent(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/sources", {"limit": PAGE_SIZE, "offset": 500}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "offset": 500}


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
            ("server_error", 500, False, 500, "Flexmail returned HTTP 500"),
        ]
    )
    @patch(f"{flexmail.__name__}.make_tracked_session")
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
        assert check_access("12345", "flexmail-token") == (expected_status, expected_message)

    @patch(f"{flexmail.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("12345", "flexmail-token")
        assert status == 0
        assert message is not None and "boom" in message

    @patch(f"{flexmail.__name__}.make_tracked_session")
    def test_probe_uses_basic_auth(self, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session = self._session(response)
        mock_session.return_value = session
        check_access("12345", "flexmail-token")
        assert session.auth == ("12345", "flexmail-token")

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Flexmail account ID or personal access token"),
            ("forbidden", 403, False, "Invalid Flexmail account ID or personal access token"),
            ("server_error", 500, False, "Flexmail returned HTTP 500"),
        ]
    )
    @patch(f"{flexmail.__name__}.make_tracked_session")
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
        assert validate_credentials("12345", "flexmail-token") == (expected_valid, expected_message)


class TestFlexmailSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = flexmail_source(
            account_id="12345",
            personal_access_token="flexmail-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp exists on most resources, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in FLEXMAIL_ENDPOINTS.values())
        assert set(FLEXMAIL_ENDPOINTS) == set(ENDPOINTS)
