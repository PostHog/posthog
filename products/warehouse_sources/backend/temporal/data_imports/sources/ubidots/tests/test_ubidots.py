from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots import ubidots
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import (
    DEFAULT_UBIDOTS_API_BASE_URL,
    ENDPOINTS,
    VALUES_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.ubidots import (
    UbidotsResumeConfig,
    UbidotsRetryableError,
    _start_timestamp_ms,
    _validated_api_base_url,
    check_access,
    get_rows,
    get_values_rows,
    ubidots_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = ubidots._fetch_page.__wrapped__  # type: ignore[attr-defined]

DEVICES_FIRST_URL = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/devices/?page_size=200"
VARIABLES_FIRST_URL = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/variables/?page_size=200"


def _values_url(variable_id: str, start: Optional[int] = None) -> str:
    url = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v1.6/variables/{variable_id}/values?page_size=200"
    return f"{url}&start={start}" if start is not None else url


class _FakeResumableManager:
    def __init__(self, state: UbidotsResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[UbidotsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> UbidotsResumeConfig | None:
        return self._state

    def save_state(self, data: UbidotsResumeConfig) -> None:
        self.saved.append(data)


def _fake_transport(monkeypatch: Any, pages: Mapping[str, tuple[list[dict], Optional[str]]]) -> None:
    def fake_fetch(session: Any, url: str, logger: Any) -> tuple[list[dict], Optional[str]]:
        return pages[url]

    monkeypatch.setattr(ubidots, "_fetch_page", fake_fetch)
    monkeypatch.setattr(ubidots, "make_tracked_session", lambda **kwargs: MagicMock())


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict], Optional[str]]],
        endpoint: str = "devices",
    ) -> list[dict]:
        _fake_transport(monkeypatch, pages)
        rows: list[dict] = []
        for batch in get_rows(
            api_token="BBUS-token",
            api_base_url=None,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {DEVICES_FIRST_URL: ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A null next link ends the sync without persisting resume state.
        assert manager.saved == []

    def test_follows_next_url_cursor_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        second = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/devices/?page=2&page_size=200"
        pages = {DEVICES_FIRST_URL: ([{"id": "a"}], second), second: ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "a"}, {"id": "b"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        second = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/devices/?page=2&page_size=200"
        manager = _FakeResumableManager(UbidotsResumeConfig(next_url=second))
        # The first page URL must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {second: ([{"id": "b"}], None)})
        assert rows == [{"id": "b"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {DEVICES_FIRST_URL: ([], None)})
        assert rows == []
        assert manager.saved == []


class TestGetValuesRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict], Optional[str]]],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        logger: Any = None,
    ) -> list[dict]:
        _fake_transport(monkeypatch, pages)
        rows: list[dict] = []
        for batch in get_values_rows(
            api_token="BBUS-token",
            api_base_url=None,
            logger=logger or MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows

    def test_fans_out_per_variable_and_injects_variable_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}, {"id": "var2"}], None),
            _values_url("var1"): ([{"timestamp": 2, "value": 1.0}], None),
            _values_url("var2"): ([{"timestamp": 3, "value": 2.0}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        # The dot payload has no variable field — injection is what makes the composite key unique.
        assert rows == [
            {"timestamp": 2, "value": 1.0, "variable": "var1"},
            {"timestamp": 3, "value": 2.0, "variable": "var2"},
        ]
        # Each fully synced variable is checkpointed so a resumed job skips past it.
        assert [s.completed_variable_ids for s in manager.saved] == [["var1"], ["var1", "var2"]]

    def test_incremental_watermark_is_passed_as_start(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}], None),
            # A URL without &start= is absent from this map, so dropping the server-side filter
            # would KeyError here rather than silently re-fetching full history.
            _values_url("var1", start=1700000000000): ([{"timestamp": 1700000000001}], None),
        }
        rows = self._collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
        )
        assert rows == [{"timestamp": 1700000000001, "variable": "var1"}]

    @pytest.mark.parametrize(
        "should_use_incremental_field,last_value",
        [
            pytest.param(False, 1700000000000, id="full_refresh_ignores_watermark"),
            pytest.param(True, None, id="incremental_without_watermark"),
        ],
    )
    def test_no_start_param_when_not_filtering(
        self, should_use_incremental_field: bool, last_value: Any, monkeypatch: Any
    ) -> None:
        manager = _FakeResumableManager()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}], None),
            _values_url("var1"): ([{"timestamp": 5}], None),
        }
        rows = self._collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert rows == [{"timestamp": 5, "variable": "var1"}]

    def test_resume_skips_completed_and_continues_current_variable(self, monkeypatch: Any) -> None:
        var2_page2 = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v1.6/variables/var2/values?page=2&page_size=200"
        manager = _FakeResumableManager(
            UbidotsResumeConfig(next_url=var2_page2, current_variable_id="var2", completed_variable_ids=["var1"])
        )
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}, {"id": "var2"}, {"id": "var3"}], None),
            # var1 is complete and var2 resumes mid-pagination — their first-page URLs must never
            # be fetched again.
            var2_page2: ([{"timestamp": 2}], None),
            _values_url("var3"): ([{"timestamp": 3}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [
            {"timestamp": 2, "variable": "var2"},
            {"timestamp": 3, "variable": "var3"},
        ]

    def test_mid_variable_state_saved_after_yield(self, monkeypatch: Any) -> None:
        page2 = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v1.6/variables/var1/values?page=2&page_size=200"
        manager = _FakeResumableManager()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}], None),
            _values_url("var1"): ([{"timestamp": 2}], page2),
            page2: ([{"timestamp": 1}], None),
        }
        self._collect(manager, monkeypatch, pages)
        mid = manager.saved[0]
        assert (mid.next_url, mid.current_variable_id, mid.completed_variable_ids) == (page2, "var1", [])
        done = manager.saved[-1]
        assert (done.next_url, done.current_variable_id, done.completed_variable_ids) == (None, None, ["var1"])

    def test_page_cap_stops_pagination_and_warns(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ubidots, "MAX_VALUES_PAGES_PER_VARIABLE", 1)
        page2 = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v1.6/variables/var1/values?page=2&page_size=200"
        manager = _FakeResumableManager()
        logger = MagicMock()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}], None),
            # page2 is absent from the map — fetching past the cap would KeyError.
            _values_url("var1"): ([{"timestamp": 2}], page2),
        }
        rows = self._collect(manager, monkeypatch, pages, logger=logger)
        assert rows == [{"timestamp": 2, "variable": "var1"}]
        logger.warning.assert_called_once()
        # The capped variable still counts as complete so the sync can finish.
        assert manager.saved[-1].completed_variable_ids == ["var1"]

    def test_variables_list_pagination_is_followed(self, monkeypatch: Any) -> None:
        variables_page2 = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/variables/?page=2&page_size=200"
        manager = _FakeResumableManager()
        pages = {
            VARIABLES_FIRST_URL: ([{"id": "var1"}], variables_page2),
            variables_page2: ([{"id": "var2"}], None),
            _values_url("var1"): ([{"timestamp": 1}], None),
            _values_url("var2"): ([{"timestamp": 2}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["variable"] for r in rows] == ["var1", "var2"]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [], "next": None}
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
        with pytest.raises(UbidotsRetryableError):
            _fetch_page_unwrapped(session, DEVICES_FIRST_URL, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, DEVICES_FIRST_URL, MagicMock())

    def test_success_returns_results_and_next(self) -> None:
        next_url = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/devices/?page=2&page_size=200"
        body = {"count": 5, "next": next_url, "previous": None, "results": [{"id": "a"}]}
        session = self._session_returning(200, body)
        rows, returned_next = _fetch_page_unwrapped(session, DEVICES_FIRST_URL, MagicMock())
        assert rows == [{"id": "a"}]
        assert returned_next == next_url

    def test_null_next_returns_none(self) -> None:
        body = {"count": 1, "next": None, "previous": None, "results": [{"id": "a"}]}
        session = self._session_returning(200, body)
        _, returned_next = _fetch_page_unwrapped(session, DEVICES_FIRST_URL, MagicMock())
        assert returned_next is None

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_results", {"count": 1})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(UbidotsRetryableError):
            _fetch_page_unwrapped(session, DEVICES_FIRST_URL, MagicMock())

    def test_request_uses_absolute_url_without_params(self) -> None:
        session = self._session_returning(200, {"results": [], "next": None})
        url = f"{DEFAULT_UBIDOTS_API_BASE_URL}/api/v2.0/devices/?page=3&page_size=200"
        _fetch_page_unwrapped(session, url, MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == url
        # The cursor URL already carries paging; we must not re-send page params.
        assert "params" not in kwargs


class TestHelpers:
    @parameterized.expand(
        [
            ("none", None, None),
            ("int_ms", 1700000000000, 1700000000000),
            ("float_ms", 1700000000000.7, 1700000000000),
            ("numeric_string", "1700000000000", 1700000000000),
            ("datetime", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000000000 // 1000),
            ("garbage_string", "not-a-timestamp", None),
            ("bool", True, None),
        ]
    )
    def test_start_timestamp_ms(self, _name: str, value: Any, expected: Optional[int]) -> None:
        assert _start_timestamp_ms(value) == expected

    @parameterized.expand(
        [
            ("default_when_none", None, "https://industrial.api.ubidots.com"),
            ("industrial", "https://industrial.api.ubidots.com", "https://industrial.api.ubidots.com"),
            ("legacy", "https://things.ubidots.com", "https://things.ubidots.com"),
            ("trailing_slash", "https://things.ubidots.com/", "https://things.ubidots.com"),
        ]
    )
    def test_validated_api_base_url_accepts_allowed_hosts(self, _name: str, given: str | None, expected: str) -> None:
        assert _validated_api_base_url(given) == expected

    @parameterized.expand(
        [
            ("attacker_host", "https://evil.example.com"),
            ("lookalike", "https://industrial.api.ubidots.com.evil.example.com"),
        ]
    )
    def test_validated_api_base_url_rejects_unknown_hosts(self, _name: str, given: str) -> None:
        # The stored token must never be sent to a host outside the fixed Ubidots set.
        with pytest.raises(ValueError):
            _validated_api_base_url(given)


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
            ("server_error", 500, False, 500, "Ubidots returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(ubidots, "make_tracked_session", return_value=self._session(response)):
            assert check_access("BBUS-token", None) == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(ubidots, "make_tracked_session", return_value=session):
            status, message = check_access("BBUS-token", None)
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Ubidots API token"),
            ("forbidden", 403, False, "Invalid Ubidots API token"),
            ("server_error", 500, False, "Ubidots returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(ubidots, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("BBUS-token", None) == (expected_valid, expected_message)

    def test_validate_credentials_rejects_bad_base_url(self) -> None:
        valid, message = validate_credentials("BBUS-token", "https://evil.example.com")
        assert valid is False
        assert message is not None and "API base URL" in message


class TestUbidotsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = ubidots_source(
            api_token="BBUS-token",
            api_base_url=None,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        if endpoint == VALUES_ENDPOINT:
            # The parent id is half the composite key — timestamps repeat across variables.
            assert response.primary_keys == ["variable", "timestamp"]
            # Values return newest first, so the watermark must only commit at sync end.
            assert response.sort_mode == "desc"
        else:
            assert response.primary_keys == ["id"]
            assert response.sort_mode == "asc"
