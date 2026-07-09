import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired import shopwired
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import (
    PAGE_SIZE,
    SHOPWIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.shopwired import (
    ShopWiredResumeConfig,
    ShopWiredRetryableError,
    check_access,
    get_rows,
    shopwired_source,
    to_unix_timestamp,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = shopwired._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: ShopWiredResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ShopWiredResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ShopWiredResumeConfig | None:
        return self._state

    def save_state(self, data: ShopWiredResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, list[dict]],
        endpoint: str = "products",
        db_incremental_field_last_value: Any = None,
        requested_params: list[dict] | None = None,
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, params: dict[str, Any], logger: Any) -> list[dict]:
            if requested_params is not None:
                requested_params.append(params)
            return pages[params.get("offset", 0)]

        monkeypatch.setattr(shopwired, "_fetch_page", fake_fetch)
        monkeypatch.setattr(shopwired, "_make_session", lambda *args: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sw-key",
            api_secret="sw-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows

    def test_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: [{"id": 1}, {"id": 2}]})
        assert rows == [{"id": 1}, {"id": 2}]
        # The page is short, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_offset_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: _full_page(0), PAGE_SIZE: [{"id": 999}]}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the full first page (offset advances by its row count), then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_resumes_from_saved_offset_and_pinned_window(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(ShopWiredResumeConfig(offset=200, from_timestamp=1700000000))
        requested: list[dict] = []
        rows = self._collect(
            manager,
            monkeypatch,
            {200: [{"id": 5}]},
            endpoint="orders",
            # A watermark that advanced mid-run must not replace the pinned window from the resume state.
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
            requested_params=requested,
        )
        assert rows == [{"id": 5}]
        assert requested[0]["offset"] == 200
        assert requested[0]["from"] == 1700000000

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: []})
        assert rows == []
        assert manager.saved == []

    def test_incremental_run_sends_from_and_sort_params(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        requested: list[dict] = []
        watermark = datetime(2024, 1, 1, tzinfo=UTC)
        self._collect(
            manager,
            monkeypatch,
            {0: [{"id": 1}]},
            endpoint="orders",
            db_incremental_field_last_value=watermark,
            requested_params=requested,
        )
        assert requested[0]["from"] == int(watermark.timestamp())
        assert requested[0]["sort"] == "date"

    def test_full_refresh_run_omits_from_param(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        requested: list[dict] = []
        self._collect(manager, monkeypatch, {0: [{"id": 1}]}, endpoint="products", requested_params=requested)
        assert "from" not in requested[0]
        assert "sort" not in requested[0]

    def test_unpaginated_endpoint_fetches_once(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        requested: list[dict] = []
        # A full-size page must not trigger a second request — order statuses document no pagination.
        rows = self._collect(
            manager, monkeypatch, {0: _full_page(0)}, endpoint="order_statuses", requested_params=requested
        )
        assert len(rows) == PAGE_SIZE
        assert len(requested) == 1
        assert requested[0] == {}
        assert manager.saved == []


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("none", None, None),
            ("datetime", datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            # Naive values must be treated as UTC regardless of the worker's local timezone.
            ("naive_datetime", datetime(2024, 1, 1), 1704067200),
            ("date", date(2024, 1, 1), 1704067200),
            ("epoch_int", 1704067200, 1704067200),
            ("epoch_float", 1704067200.5, 1704067200),
            ("rfc2822_string", "Mon, 01 Jan 2024 00:00:00 +0000", 1704067200),
            ("iso_string", "2024-01-01T00:00:00+00:00", 1704067200),
            ("naive_iso_string", "2024-01-01T00:00:00", 1704067200),
            ("unparseable_string", "not-a-date-at-all-99", None),
            ("empty_string", "", None),
        ]
    )
    def test_conversion(self, _name: str, value: Any, expected: int | None) -> None:
        assert to_unix_timestamp(value) == expected

    def test_naive_values_are_utc_regardless_of_local_timezone(self, monkeypatch: Any) -> None:
        # CI runs in UTC, where a local-time interpretation of naive values happens to give the
        # right answer — force a non-UTC timezone so a regression to naive .timestamp() fails here.
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            assert to_unix_timestamp(date(2024, 1, 1)) == 1704067200
            assert to_unix_timestamp(datetime(2024, 1, 1)) == 1704067200
            assert to_unix_timestamp("2024-01-01T00:00:00") == 1704067200
        finally:
            monkeypatch.undo()
            time.tzset()


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
        with pytest.raises(ShopWiredRetryableError):
            _fetch_page_unwrapped(session, "/products", {"count": PAGE_SIZE, "offset": 0}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/products", {"count": PAGE_SIZE, "offset": 0}, MagicMock())

    def test_success_returns_bare_array(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        assert _fetch_page_unwrapped(session, "/products", {}, MagicMock()) == [{"id": 1}]

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "unexpected"})
        with pytest.raises(ShopWiredRetryableError):
            _fetch_page_unwrapped(session, "/products", {}, MagicMock())

    def test_params_are_passed_through(self) -> None:
        session = self._session_returning(200, [])
        params = {"count": PAGE_SIZE, "offset": 300, "sort": "date", "from": 1700000000}
        _fetch_page_unwrapped(session, "/orders", params, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == params


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
            ("server_error", 500, False, 500, "ShopWired returned HTTP 500"),
        ]
    )
    @patch(f"{shopwired.__name__}.make_tracked_session")
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
        assert check_access("sw-key", "sw-secret") == (expected_status, expected_message)

    @patch(f"{shopwired.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("sw-key", "sw-secret")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid ShopWired API key or secret"),
            ("forbidden", 403, False, "Invalid ShopWired API key or secret"),
            ("server_error", 500, False, "ShopWired returned HTTP 500"),
        ]
    )
    @patch(f"{shopwired.__name__}.make_tracked_session")
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
        assert validate_credentials("sw-key", "sw-secret") == (expected_valid, expected_message)


class TestShopWiredSourceResponse:
    @parameterized.expand([(name,) for name in SHOPWIRED_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = shopwired_source(
            api_key="sw-key",
            api_secret="sw-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    def test_orders_partition_on_stable_created_field(self) -> None:
        response = shopwired_source(
            api_key="sw-key",
            api_secret="sw-secret",
            endpoint="orders",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]

    def test_non_order_endpoints_have_no_datetime_partition(self) -> None:
        response = shopwired_source(
            api_key="sw-key",
            api_secret="sw-secret",
            endpoint="products",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
