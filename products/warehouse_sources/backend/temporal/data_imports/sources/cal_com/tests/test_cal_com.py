from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com import cal_com
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    CAL_COM_BASE_URL,
    PAGE_LIMIT,
    CalComResumeConfig,
    CalComRetryableError,
    cal_com_source,
    check_access,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
    ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = cal_com._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: CalComResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CalComResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CalComResumeConfig | None:
        return self._state

    def save_state(self, data: CalComResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    fake_fetch: Any,
    endpoint: str,
    **kwargs: Any,
) -> tuple[list[dict], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def _fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
        calls.append({"url": url, "params": params})
        return fake_fetch(url, params)

    with (
        patch.object(cal_com, "_fetch_page", _fetch),
        patch.object(cal_com, "make_tracked_session", return_value=MagicMock()),
    ):
        rows: list[dict] = []
        for batch in get_rows(
            api_key="cal_live_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows, calls


class TestBookingsCursorPagination:
    def _pages(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        cursor = params.get("cursor")
        if cursor is None:
            return {"data": [{"id": 1}], "pagination": {"nextCursor": "c2", "hasMore": True}}
        if cursor == "c2":
            return {"data": [{"id": 2}], "pagination": {"nextCursor": None, "hasMore": False}}
        raise AssertionError(f"unexpected cursor {cursor}")

    def test_follows_next_cursor_until_has_more_false(self) -> None:
        manager = _FakeResumableManager()
        rows, calls = _collect(manager, self._pages, "bookings")
        assert rows == [{"id": 1}, {"id": 2}]
        assert calls[0]["params"] == {"limit": PAGE_LIMIT}
        assert calls[1]["params"] == {"limit": PAGE_LIMIT, "cursor": "c2"}
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.cursor for s in manager.saved] == ["c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _FakeResumableManager(CalComResumeConfig(cursor="c2"))
        rows, calls = _collect(manager, self._pages, "bookings")
        # The first page must never be re-fetched on resume.
        assert rows == [{"id": 2}]
        assert calls[0]["params"]["cursor"] == "c2"

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"data": [], "pagination": {"nextCursor": None, "hasMore": False}}

        rows, _ = _collect(manager, pages, "bookings")
        assert rows == []
        assert manager.saved == []

    def test_incremental_filter_param_sent_on_every_page(self) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "bookings",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        for call in calls:
            assert call["params"]["afterUpdatedAt"] == "2026-01-02T03:04:05.000Z"

    def test_incremental_created_at_maps_to_after_created_at(self) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "bookings",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 2),
            incremental_field="createdAt",
        )
        assert calls[0]["params"]["afterCreatedAt"] == "2026-01-02T00:00:00.000Z"
        assert "afterUpdatedAt" not in calls[0]["params"]

    def test_unknown_incremental_field_raises(self) -> None:
        manager = _FakeResumableManager()
        with pytest.raises(ValueError, match="no server-side filter"):
            _collect(
                manager,
                self._pages,
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01",
                incremental_field="startTime",
            )

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    def test_no_filter_param_without_watermark(self, _name: str, should_use: bool, last_value: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "bookings",
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="updatedAt",
        )
        assert "afterUpdatedAt" not in calls[0]["params"]


class TestWebhooksOffsetPagination:
    def test_advances_skip_until_short_page(self) -> None:
        manager = _FakeResumableManager()
        full_page = [{"id": i} for i in range(PAGE_LIMIT)]

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"data": full_page if params["skip"] == 0 else [{"id": "last"}]}

        rows, calls = _collect(manager, pages, "webhooks")
        assert len(rows) == PAGE_LIMIT + 1
        assert [c["params"]["skip"] for c in calls] == [0, PAGE_LIMIT]
        assert [s.skip for s in manager.saved] == [PAGE_LIMIT]

    def test_resumes_from_saved_offset(self) -> None:
        manager = _FakeResumableManager(CalComResumeConfig(skip=500))

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            assert params["skip"] == 500
            return {"data": [{"id": "resumed"}]}

        rows, _ = _collect(manager, pages, "webhooks")
        assert rows == [{"id": "resumed"}]


class TestSingleFetchEndpoints:
    @parameterized.expand([("event_types",), ("schedules",), ("teams",)])
    def test_list_endpoints_yield_single_batch(self, endpoint: str) -> None:
        manager = _FakeResumableManager()
        rows, calls = _collect(manager, lambda url, params: {"data": [{"id": 1}, {"id": 2}]}, endpoint)
        assert rows == [{"id": 1}, {"id": 2}]
        assert len(calls) == 1
        assert manager.saved == []

    def test_me_wraps_single_object_in_list(self) -> None:
        manager = _FakeResumableManager()
        rows, _ = _collect(manager, lambda url, params: {"data": {"id": 42, "username": "tom"}}, "me")
        assert rows == [{"id": 42, "username": "tom"}]

    def test_endpoint_versions_pinned_in_headers(self) -> None:
        # Omitting cal-api-version silently falls back to legacy endpoint behavior, so the
        # versioned endpoints must pin it.
        assert cal_com._headers("k", CAL_COM_ENDPOINTS["bookings"])["cal-api-version"] == "2026-05-01"
        assert cal_com._headers("k", CAL_COM_ENDPOINTS["event_types"])["cal-api-version"] == "2024-06-14"
        assert cal_com._headers("k", CAL_COM_ENDPOINTS["schedules"])["cal-api-version"] == "2024-06-11"
        assert "cal-api-version" not in cal_com._headers("k", CAL_COM_ENDPOINTS["teams"])


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.reason = "Unauthorized"
        # A query string that would carry credentials on a query-bearing endpoint; the error path
        # must strip it before the URL reaches the exception message.
        response.url = f"{CAL_COM_BASE_URL}/bookings?apiKey=secret-token"
        response.json.return_value = body if body is not None else {"status": "success", "data": []}
        response.text = ""
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(CalComRetryableError):
            _fetch_page_unwrapped(session, f"{CAL_COM_BASE_URL}/bookings", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_with_scrubbed_url(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page_unwrapped(session, f"{CAL_COM_BASE_URL}/bookings", {}, MagicMock())
        # The base URL stays so `get_non_retryable_errors()` can match, but the credential-bearing
        # query string must never reach the persisted error message.
        message = str(exc_info.value)
        assert f"for url: {CAL_COM_BASE_URL}/bookings" in message
        assert "secret-token" not in message
        assert "?" not in message

    @parameterized.expand([("bare_list", [{"id": 1}]), ("missing_data", {"status": "success"})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(CalComRetryableError):
            _fetch_page_unwrapped(session, f"{CAL_COM_BASE_URL}/me", {}, MagicMock())

    def test_success_returns_full_body(self) -> None:
        body = {"status": "success", "data": [{"id": 1}], "pagination": {"nextCursor": "c2", "hasMore": True}}
        session = self._session_returning(200, body)
        assert _fetch_page_unwrapped(session, f"{CAL_COM_BASE_URL}/bookings", {"limit": 250}, MagicMock()) == body
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": 250}


class TestCheckAccess:
    def _session(self, response: Any) -> MagicMock:
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
            ("server_error", 500, False, 500, "Cal.com returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(cal_com, "make_tracked_session", return_value=self._session(response)):
            assert check_access("cal_live_key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(cal_com, "make_tracked_session", return_value=session):
            status, message = check_access("cal_live_key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Cal.com API key"),
            ("forbidden", 403, False, "Invalid Cal.com API key"),
            ("server_error", 500, False, "Cal.com returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(cal_com, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("cal_live_key") == (expected_valid, expected_message)


class TestCalComSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = cal_com_source(
            api_key="cal_live_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]

    def test_bookings_partitions_on_stable_created_at(self) -> None:
        response = cal_com_source(
            api_key="cal_live_key", endpoint="bookings", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        # Bookings arrive newest-first, so the watermark must only commit after a complete sync.
        assert response.sort_mode == "desc"

    @parameterized.expand([(e,) for e in ENDPOINTS if e != "bookings"])
    def test_full_refresh_endpoints_do_not_partition(self, endpoint: str) -> None:
        response = cal_com_source(
            api_key="cal_live_key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.partition_mode is None
        assert response.sort_mode == "asc"
