from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds import cloudbeds
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.cloudbeds import (
    PAGE_SIZE,
    CloudbedsApiError,
    CloudbedsResumeConfig,
    CloudbedsRetryableError,
    check_access,
    cloudbeds_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = cloudbeds._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: CloudbedsResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CloudbedsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CloudbedsResumeConfig | None:
        return self._state

    def save_state(self, data: CloudbedsResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"reservationID": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[tuple[str, Any], list[Any]],
        endpoint: str = "reservations",
        property_id: str | None = None,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], logger: Any) -> list[dict]:
            calls.append(params)
            return pages[(path, params.get("pageNumber"))]

        monkeypatch.setattr(cloudbeds, "_fetch_page", fake_fetch)
        monkeypatch.setattr(cloudbeds, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="cbat_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            property_id=property_id,
        ):
            rows.extend(batch)
        return rows, calls

    def test_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            manager, monkeypatch, {("/getReservations", 1): [{"reservationID": "1"}, {"reservationID": "2"}]}
        )
        assert rows == [{"reservationID": "1"}, {"reservationID": "2"}]
        # The page was short, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_page_number_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/getReservations", 1): _full_page(0),
            ("/getReservations", 2): [{"reservationID": "999"}],
        }
        rows, _ = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (advancing to page 2), then we stop on the short page.
        assert [s.page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(CloudbedsResumeConfig(page=3))
        # Page 1 must never be fetched on resume.
        rows, calls = self._collect(manager, monkeypatch, {("/getReservations", 3): [{"reservationID": "5"}]})
        assert rows == [{"reservationID": "5"}]
        assert [c["pageNumber"] for c in calls] == [3]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, {("/getReservations", 1): []})
        assert rows == []
        assert manager.saved == []

    def test_property_id_is_sent_on_every_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/getReservations", 1): _full_page(0),
            ("/getReservations", 2): [],
        }
        _, calls = self._collect(manager, monkeypatch, pages, property_id="12345")
        assert all(c["propertyID"] == "12345" for c in calls)

    def test_non_paginated_endpoint_fetches_once_and_never_saves_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {("/getHotels", None): [{"propertyID": "1"}, {"propertyID": "2"}]}
        rows, calls = self._collect(manager, monkeypatch, pages, endpoint="hotels")
        assert rows == [{"propertyID": "1"}, {"propertyID": "2"}]
        assert len(calls) == 1
        assert "pageNumber" not in calls[0]
        assert manager.saved == []

    def test_rooms_are_flattened_with_property_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/getRooms", None): [
                {
                    "propertyID": "1",
                    "propertyName": "Hotel One",
                    "rooms": [{"roomID": "r1", "roomName": "101"}, {"roomID": "r2", "roomName": "102"}],
                },
                {"propertyID": "2", "propertyName": "Hotel Two", "rooms": []},
            ]
        }
        rows, _ = self._collect(manager, monkeypatch, pages, endpoint="rooms")
        assert rows == [
            {"roomID": "r1", "roomName": "101", "propertyID": "1"},
            {"roomID": "r2", "roomName": "102", "propertyID": "1"},
        ]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"success": True, "data": []}
        response.text = ""
        response.reason = "Unauthorized"
        response.url = "https://api.cloudbeds.com/api/v1.2/getReservations?propertyID=1"
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(CloudbedsRetryableError):
            _fetch_page_unwrapped(session, "/getReservations", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_sanitized_http_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page_unwrapped(session, "/getReservations", {}, MagicMock())
        message = str(exc_info.value)
        # Keeps the prefix get_non_retryable_errors() matches on, but drops the query string so a
        # future credential-bearing URL can never leak into persisted error state.
        assert message.startswith(f"{status} Client Error:")
        assert "for url: https://api.cloudbeds.com/api/v1.2/getReservations" in message
        assert "?" not in message

    def test_success_returns_data_rows(self) -> None:
        body = {"success": True, "data": [{"reservationID": "1"}], "count": 1, "total": 1}
        session = self._session_returning(200, body)
        rows = _fetch_page_unwrapped(session, "/getReservations", {}, MagicMock())
        assert rows == [{"reservationID": "1"}]

    def test_success_false_raises_api_error_not_retryable(self) -> None:
        # Cloudbeds signals bad params / missing scopes as HTTP 200 + success=false; retrying would
        # loop forever, so it must surface as a distinct non-retryable error.
        body = {"success": False, "message": "Access denied for this endpoint"}
        session = self._session_returning(200, body)
        with pytest.raises(CloudbedsApiError, match="Access denied"):
            _fetch_page_unwrapped(session, "/getReservations", {}, MagicMock())

    @parameterized.expand(
        [
            ("non_dict_body", [{"reservationID": "1"}]),
            ("missing_data_key", {"success": True}),
            ("non_list_data", {"success": True, "data": {"reservationID": "1"}}),
        ]
    )
    def test_unexpected_payloads_are_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(CloudbedsRetryableError):
            _fetch_page_unwrapped(session, "/getReservations", {}, MagicMock())


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
            ("server_error", 500, False, 500, "Cloudbeds returned HTTP 500"),
        ]
    )
    @patch(f"{cloudbeds.__name__}.make_tracked_session")
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
        assert check_access("cbat_key") == (expected_status, expected_message)

    @patch(f"{cloudbeds.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("cbat_key")
        assert status == 0
        assert message is not None and "boom" in message

    @patch(f"{cloudbeds.__name__}.make_tracked_session")
    def test_probe_scopes_to_property_when_configured(self, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session = self._session(response)
        mock_session.return_value = session
        check_access("cbat_key", property_id="12345")
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"propertyID": "12345"}

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Cloudbeds API key"),
            ("forbidden", 403, False, "Invalid Cloudbeds API key"),
            ("server_error", 500, False, "Cloudbeds returned HTTP 500"),
        ]
    )
    @patch(f"{cloudbeds.__name__}.make_tracked_session")
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
        assert validate_credentials("cbat_key") == (expected_valid, expected_message)


class TestCloudbedsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = cloudbeds_source(
            api_key="cbat_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == CLOUDBEDS_ENDPOINTS[endpoint].primary_keys
        # No creation timestamp is verified stable across every object, so we don't partition.
        assert response.partition_mode is None

    def test_endpoint_catalog_is_consistent(self) -> None:
        assert set(CLOUDBEDS_ENDPOINTS) == set(ENDPOINTS)
        assert all(config.primary_keys for config in CLOUDBEDS_ENDPOINTS.values())
