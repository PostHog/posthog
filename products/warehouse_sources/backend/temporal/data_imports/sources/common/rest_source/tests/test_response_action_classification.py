import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"


def _make_response(body: Any, status_code: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.example.com/items"
    return resp


class TestResponseActionClassification:
    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_retry_action_on_200_body_then_succeeds(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        # HTTP 200 carrying an in-body rate-limit signal, then a clean page.
        mock_session.send.side_effect = [
            _make_response({"status": {"error_code": 429}}),
            _make_response({"results": [{"id": 1}]}),
        ]
        hooks = create_response_hooks([{"content": '"error_code": 429', "action": "retry"}])

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks)
        )

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_retry_action_persistent_reraises_retryable(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"status": {"error_code": 429}})
        hooks = create_response_hooks([{"content": "error_code", "action": "retry", "message": "rate limited"}])

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=3)
        with pytest.raises(RESTClientRetryableError, match="rate limited"):
            list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks))
        assert mock_session.send.call_count == 3

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_raise_action_is_permanent_with_message(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"error": {"code": "InvalidWindow"}})
        hooks = create_response_hooks(
            [{"content": "InvalidWindow", "action": "raise", "message": "Window too old — trigger a full resync"}]
        )

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=3)
        with pytest.raises(ValueError, match="trigger a full resync"):
            list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks))
        # Permanent: raised on the first response, never retried.
        assert mock_session.send.call_count == 1

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_unmatched_4xx_still_raises_for_status(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"error": "not found"}, status_code=404, reason="Not Found")
        # A rule that doesn't match this response must not swallow the 404.
        hooks = create_response_hooks([{"status_code": 400, "action": "ignore"}])

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=1)
        with pytest.raises(HTTPError):
            list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks))
