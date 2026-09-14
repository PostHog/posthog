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
CONFIG_SETUP_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup"


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
    def test_ignore_action_with_non_json_body_is_skipped(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        # A 404 whose body is empty (not JSON) — the shape an endpoint returns for a missing
        # resource. The ignore must skip it, not blow up parsing the body.
        resp = Response()
        resp.status_code = 404
        resp.reason = "Not Found"
        resp._content = b""
        resp.url = "https://api.example.com/items"
        mock_session.send.return_value = resp
        hooks = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="issue_hashes")

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=1)
        with patch(f"{CONFIG_SETUP_MODULE}.logger") as mock_logger:
            pages = list(
                client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks)
            )

        assert pages == []
        assert mock_session.send.call_count == 1
        # A stale fan-out parent is dropped here, so the ignore has to be countable per schema.
        logged = mock_logger.info.call_args
        assert logged.args[0] == "data_imports.response_action_ignored"
        assert logged.kwargs["resource"] == "issue_hashes"
        assert logged.kwargs["status_code"] == 404

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

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_json_field_action_matches_body_value_only(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.side_effect = [
            _make_response({"code": 40100, "message": "too many requests"}),
            # A row that merely contains the same number must not be classified as an error —
            # what substring matching on the serialized body would get wrong.
            _make_response({"code": 0, "results": [{"id": 40100}]}),
        ]
        hooks = create_response_hooks([{"json_field": "code", "json_values": [40100], "action": "retry"}])

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks)
        )

        assert pages == [[{"id": 40100}]]
        assert mock_session.send.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_json_field_action_reads_a_nested_path(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.side_effect = [
            _make_response({"error": {"type": "rate_limit"}}),
            _make_response({"results": [{"id": 1}]}),
        ]
        hooks = create_response_hooks([{"json_field": "error.type", "json_values": ["rate_limit"], "action": "retry"}])

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator(), hooks=hooks)
        )

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2
