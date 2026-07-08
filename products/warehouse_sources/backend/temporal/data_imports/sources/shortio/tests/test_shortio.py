from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.shortio import shortio
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.settings import (
    ENDPOINTS,
    SHORTIO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.shortio import (
    ShortioRetryableError,
    check_access,
    get_rows,
    shortio_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_all_unwrapped = shortio._fetch_all.__wrapped__  # type: ignore[attr-defined]


class TestGetRows:
    @staticmethod
    def _collect(monkeypatch: Any, rows: list[dict], endpoint: str = "domains") -> list[dict]:
        def fake_fetch(session: Any, path: str, logger: Any) -> list[dict]:
            return rows

        monkeypatch.setattr(shortio, "_fetch_all", fake_fetch)
        monkeypatch.setattr(shortio, "make_tracked_session", lambda **kwargs: MagicMock())

        collected: list[dict] = []
        for batch in get_rows(api_key="sk-key", endpoint=endpoint, logger=MagicMock()):
            collected.extend(batch)
        return collected

    def test_yields_all_rows_in_a_single_batch(self, monkeypatch: Any) -> None:
        rows = self._collect(monkeypatch, [{"id": 1}, {"id": 2}])
        assert rows == [{"id": 1}, {"id": 2}]

    def test_empty_response_yields_nothing(self, monkeypatch: Any) -> None:
        assert self._collect(monkeypatch, []) == []


class TestFetchAll:
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
        with pytest.raises(ShortioRetryableError):
            _fetch_all_unwrapped(session, "/api/domains", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_all_unwrapped(session, "/api/domains", MagicMock())

    def test_success_returns_list_body(self) -> None:
        body = [{"id": 1}]
        session = self._session_returning(200, body)
        assert _fetch_all_unwrapped(session, "/api/domains", MagicMock()) == body

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "nope"})
        with pytest.raises(ShortioRetryableError):
            _fetch_all_unwrapped(session, "/api/domains", MagicMock())


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(shortio, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Short.io returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("sk-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sk-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Short.io API key"),
            (403, False, "Invalid Short.io API key"),
            (500, False, "Short.io returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("sk-key") == (expected_valid, expected_message)

    def test_api_key_sent_raw_in_authorization_header(self, monkeypatch: Any) -> None:
        # Short.io uses the raw secret key in Authorization — no 'Bearer' prefix.
        captured: dict[str, Any] = {}

        def fake_make_session(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            session = MagicMock()
            response = MagicMock()
            response.status_code = 200
            response.ok = True
            session.get.return_value = response
            return session

        monkeypatch.setattr(shortio, "make_tracked_session", fake_make_session)
        check_access("sk-key")
        assert captured["headers"]["Authorization"] == "sk-key"


class TestShortioSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = shortio_source(api_key="sk-key", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # The domain list carries no stable creation timestamp guarantee, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SHORTIO_ENDPOINTS.values())
        assert set(SHORTIO_ENDPOINTS) == set(ENDPOINTS)
