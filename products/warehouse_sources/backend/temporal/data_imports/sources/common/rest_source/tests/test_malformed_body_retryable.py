import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"


def _make_response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.example.com/items"
    return resp


class TestMalformedBodyRetryable:
    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_malformed_then_valid_recovers(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        # A dict-without-the-selector-key (wrong shape) then a proper page.
        mock_session.send.side_effect = [
            _make_response({"error": "temporary glitch"}),
            _make_response({"data": [{"id": 1}]}),
        ]

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(
                path="/items",
                data_selector="data",
                paginator=SinglePagePaginator(),
                data_selector_malformed_retryable=True,
            )
        )

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2

    @pytest.mark.parametrize(
        "bad_body",
        [
            pytest.param("just a string", id="bare_string"),
            pytest.param({"error": "nope"}, id="dict_without_key"),
            pytest.param({"data": {"id": 1}}, id="key_present_but_not_a_list"),
        ],
    )
    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_persistent_malformed_body_reraises_retryable(self, MockSession, _sleep, bad_body) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response(bad_body)

        client = RESTClient(base_url="https://api.example.com", max_retry_attempts=3)
        with pytest.raises(RESTClientRetryableError, match="Unexpected 200 response body shape"):
            list(
                client.paginate(
                    path="/items",
                    data_selector="data",
                    paginator=SinglePagePaginator(),
                    data_selector_malformed_retryable=True,
                )
            )
        assert mock_session.send.call_count == 3

    @patch("tenacity.nap.time.sleep")
    @patch(f"{MODULE}.make_tracked_session")
    def test_valid_list_body_is_not_retried(self, MockSession, _sleep) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"data": [{"id": 1}, {"id": 2}]})

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(
                path="/items",
                data_selector="data",
                paginator=SinglePagePaginator(),
                data_selector_malformed_retryable=True,
            )
        )

        assert pages == [[{"id": 1}, {"id": 2}]]
        assert mock_session.send.call_count == 1
