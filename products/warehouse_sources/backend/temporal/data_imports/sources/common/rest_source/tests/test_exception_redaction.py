from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
SECRET = "sk_live_super_secret_key"


def _make_response(status_code: int, reason: str) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    # The credential rides in the query string, so it lands in the URL that raise_for_status /
    # the retryable-error message embed — exactly the leak this feature closes.
    resp.url = f"https://api.example.com/items?api_key={SECRET}"
    resp._content = b'{"error": "nope"}'
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestExceptionRedaction:
    @parameterized.expand(
        [
            # (status_code, reason, keep_marker)
            ("client_error_400", 400, "Bad Request", "400"),
            ("server_error_500", 500, "Server Error", "HTTP 500"),
        ]
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_query_param_secret_is_redacted_from_error(
        self, _name: str, status_code: int, reason: str, keep_marker: str, MockSession
    ) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}

        def _prep(request: Any) -> MagicMock:
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        mock_session.prepare_request.side_effect = _prep
        mock_session.send.return_value = _make_response(status_code, reason)

        client = RESTClient(
            base_url="https://api.example.com",
            auth=APIKeyAuth(api_key=SECRET, name="api_key", location="query"),
            max_retry_attempts=1,
        )

        with pytest.raises((Exception,)) as excinfo:
            list(client.paginate(path="/items"))

        message = str(excinfo.value)
        assert SECRET not in message
        assert "***" in message
        # The status information is preserved — only the secret is scrubbed.
        assert keep_marker in message

    @patch(f"{MODULE}.make_tracked_session")
    def test_no_auth_leaves_message_untouched(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}

        def _prep(request: Any) -> MagicMock:
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        mock_session.prepare_request.side_effect = _prep
        mock_session.send.return_value = _make_response(500, "Server Error")

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=1)

        with pytest.raises(RESTClientRetryableError) as excinfo:
            list(client.paginate(path="/items"))

        # Without registered secrets there is nothing to redact, so the URL is reported verbatim.
        assert "api.example.com/items" in str(excinfo.value)
