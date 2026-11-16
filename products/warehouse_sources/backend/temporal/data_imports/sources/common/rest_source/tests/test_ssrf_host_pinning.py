import io
import gzip
import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response, Session
from requests.exceptions import ConnectionError as RequestsConnectionError
from urllib3 import HTTPResponse

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)

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


S3_PATTERN = r"[a-z0-9.-]+\.s3\.[a-z0-9-]+\.amazonaws\.com"
STORAGE_URL = "https://bucket.s3.us-east-1.amazonaws.com/responses/page.json.gz?X-Amz-Signature=sig"


def _storage_response(body: bytes, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.raw = HTTPResponse(body=io.BytesIO(body), status=status, preload_content=False)
    return resp


def _redirect_to_storage() -> Response:
    return _make_response({}, status_code=303, headers={"Location": STORAGE_URL})


def _presigned_client() -> tuple[Session, RESTClient]:
    session = Session()
    client = RESTClient(
        base_url="https://api.example.com",
        auth=BearerTokenAuth("api-secret"),
        headers={"X-Api-Key": "header-secret"},
        session=session,
        max_retry_attempts=1,
        allow_redirects=False,
        presigned_redirect_host_pattern=S3_PATTERN,
    )
    return session, client


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

    @parameterized.expand(
        [
            # base origin is https://api.example.com (implicit :443); an allowed hostname reached
            # over a downgraded scheme or a different port is still off-origin and must be rejected.
            ("http_downgrade_same_host_rejected", "http://api.example.com/page2", True),
            ("different_port_same_host_rejected", "https://api.example.com:8443/page2", True),
            ("https_default_port_allowed", "https://api.example.com/page2", False),
            ("https_explicit_default_port_allowed", "https://api.example.com:443/page2", False),
        ]
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_scheme_and_port_pinned_to_base_origin(
        self, _name: str, next_url: str, expect_reject: bool, MockSession
    ) -> None:
        mock_session = _session_echoing_url(MockSession)
        mock_session.send.side_effect = [
            _make_response({"results": [{"id": 1}], "next": next_url}),
            _make_response({"results": [{"id": 2}], "next": None}),
        ]

        client = RESTClient(base_url="https://api.example.com", allowed_hosts=[])
        pager = client.paginate(
            path="/items", data_selector="results", paginator=JSONResponsePaginator(next_url_path="next")
        )

        if expect_reject:
            with pytest.raises(ValueError, match="scheme|port"):
                list(pager)
            # The first page was yielded, but the downgraded/off-port second request never went out.
            assert mock_session.send.call_count == 1
        else:
            pages = list(pager)
            assert [row["id"] for page in pages for row in page] == [1, 2]

    @parameterized.expand(
        [
            ("redirects_disabled", None, "https://evil.com/steal"),
            (
                "host_outside_pattern",
                S3_PATTERN,
                "https://evil.com/a.s3.us-east-1.amazonaws.com?X-Amz-Signature=sekret",
            ),
            ("non_s3_aws_host", S3_PATTERN, "https://ec2-1-2-3-4.compute-1.amazonaws.com/o?X-Amz-Signature=sekret"),
            ("presigned_host_over_http", S3_PATTERN, "http://b.s3.us-east-1.amazonaws.com/o?X-Amz-Signature=sekret"),
            ("scheme_relative_location", S3_PATTERN, "//b.s3.us-east-1.amazonaws.com/o?X-Amz-Signature=sekret"),
        ]
    )
    @patch(f"{MODULE}.make_tracked_session")
    def test_redirect_rejected_when_disabled(
        self, _name: str, presigned_pattern: Optional[str], location: str, MockSession
    ) -> None:
        mock_session = _session_echoing_url(MockSession)
        mock_session.send.return_value = _make_response({}, status_code=303, headers={"Location": location})

        client = RESTClient(
            base_url="https://api.example.com",
            allow_redirects=False,
            presigned_redirect_host_pattern=presigned_pattern,
        )
        with pytest.raises(ValueError, match="Unexpected redirect") as exc_info:
            list(client.paginate(path="/items", data_selector="results"))
        assert "sekret" not in str(exc_info.value)
        assert mock_session.send.call_count == 1

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

    @parameterized.expand([("plain_body", False), ("gzipped_body", True)])
    def test_presigned_redirect_fetched_without_credentials(self, _name: str, gzipped: bool) -> None:
        body = json.dumps({"results": [{"id": 1}]}).encode()
        session, client = _presigned_client()

        with patch.object(
            session,
            "send",
            side_effect=[_redirect_to_storage(), _storage_response(gzip.compress(body) if gzipped else body)],
        ) as send:
            pages = list(client.paginate(path="/items", method="post", data_selector="results"))

        assert pages == [[{"id": 1}]]
        followed = send.call_args_list[1].args[0]
        assert (followed.method, followed.url) == ("GET", STORAGE_URL)
        assert "Authorization" not in followed.headers
        assert "X-Api-Key" not in followed.headers

    @parameterized.expand(
        [
            ("expired_url", _storage_response(b"", status=403), RESTClientRetryableError),
            (
                "connection_error",
                RequestsConnectionError(f"Max retries exceeded with url: {STORAGE_URL}"),
                RESTClientRetryableError,
            ),
            ("corrupt_gzip", _storage_response(b"\x1f\x8b" + b"\x00" * 20), RESTClientRetryableError),
            (
                "truncated_gzip",
                _storage_response(gzip.compress(b'{"results": []}' * 100)[:30]),
                RESTClientRetryableError,
            ),
            ("gzip_bomb", _storage_response(gzip.compress(b"\x00" * 4096)), RESTClientNonRetryableError),
            ("oversized_body", _storage_response(b'{"results": []}' + b" " * 4096), RESTClientNonRetryableError),
        ]
    )
    @patch(f"{MODULE}.MAX_PRESIGNED_RESPONSE_BYTES", 1024)
    def test_presigned_fetch_failure_hides_signed_url(
        self, _name: str, storage_outcome: Any, expected: type[Exception]
    ) -> None:
        session, client = _presigned_client()

        with patch.object(session, "send", side_effect=[_redirect_to_storage(), storage_outcome]):
            with pytest.raises(expected) as exc_info:
                list(client.paginate(path="/items", method="post", data_selector="results"))

        assert "X-Amz-Signature" not in str(exc_info.value)
        assert exc_info.value.__cause__ is None
