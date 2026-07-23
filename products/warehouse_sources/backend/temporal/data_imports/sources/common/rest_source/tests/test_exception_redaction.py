from typing import Any
from urllib.parse import quote

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
SECRET = "sk_live_super_secret_key"
# A key with reserved characters is percent-encoded in the query string, so `_redact` (which only
# replaces the raw value) can't scrub it — the URL must be reduced to scheme/host/path instead.
SPECIAL_SECRET = "abc+def/ghi="


def _make_response(
    status_code: int, secret: str, *, reason: str = "OK", content: bytes = b'{"error": "nope"}'
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    # The credential rides in the query string (percent-encoded, as requests sends it), so it lands
    # in the URL that raise_for_status / the retryable-error message embed — the leak this closes.
    resp.url = f"https://api.example.com/items?api_key={quote(secret, safe='')}"
    resp._content = content
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_client(secret: str, MockSession: MagicMock) -> MagicMock:
    mock_session = MockSession.return_value
    mock_session.headers = {}

    def _prep(request: Any) -> MagicMock:
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    mock_session.prepare_request.side_effect = _prep
    return mock_session


def _make_client_with_credentialed_url(secret: str, MockSession: MagicMock) -> MagicMock:
    # Unlike `_make_client`, the prepared URL itself carries the query-encoded credential — this
    # is what a real `session.prepare_request()` produces once the auth hook injects the query
    # param, and it's what `_send_request` sees when a connection error fires before any response.
    mock_session = MockSession.return_value
    mock_session.headers = {}
    prepared = MagicMock()
    prepared.url = f"https://api.example.com/items?api_key={quote(secret, safe='')}"
    mock_session.prepare_request.return_value = prepared
    return mock_session


def _make_connection_error(secret: str) -> RequestsConnectionError:
    # Mirrors urllib3's real "Max retries exceeded with url: ..." message shape, which embeds the
    # full request URL (query string included) in the exception text itself.
    url = f"https://api.example.com/items?api_key={quote(secret, safe='')}"
    return RequestsConnectionError(
        f"HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: {url} "
        "(Caused by ProxyError('Cannot connect to proxy.'))"
    )


class TestExceptionRedaction:
    @patch(f"{MODULE}.make_tracked_session")
    def test_client_error_masks_secret_in_place(self, MockSession) -> None:
        # The raise_for_status path keeps the URL and masks the raw secret to *** in place.
        mock_session = _make_client(SECRET, MockSession)
        mock_session.send.return_value = _make_response(400, SECRET, reason="Bad Request")
        client = RESTClient(
            base_url="https://api.example.com",
            auth=APIKeyAuth(api_key=SECRET, name="api_key", location="query"),
            max_retry_attempts=1,
        )
        with pytest.raises(Exception) as excinfo:
            list(client.paginate(path="/items"))
        message = str(excinfo.value)
        assert SECRET not in message
        assert "***" in message
        assert "400" in message

    @parameterized.expand([("raw", SECRET), ("reserved_chars", SPECIAL_SECRET)])
    @patch(f"{MODULE}.make_tracked_session")
    def test_retryable_5xx_drops_query_so_no_secret_leaks(self, _name: str, secret: str, MockSession) -> None:
        mock_session = _make_client(secret, MockSession)
        mock_session.send.return_value = _make_response(500, secret, reason="Server Error")
        client = RESTClient(
            base_url="https://api.example.com",
            auth=APIKeyAuth(api_key=secret, name="api_key", location="query"),
            max_retry_attempts=1,
        )
        with pytest.raises(RESTClientRetryableError) as excinfo:
            list(client.paginate(path="/items"))
        message = str(excinfo.value)
        # Neither the raw nor the percent-encoded secret survives; the query is dropped entirely.
        assert secret not in message
        assert quote(secret, safe="") not in message
        assert "?" not in message
        assert "HTTP 500" in message
        assert "api.example.com/items" in message

    @parameterized.expand([("raw", SECRET), ("reserved_chars", SPECIAL_SECRET)])
    @patch(f"{MODULE}.make_tracked_session")
    def test_malformed_json_drops_query_so_no_secret_leaks(self, _name: str, secret: str, MockSession) -> None:
        mock_session = _make_client(secret, MockSession)
        # A 200 whose body starts like JSON but doesn't parse hits the malformed (retryable) branch.
        mock_session.send.return_value = _make_response(200, secret, content=b'{"partial')
        client = RESTClient(
            base_url="https://api.example.com",
            auth=APIKeyAuth(api_key=secret, name="api_key", location="query"),
            max_retry_attempts=1,
        )
        with pytest.raises(RESTClientRetryableError) as excinfo:
            list(client.paginate(path="/items"))
        message = str(excinfo.value)
        assert secret not in message
        assert quote(secret, safe="") not in message
        assert "?" not in message

    @parameterized.expand([("raw", SECRET), ("reserved_chars", SPECIAL_SECRET)])
    @patch(f"{MODULE}.make_tracked_session")
    def test_connection_error_drops_query_so_no_secret_leaks(self, _name: str, secret: str, MockSession) -> None:
        mock_session = _make_client_with_credentialed_url(secret, MockSession)
        mock_session.send.side_effect = _make_connection_error(secret)
        client = RESTClient(
            base_url="https://api.example.com",
            auth=APIKeyAuth(api_key=secret, name="api_key", location="query"),
            max_retry_attempts=1,
        )
        with pytest.raises(RESTClientRetryableError) as excinfo:
            list(client.paginate(path="/items"))
        message = str(excinfo.value)
        # Neither the raw nor the percent-encoded secret survives; the query is dropped entirely.
        assert secret not in message
        assert quote(secret, safe="") not in message
        assert "?" not in message
        assert "api.example.com/items" in message

    @patch(f"{MODULE}.make_tracked_session")
    def test_no_auth_still_reports_host_and_path(self, MockSession) -> None:
        mock_session = _make_client(SECRET, MockSession)
        mock_session.send.return_value = _make_response(500, SECRET, reason="Server Error")

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=1)

        with pytest.raises(RESTClientRetryableError) as excinfo:
            list(client.paginate(path="/items"))

        # scheme/host/path stays in the message for debugging even though the query is always dropped.
        assert "api.example.com/items" in str(excinfo.value)
