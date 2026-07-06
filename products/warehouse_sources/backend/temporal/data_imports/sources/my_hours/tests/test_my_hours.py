from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours import my_hours
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.my_hours import (
    MyHoursRetryableError,
    check_access,
    get_rows,
    my_hours_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    ENDPOINTS,
    MY_HOURS_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = my_hours._fetch.__wrapped__  # type: ignore[attr-defined]


class TestGetRows:
    @staticmethod
    def _collect(monkeypatch: Any, items: list[dict], endpoint: str = "clients") -> list[dict]:
        def fake_fetch(session: Any, path: str, logger: Any) -> list[dict]:
            return items

        monkeypatch.setattr(my_hours, "_fetch", fake_fetch)
        monkeypatch.setattr(my_hours, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(api_key="mh-key", endpoint=endpoint, logger=MagicMock()):
            rows.extend(batch)
        return rows

    def test_yields_the_full_array_once(self, monkeypatch: Any) -> None:
        rows = self._collect(monkeypatch, [{"id": 1}, {"id": 2}])
        assert rows == [{"id": 1}, {"id": 2}]

    def test_empty_array_yields_nothing(self, monkeypatch: Any) -> None:
        rows = self._collect(monkeypatch, [])
        assert rows == []


class TestFetch:
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
        with pytest.raises(MyHoursRetryableError):
            _fetch_unwrapped(session, "/Clients", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(session, "/Clients", MagicMock())

    def test_success_returns_list_body(self) -> None:
        body = [{"id": 1}]
        session = self._session_returning(200, body)
        assert _fetch_unwrapped(session, "/Clients", MagicMock()) == body

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(MyHoursRetryableError):
            _fetch_unwrapped(session, "/Clients", MagicMock())

    def test_request_targets_the_expected_url(self) -> None:
        session = self._session_returning(200, [])
        _fetch_unwrapped(session, "/Projects/getAll", MagicMock())
        args, _ = session.get.call_args
        assert args[0] == "https://api2.myhours.com/api/Projects/getAll"


class TestAuthHeader:
    def test_uses_apikey_prefix(self) -> None:
        # My Hours rejects requests that omit the literal `apikey ` prefix, so this is load-bearing.
        assert my_hours._headers("mh-key")["Authorization"] == "apikey mh-key"


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(my_hours, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "My Hours returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("mh-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("mh-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid My Hours API key"),
            (403, False, "Invalid My Hours API key"),
            (500, False, "My Hours returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("mh-key") == (expected_valid, expected_message)


class TestMyHoursSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = my_hours_source(api_key="mh-key", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # The list endpoints carry no stable timestamp, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in MY_HOURS_ENDPOINTS.values())
        assert set(MY_HOURS_ENDPOINTS) == set(ENDPOINTS)
