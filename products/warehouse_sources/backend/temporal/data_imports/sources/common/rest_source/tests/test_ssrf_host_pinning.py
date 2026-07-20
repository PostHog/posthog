import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"


def _make_response(json_body: Any, status_code: int = 200, headers: Optional[dict[str, str]] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode()
    resp.headers["Content-Type"] = "application/json"
    for key, value in (headers or {}).items():
        resp.headers[key] = value
    return resp


def _session_echoing_url(MockSession) -> MagicMock:
    # Emulate Session.prepare_request: the prepared URL is the request's final URL, which is
    # what the host check inspects. Absolute next-page URLs set by the paginator flow straight
    # through here.
    mock_session = MockSession.return_value
    mock_session.headers = {}

    def _prep(request: Any) -> MagicMock:
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    mock_session.prepare_request.side_effect = _prep
    return mock_session


class TestSSRFHostPinning:
    @parameterized.expand(
        [
            # (allowed_hosts, next_page_host, expect_reject)
            ("same_host_pins_rejects_offhost", [], "evil.com", True),
            ("same_host_allows_base_host", [], "api.example.com", False),
            ("extra_host_in_allowlist_permitted", ["cdn.example.com"], "cdn.example.com", False),
            ("host_not_in_allowlist_rejected", ["cdn.example.com"], "evil.com", True),
            ("no_allowlist_disables_enforcement", None, "evil.com", False),
        ]
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_offhost_next_url_enforcement(
        self, _name: str, allowed_hosts: Optional[list[str]], next_host: str, expect_reject: bool, MockSession
    ) -> None:
        mock_session = _session_echoing_url(MockSession)
        mock_session.send.side_effect = [
            _make_response({"results": [{"id": 1}], "next": f"https://{next_host}/page2"}),
            _make_response({"results": [{"id": 2}], "next": None}),
        ]

        client = RESTClient(base_url="https://api.example.com", allowed_hosts=allowed_hosts)
        pager = client.paginate(
            path="/items", data_selector="results", paginator=JSONResponsePaginator(next_url_path="next")
        )

        if expect_reject:
            with pytest.raises(ValueError, match="disallowed host"):
                list(pager)
            # The first page was yielded, but the off-host second request never went out.
            assert mock_session.send.call_count == 1
        else:
            pages = list(pager)
            assert [row["id"] for page in pages for row in page] == [1, 2]

    @patch(f"{MODULE}.make_tracked_session")
    def test_redirect_rejected_when_disabled(self, MockSession) -> None:
        mock_session = _session_echoing_url(MockSession)
        mock_session.send.return_value = _make_response(
            {}, status_code=302, headers={"Location": "https://evil.com/steal"}
        )

        client = RESTClient(base_url="https://api.example.com", allow_redirects=False)
        with pytest.raises(ValueError, match="Unexpected redirect"):
            list(client.paginate(path="/items", data_selector="results"))

        # The redirect target was never followed: send ran once and got no allow_redirects.
        _, kwargs = mock_session.send.call_args
        assert kwargs.get("allow_redirects") is False

    @patch(f"{MODULE}.make_tracked_session")
    def test_redirects_followed_by_default(self, MockSession) -> None:
        mock_session = _session_echoing_url(MockSession)
        mock_session.send.return_value = _make_response({"results": [{"id": 1}]})

        client = RESTClient(base_url="https://api.example.com")
        list(client.paginate(path="/items", data_selector="results"))

        _, kwargs = mock_session.send.call_args
        assert kwargs.get("allow_redirects") is True
