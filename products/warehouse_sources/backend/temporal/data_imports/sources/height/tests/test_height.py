from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.height import height
from products.warehouse_sources.backend.temporal.data_imports.sources.height.height import (
    HeightRetryableError,
    check_access,
    get_rows,
    height_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import ENDPOINTS, HEIGHT_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_list_unwrapped = height._fetch_list.__wrapped__  # type: ignore[attr-defined]


class TestGetRows:
    @staticmethod
    def _collect(monkeypatch: Any, rows: list[dict], endpoint: str = "users") -> list[dict]:
        def fake_fetch(session: Any, path: str, logger: Any) -> list[dict]:
            return rows

        monkeypatch.setattr(height, "_fetch_list", fake_fetch)
        monkeypatch.setattr(height, "make_tracked_session", lambda **kwargs: MagicMock())

        collected: list[dict] = []
        for batch in get_rows(api_key="secret_key", endpoint=endpoint, logger=MagicMock()):
            collected.extend(batch)
        return collected

    def test_yields_single_batch(self, monkeypatch: Any) -> None:
        rows = self._collect(monkeypatch, [{"id": "a"}, {"id": "b"}])
        assert rows == [{"id": "a"}, {"id": "b"}]

    def test_empty_list_yields_nothing(self, monkeypatch: Any) -> None:
        assert self._collect(monkeypatch, []) == []

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_every_endpoint_fetches_its_path(self, endpoint: str) -> None:
        captured: dict[str, str] = {}

        def fake_fetch(session: Any, path: str, logger: Any) -> list[dict]:
            captured["path"] = path
            return []

        # Patch on the module so get_rows uses the fake, bypassing the network.
        original = height._fetch_list
        height._fetch_list = fake_fetch  # type: ignore[assignment]
        try:
            list(get_rows(api_key="secret_key", endpoint=endpoint, logger=MagicMock()))
        finally:
            height._fetch_list = original  # type: ignore[assignment]

        assert captured["path"] == HEIGHT_ENDPOINTS[endpoint].path


class TestFetchList:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"list": []}
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
        with pytest.raises(HeightRetryableError):
            _fetch_list_unwrapped(session, "/users", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_list_unwrapped(session, "/users", MagicMock())

    def test_success_returns_list_key(self) -> None:
        session = self._session_returning(200, {"list": [{"id": "x"}]})
        result = _fetch_list_unwrapped(session, "/users", MagicMock())
        assert result == [{"id": "x"}]

    @parameterized.expand([("bare_array", [{"id": 1}]), ("missing_list_key", {"data": []}), ("null_body", None)])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        # `None` maps to a body without a `list` key via the fixture default.
        session = self._session_returning(200, body if body is not None else {"data": []})
        with pytest.raises(HeightRetryableError):
            _fetch_list_unwrapped(session, "/users", MagicMock())

    def test_request_targets_base_url_and_path(self) -> None:
        session = self._session_returning(200, {"list": []})
        _fetch_list_unwrapped(session, "/lists", MagicMock())
        args, _ = session.get.call_args
        assert args[0] == "https://api.height.app/lists"


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(height, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Height returned HTTP 500"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.height.height.make_tracked_session")
    def test_status_mapping(
        self,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: mock.MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        session = MagicMock()
        session.get.return_value = response
        mock_make_session.return_value = session
        assert check_access("secret_key") == (expected_status, expected_message)

    def test_authorization_header_uses_api_key_scheme(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(headers: dict[str, str], redact_values: Any) -> MagicMock:
            captured["headers"] = headers
            response = MagicMock()
            response.status_code = 200
            response.ok = True
            session = MagicMock()
            session.get.return_value = response
            return session

        monkeypatch.setattr(height, "make_tracked_session", fake_make_session)
        check_access("secret_abc")
        assert captured["headers"]["Authorization"] == "api-key secret_abc"

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("secret_key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Height API key"),
            (403, False, "Invalid Height API key"),
            (500, False, "Height returned HTTP 500"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.height.height.make_tracked_session")
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: mock.MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        session = MagicMock()
        session.get.return_value = response
        mock_make_session.return_value = session
        assert validate_credentials("secret_key") == (expected_valid, expected_message)


class TestHeightSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = height_source(api_key="secret_key", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in HEIGHT_ENDPOINTS.values())
        assert set(HEIGHT_ENDPOINTS) == set(ENDPOINTS)
