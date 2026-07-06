import base64
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.configcat import configcat
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.configcat import (
    ConfigCatRetryableError,
    _headers,
    check_access,
    configcat_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import (
    CONFIGCAT_ENDPOINTS,
    ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = configcat._fetch.__wrapped__  # type: ignore[attr-defined]


class TestHeaders:
    def test_basic_auth_header_encodes_username_and_password(self) -> None:
        headers = _headers("user", "pass")
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestGetRows:
    @staticmethod
    def _collect(monkeypatch: Any, items: list[dict], endpoint: str = "products") -> list[dict]:
        def fake_fetch(session: Any, path: str, logger: Any) -> list[dict]:
            return items

        monkeypatch.setattr(configcat, "_fetch", fake_fetch)
        monkeypatch.setattr(configcat, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(username="user", password="pass", endpoint=endpoint, logger=MagicMock()):
            rows.extend(batch)
        return rows

    def test_yields_full_collection_in_one_batch(self, monkeypatch: Any) -> None:
        rows = self._collect(monkeypatch, [{"productId": "a"}, {"productId": "b"}])
        assert rows == [{"productId": "a"}, {"productId": "b"}]

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        assert self._collect(monkeypatch, []) == []


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
        with pytest.raises(ConfigCatRetryableError):
            _fetch_unwrapped(session, "/v1/products", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(session, "/v1/products", MagicMock())

    def test_success_returns_list_body(self) -> None:
        body = [{"productId": "a"}]
        session = self._session_returning(200, body)
        assert _fetch_unwrapped(session, "/v1/products", MagicMock()) == body

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(ConfigCatRetryableError):
            _fetch_unwrapped(session, "/v1/products", MagicMock())


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(configcat, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "ConfigCat returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("user", "pass") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("user", "pass")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid ConfigCat Public API credentials"),
            (403, False, "Invalid ConfigCat Public API credentials"),
            (500, False, "ConfigCat returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("user", "pass") == (expected_valid, expected_message)


class TestConfigCatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = configcat_source(username="user", password="pass", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == CONFIGCAT_ENDPOINTS[endpoint].primary_keys
        # The list endpoints expose no stable timestamp, so we don't partition.
        assert response.partition_mode is None

    def test_primary_keys_are_per_endpoint(self) -> None:
        assert CONFIGCAT_ENDPOINTS["products"].primary_keys == ["productId"]
        assert CONFIGCAT_ENDPOINTS["organizations"].primary_keys == ["organizationId"]
        assert set(CONFIGCAT_ENDPOINTS) == set(ENDPOINTS)
