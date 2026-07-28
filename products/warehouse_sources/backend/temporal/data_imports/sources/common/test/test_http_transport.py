import pytest
from unittest.mock import patch

import requests
from parameterized import parameterized
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3 import HTTPResponse
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    DEFAULT_RETRY,
    MAX_RETRY_AFTER_SECONDS,
    BoundedRetry,
    TrackedHTTPAdapter,
    _NoRedirectSession,
    make_tracked_adapter,
    make_tracked_session,
)


def _urllib_response(retry_after: str | None) -> HTTPResponse:
    # get_retry_after only reads .headers; a bare HTTPResponse carrying the header is enough.
    return HTTPResponse(headers={"Retry-After": retry_after} if retry_after is not None else {})


@pytest.fixture
def mock_record():
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport.record_request"
    ) as m:
        yield m


def _fake_response(status_code: int = 200, body: bytes = b"ok") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = body
    resp.headers["Content-Length"] = str(len(body))
    return resp


@pytest.fixture
def fake_http_send():
    """Patch the parent `HTTPAdapter.send` so `TrackedHTTPAdapter.send()`'s `super().send()` returns a canned response without touching the network."""

    def _factory(response: Response):
        return patch.object(HTTPAdapter, "send", return_value=response)

    return _factory


def test_make_tracked_session_mounts_tracked_adapter_for_both_schemes():
    session = make_tracked_session()

    https_adapter = session.get_adapter("https://example.com/")
    http_adapter = session.get_adapter("http://example.com/")

    assert isinstance(https_adapter, TrackedHTTPAdapter)
    assert isinstance(http_adapter, TrackedHTTPAdapter)


def test_default_retry_is_bounded():
    assert isinstance(DEFAULT_RETRY, BoundedRetry)


@parameterized.expand(
    [
        # A giant delta-seconds and a far-future HTTP-date both used to reach
        # time.sleep() out of C's PyTime_t range and raise OverflowError.
        ("huge_delta_seconds", "999999999999", MAX_RETRY_AFTER_SECONDS),
        ("far_future_http_date", "Wed, 21 Oct 9999 07:28:00 GMT", MAX_RETRY_AFTER_SECONDS),
        # A small, sane value passes through unclamped.
        ("small_delta_seconds", "5", 5.0),
    ]
)
def test_bounded_retry_caps_retry_after(_name, header_value, expected):
    retry_after = DEFAULT_RETRY.get_retry_after(_urllib_response(header_value))
    assert retry_after is not None
    assert retry_after <= MAX_RETRY_AFTER_SECONDS
    assert retry_after == pytest.approx(expected, abs=1.0)


def test_bounded_retry_returns_none_without_header():
    assert DEFAULT_RETRY.get_retry_after(_urllib_response(None)) is None


def test_bounded_retry_survives_new():
    # `.new()` rebuilds via type(self); sources deriving a policy from DEFAULT_RETRY must stay bounded.
    derived = DEFAULT_RETRY.new(allowed_methods=frozenset(["GET", "POST"]))
    assert isinstance(derived, BoundedRetry)
    assert derived.get_retry_after(_urllib_response("999999999999")) == MAX_RETRY_AFTER_SECONDS


def test_make_tracked_session_uses_default_retry():
    session = make_tracked_session()
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == DEFAULT_RETRY.total
    assert adapter.max_retries.backoff_factor == DEFAULT_RETRY.backoff_factor
    assert set(adapter.max_retries.status_forcelist or ()) == set(DEFAULT_RETRY.status_forcelist or ())


def test_make_tracked_session_honors_custom_retry():
    custom = Retry(total=7, backoff_factor=2.0, status_forcelist=(418,))
    session = make_tracked_session(retry=custom)
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == 7
    assert adapter.max_retries.backoff_factor == 2.0


def test_make_tracked_session_allows_redirects_by_default():
    session = make_tracked_session()
    assert not isinstance(session, _NoRedirectSession)


def test_make_tracked_session_can_disable_redirects():
    session = make_tracked_session(allow_redirects=False)
    assert isinstance(session, _NoRedirectSession)
    # Tracked adapters must still be mounted on the no-redirect session.
    assert isinstance(session.get_adapter("https://example.com/"), TrackedHTTPAdapter)


def test_no_redirect_session_does_not_follow_redirects(mock_record):
    # Even when a caller invokes send() without allow_redirects (as RESTClient does),
    # a 3xx must be returned as-is rather than transparently followed to its target.
    session = make_tracked_session(allow_redirects=False)
    prepared = session.prepare_request(requests.Request("GET", "https://acme.example.com/"))

    redirect = Response()
    redirect.status_code = 302
    redirect.headers["Location"] = "https://169.254.169.254/"
    redirect._content = b""
    redirect.url = "https://acme.example.com/"

    with patch.object(HTTPAdapter, "send", return_value=redirect) as adapter_send:
        response = session.send(prepared)

    assert response.status_code == 302
    # A single dispatch: the redirect target is never fetched.
    assert adapter_send.call_count == 1


def test_make_tracked_session_merges_headers():
    session = make_tracked_session(headers={"X-Source": "stripe", "User-Agent": "posthog/test"})

    assert session.headers["X-Source"] == "stripe"
    assert session.headers["User-Agent"] == "posthog/test"


def test_make_tracked_adapter_with_none_retry_uses_default():
    """`retry=None` is the explicit "use default" sentinel — not "disable retries"."""
    adapter = make_tracked_adapter(retry=None)

    # Should equal the DEFAULT_RETRY total
    assert adapter.max_retries.total == DEFAULT_RETRY.total


def test_send_forwards_redact_values_to_record(mock_record, fake_http_send):
    session = make_tracked_session(redact_values=("sk_live_secret",))

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        session.get("https://api.example.com/v1/ok")

    assert mock_record.call_args.kwargs["redact_values"] == ("sk_live_secret",)


def test_send_defaults_redact_values_to_empty(mock_record, fake_http_send):
    session = make_tracked_session()

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        session.get("https://api.example.com/v1/ok")

    assert mock_record.call_args.kwargs["redact_values"] == ()


def test_send_captures_by_default(mock_record, fake_http_send):
    session = make_tracked_session()

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        session.get("https://api.example.com/v1/ok")

    assert mock_record.call_args.kwargs["capture"] is True


def test_send_forwards_capture_disabled_to_record(mock_record, fake_http_send):
    session = make_tracked_session(capture=False)

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        session.get("https://api.example.com/v1/ok")

    assert mock_record.call_args.kwargs["capture"] is False


def test_send_records_request_for_2xx(mock_record, fake_http_send):
    session = make_tracked_session()

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        response = session.get("https://api.example.com/v1/ok")

    assert response.status_code == 200
    assert mock_record.call_count == 1
    args, kwargs = mock_record.call_args
    # First positional arg is the PreparedRequest, second is the Response.
    assert args[0].url == "https://api.example.com/v1/ok"
    assert args[1].status_code == 200
    assert kwargs["exception"] is None
    assert "started_at_monotonic" in kwargs


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 502, 503])
def test_send_records_request_for_non_2xx(mock_record, fake_http_send, status_code):
    session = make_tracked_session(retry=Retry(total=0))

    with fake_http_send(_fake_response(status_code=status_code, body=b"err")):
        response = session.get("https://api.example.com/v1/err")

    assert response.status_code == status_code
    assert mock_record.call_count == 1
    response_arg = mock_record.call_args.args[1]
    assert response_arg.status_code == status_code


def test_send_records_request_on_connection_exception(mock_record):
    """Network errors must still call record_request, and the exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))
    with pytest.raises(requests.exceptions.RequestException):
        # 127.0.0.1:1 is reserved/never-listening; resolves instantly with a connection refused.
        session.get("http://127.0.0.1:1/", timeout=2)

    assert mock_record.call_count == 1
    request_arg = mock_record.call_args.args[0]
    response_arg = mock_record.call_args.args[1]
    assert request_arg.url == "http://127.0.0.1:1/"
    assert response_arg is None
    assert mock_record.call_args.kwargs["exception"] is not None


def test_send_does_not_mask_real_outcome_when_record_raises(fake_http_send):
    """If record_request itself raises, the response must still be returned to the caller."""
    session = make_tracked_session()

    with (
        fake_http_send(_fake_response(status_code=200, body=b"ok")),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport.record_request",
            side_effect=RuntimeError("observer broken"),
        ),
    ):
        # No exception should bubble up; the swallow happens inside `TrackedHTTPAdapter.send`'s `finally`.
        response = session.get("https://api.example.com/")

    assert response.status_code == 200


def test_send_does_not_mask_real_exception_when_record_raises():
    """If both the request fails AND the observer raises, the original exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport.record_request",
        side_effect=RuntimeError("observer broken"),
    ):
        with pytest.raises(requests.exceptions.RequestException):
            session.get("http://127.0.0.1:1/", timeout=2)
