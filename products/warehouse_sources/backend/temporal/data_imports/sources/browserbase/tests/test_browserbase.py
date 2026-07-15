from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase import browserbase
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase import (
    BROWSERBASE_BASE_URL,
    BrowserbaseRetryableError,
    _fetch,
    browserbase_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import ENDPOINTS


def _response(status_code: int, json_body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = "" if json_body is None else str(json_body)
    response.json.return_value = json_body

    def _raise() -> None:
        if not response.ok:
            raise requests.HTTPError(f"{status_code} Client Error", response=response)

    response.raise_for_status.side_effect = _raise
    return response


class TestFetch:
    def setup_method(self) -> None:
        # Drop the exponential backoff so retryable-status tests don't actually sleep.
        _fetch.retry.wait = wait_none()  # type: ignore[attr-defined]

    def test_returns_parsed_json_on_success(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "sess_1"}])

        result = _fetch(session, f"{BROWSERBASE_BASE_URL}/sessions", {}, MagicMock())

        assert result == [{"id": "sess_1"}]
        assert session.get.call_count == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code, {"error": "nope"})

        with pytest.raises(BrowserbaseRetryableError):
            _fetch(session, f"{BROWSERBASE_BASE_URL}/sessions", {}, MagicMock())

        # 5 attempts before giving up (stop_after_attempt(5)).
        assert session.get.call_count == 5

    def test_recovers_after_transient_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_response(500, {}), _response(200, [{"id": "sess_1"}])]

        result = _fetch(session, f"{BROWSERBASE_BASE_URL}/sessions", {}, MagicMock())

        assert result == [{"id": "sess_1"}]
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_immediately(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code, {"error": "nope"})

        with pytest.raises(requests.HTTPError):
            _fetch(session, f"{BROWSERBASE_BASE_URL}/sessions", {}, MagicMock())

        # Client errors are not retried - they can never succeed on retry.
        assert session.get.call_count == 1


class TestGetRows:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase._fetch")
    def test_yields_list_of_rows(self, mock_fetch: MagicMock) -> None:
        rows = [{"id": "sess_1"}, {"id": "sess_2"}]
        mock_fetch.return_value = rows

        result = list(get_rows("bb_key", "sessions", MagicMock()))

        assert result == [rows]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase._fetch")
    def test_empty_list_yields_nothing(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = []

        assert list(get_rows("bb_key", "sessions", MagicMock())) == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase._fetch")
    def test_non_list_response_raises(self, mock_fetch: MagicMock) -> None:
        # Browserbase list endpoints return arrays; a dict means an unexpected/error shape. Raise so the
        # sync fails loudly instead of finishing "successfully" with zero rows.
        mock_fetch.return_value = {"statusCode": 500}

        with pytest.raises(ValueError):
            list(get_rows("bb_key", "sessions", MagicMock()))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase._fetch")
    def test_requests_the_endpoint_path(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [{"id": "proj_1"}]

        list(get_rows("bb_key", "projects", MagicMock()))

        called_url = mock_fetch.call_args.args[1]
        assert called_url == f"{BROWSERBASE_BASE_URL}/projects"


class TestKeyRedaction:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase._fetch")
    @patch.object(browserbase, "make_tracked_session")
    def test_get_rows_redacts_key(self, mock_session_factory: MagicMock, mock_fetch: MagicMock) -> None:
        # The API key must be masked in tracked HTTP logs/samples, not left recoverable from a bucket.
        mock_fetch.return_value = []
        mock_session_factory.return_value = MagicMock()

        list(get_rows("bb_secret", "sessions", MagicMock()))

        assert mock_session_factory.call_args.kwargs["redact_values"] == ("bb_secret",)
        # Response bodies carry arbitrary customer userMetadata the scrubbers can't recognise.
        assert mock_session_factory.call_args.kwargs["capture"] is False

    @patch.object(browserbase, "make_tracked_session")
    def test_validate_credentials_redacts_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = _response(200)
        mock_session_factory.return_value = session

        validate_credentials("bb_secret")

        assert mock_session_factory.call_args.kwargs["redact_values"] == ("bb_secret",)
        assert mock_session_factory.call_args.kwargs["capture"] is False


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch.object(browserbase, "make_tracked_session")
    def test_maps_status_to_bool(
        self, _name: str, status_code: int, expected: bool, mock_session_factory: MagicMock
    ) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code)
        mock_session_factory.return_value = session

        assert validate_credentials("bb_key") is expected

    @patch.object(browserbase, "make_tracked_session")
    def test_network_error_propagates(self, mock_session_factory: MagicMock) -> None:
        # A transport failure is transient - it must surface, not be reported as an invalid key.
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        mock_session_factory.return_value = session

        with pytest.raises(requests.ConnectionError):
            validate_credentials("bb_key")


class TestBrowserbaseSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = browserbase_source("bb_key", endpoint, MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Partition on the stable creation timestamp, never updatedAt.
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"
