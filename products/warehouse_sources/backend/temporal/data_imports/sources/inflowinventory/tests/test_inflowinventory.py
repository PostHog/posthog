from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory import inflowinventory
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.inflowinventory import (
    PAGE_SIZE,
    InflowInventoryResumeConfig,
    InflowInventoryRetryableError,
    check_access,
    get_rows,
    inflowinventory_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    ENDPOINTS,
    INFLOWINVENTORY_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = inflowinventory._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: InflowInventoryResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[InflowInventoryResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> InflowInventoryResumeConfig | None:
        return self._state

    def save_state(self, data: InflowInventoryResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"productId": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[Any, list[dict]],
        endpoint: str = "products",
    ) -> list[dict]:
        def fake_fetch(session: Any, company_id: str, path: str, after: Any, count: int, logger: Any) -> list[dict]:
            return pages[after]

        monkeypatch.setattr(inflowinventory, "_fetch_page", fake_fetch)
        monkeypatch.setattr(inflowinventory, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="inflow-key",
            company_id="co-123",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: [{"productId": "1"}, {"productId": "2"}]})
        assert rows == [{"productId": "1"}, {"productId": "2"}]
        # The page is short (< PAGE_SIZE), so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_after_cursor_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # Last row of the first full page has productId str(PAGE_SIZE - 1), which becomes the cursor.
        last_id = str(PAGE_SIZE - 1)
        pages = {None: _full_page(0), last_id: [{"productId": "9999"}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        assert [s.after for s in manager.saved] == [last_id]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(InflowInventoryResumeConfig(after="42"))
        # The unpaginated first page (after=None) must never be fetched on resume.
        pages = {"42": [{"productId": "5"}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"productId": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: []})
        assert rows == []
        assert manager.saved == []

    def test_full_page_missing_id_field_stops(self, monkeypatch: Any) -> None:
        # A full page whose last row lacks the cursor field can't be paginated past — stop instead
        # of looping forever on the same cursor.
        page = _full_page(0)
        page[-1] = {"name": "no id here"}
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: page})
        assert len(rows) == PAGE_SIZE
        assert manager.saved == []


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
        with pytest.raises(InflowInventoryRetryableError):
            _fetch_page_unwrapped(session, "co-1", "products", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "co-1", "products", None, PAGE_SIZE, MagicMock())

    def test_success_returns_list_body(self) -> None:
        body = [{"productId": "1"}]
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "co-1", "products", None, PAGE_SIZE, MagicMock())
        assert result == body

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(InflowInventoryRetryableError):
            _fetch_page_unwrapped(session, "co-1", "products", None, PAGE_SIZE, MagicMock())

    def test_first_page_omits_after_param(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "co-1", "products", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"count": PAGE_SIZE}

    def test_paginated_request_sends_after_cursor(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "co-1", "customers", "abc", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"count": PAGE_SIZE, "after": "abc"}

    def test_request_targets_company_scoped_url(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "co-1", "sales-orders", None, PAGE_SIZE, MagicMock())
        args, _ = session.get.call_args
        assert args[0] == "https://cloudapi.inflowinventory.com/co-1/sales-orders"


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(inflowinventory, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "inFlow Inventory returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("inflow-key", "co-123") == (expected_status, expected_message)

    def test_malformed_company_id_short_circuits(self, monkeypatch: Any) -> None:
        # A bad company ID never reaches the network — no session is created.
        session = self._patch_session(monkeypatch, MagicMock())
        status, message = check_access("inflow-key", "bad id/../evil")
        assert status == 400
        assert message is not None
        session.get.assert_not_called()

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("inflow-key", "co-123")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid inFlow Inventory API key"),
            (403, False, "Invalid inFlow Inventory API key"),
            (500, False, "inFlow Inventory returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("inflow-key", "co-123") == (expected_valid, expected_message)


class TestInflowInventorySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = inflowinventory_source(
            api_key="inflow-key",
            company_id="co-123",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == INFLOWINVENTORY_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_primary_key_matches_id_field(self) -> None:
        assert all(config.primary_keys == [config.id_field] for config in INFLOWINVENTORY_ENDPOINTS.values())
        assert set(INFLOWINVENTORY_ENDPOINTS) == set(ENDPOINTS)
