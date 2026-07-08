from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture import safetyculture
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.safetyculture import (
    SafetyCultureResumeConfig,
    SafetyCultureRetryableError,
    _build_initial_path,
    _format_modified_after,
    check_access,
    get_rows,
    safetyculture_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    SAFETYCULTURE_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = safetyculture._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SafetyCultureResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SafetyCultureResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SafetyCultureResumeConfig | None:
        return self._state

    def save_state(self, data: SafetyCultureResumeConfig) -> None:
        self.saved.append(data)


class TestBuildInitialPath:
    def test_static_params_are_encoded(self) -> None:
        path = _build_initial_path(SAFETYCULTURE_ENDPOINTS["inspections"], False, None)
        assert path == "/feed/inspections?archived=both&completed=both"

    def test_no_params_returns_bare_path(self) -> None:
        path = _build_initial_path(SAFETYCULTURE_ENDPOINTS["users"], False, None)
        assert path == "/feed/users"

    def test_incremental_cursor_adds_modified_after(self) -> None:
        cursor = datetime(2024, 3, 1, 12, 30, 45, tzinfo=UTC)
        path = _build_initial_path(SAFETYCULTURE_ENDPOINTS["actions"], True, cursor)
        assert path == "/feed/actions?modified_after=2024-03-01T12%3A30%3A45.000Z"

    def test_full_refresh_endpoint_ignores_cursor(self) -> None:
        # The issues feed rejects/ignores modified_after — a stale watermark must never leak into it.
        cursor = datetime(2024, 3, 1, tzinfo=UTC)
        path = _build_initial_path(SAFETYCULTURE_ENDPOINTS["issues"], True, cursor)
        assert path == "/feed/issues"


class TestFormatModifiedAfter:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 28, 23, 14, 23, tzinfo=UTC), "2024-01-28T23:14:23.000Z"),
            ("naive_datetime", datetime(2024, 1, 28, 23, 14, 23), "2024-01-28T23:14:23.000Z"),
            ("date", date(2024, 1, 28), "2024-01-28T00:00:00.000Z"),
            ("string_passthrough", "2024-01-28T23:14:23.000Z", "2024-01-28T23:14:23.000Z"),
        ]
    )
    def test_internet_date_time_format(self, _name: str, value: Any, expected: str) -> None:
        # Since 2025-02-01 SafetyCulture rejects timestamps that aren't Internet Date-Time format.
        assert _format_modified_after(value) == expected


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, tuple[list[dict], str | None]],
        endpoint: str = "users",
        **kwargs: Any,
    ) -> list[dict]:
        fetched: list[str] = []

        def fake_fetch(session: Any, path: str, logger: Any) -> tuple[list[dict], str | None]:
            fetched.append(path)
            return pages[path]

        monkeypatch.setattr(safetyculture, "_fetch_page", fake_fetch)
        monkeypatch.setattr(safetyculture, "make_tracked_session", lambda **_: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="sc-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows

    def test_single_page_no_next_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {"/feed/users": ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # `next_page` is null, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_next_page_verbatim(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "/feed/users": ([{"id": "a"}], "/feed/users?opaque-cursor=xyz"),
            "/feed/users?opaque-cursor=xyz": ([{"id": "b"}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "a"}, {"id": "b"}]
        # State is saved after the first page yields, and holds the verbatim next_page path.
        assert [s.next_page for s in manager.saved] == ["/feed/users?opaque-cursor=xyz"]

    def test_resumes_from_saved_next_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SafetyCultureResumeConfig(next_page="/feed/users?opaque-cursor=xyz"))
        # The initial (unfiltered) page must never be fetched on resume.
        pages: dict[str, tuple[list[dict], str | None]] = {"/feed/users?opaque-cursor=xyz": ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "b"}]

    def test_incremental_first_request_carries_modified_after(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        cursor = datetime(2024, 3, 1, tzinfo=UTC)
        expected_path = "/feed/inspections?archived=both&completed=both&modified_after=2024-03-01T00%3A00%3A00.000Z"
        pages: dict[str, tuple[list[dict], str | None]] = {expected_path: ([{"id": "a"}], None)}
        rows = self._collect(
            manager,
            monkeypatch,
            pages,
            endpoint="inspections",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
        )
        assert rows == [{"id": "a"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {"/feed/users": ([], None)})
        assert rows == []
        assert manager.saved == []

    def test_empty_page_with_next_page_terminates(self, monkeypatch: Any) -> None:
        # A lingering next_page on an empty page must not loop forever.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {"/feed/users": ([], "/feed/users?opaque-cursor=xyz")})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"metadata": {"next_page": None}, "data": []}
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
        with pytest.raises(SafetyCultureRetryableError):
            _fetch_page_unwrapped(session, "/feed/users", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/feed/users", MagicMock())

    def test_success_returns_items_and_next_page(self) -> None:
        body = {"metadata": {"next_page": "/feed/users?cursor=abc", "remaining_records": 10}, "data": [{"id": "a"}]}
        session = self._session_returning(200, body)
        items, next_page = _fetch_page_unwrapped(session, "/feed/users", MagicMock())
        assert items == [{"id": "a"}]
        assert next_page == "/feed/users?cursor=abc"

    @parameterized.expand(
        [
            ("null_next_page", {"metadata": {"next_page": None}, "data": [{"id": "a"}]}),
            ("missing_metadata", {"data": [{"id": "a"}]}),
            ("empty_next_page", {"metadata": {"next_page": ""}, "data": [{"id": "a"}]}),
        ]
    )
    def test_terminal_next_page_shapes_yield_none(self, _name: str, body: dict) -> None:
        session = self._session_returning(200, body)
        _, next_page = _fetch_page_unwrapped(session, "/feed/users", MagicMock())
        assert next_page is None

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "a"}]),
            ("non_list_data", {"metadata": {}, "data": {"id": "a"}}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(SafetyCultureRetryableError):
            _fetch_page_unwrapped(session, "/feed/users", MagicMock())

    def test_path_is_requested_verbatim_without_extra_params(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/feed/users?cursor=abc", MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == "https://api.safetyculture.io/feed/users?cursor=abc"
        assert "params" not in kwargs


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(safetyculture, "make_tracked_session", lambda **_: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "SafetyCulture returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("sc-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sc-token")
        assert status == 0
        assert message is not None and "boom" in message


class TestSafetyCultureSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = safetyculture_source(
            api_token="sc-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        config = SAFETYCULTURE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_incremental_endpoints_match_documented_modified_after_support(self) -> None:
        # Only these four feeds document a server-side modified_after filter; flipping any other
        # endpoint to incremental would silently ship a full-refresh-cost "incremental" sync.
        incremental = {name for name, config in SAFETYCULTURE_ENDPOINTS.items() if config.supports_incremental}
        assert incremental == {"inspections", "inspection_items", "templates", "actions"}
