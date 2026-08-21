import pytest
from unittest import mock

from requests.exceptions import ChunkedEncodingError, SSLError

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
    ShopifyRetryableError,
    _get_shopify_access_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource


def _mock_response(status_code: int, ok: bool, json_data: dict | None = None, reason: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.reason = reason
    response.json.return_value = json_data or {}
    return response


def _patched_token_post(post: mock.MagicMock):
    return mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session",
        return_value=mock.MagicMock(post=post),
    )


def _patched_token_call(response: mock.MagicMock):
    return _patched_token_post(mock.MagicMock(return_value=response))


def test_get_access_token_asks_shopify_for_json_errors():
    # Without an explicit JSON Accept header Shopify renders 4xx OAuth errors as an HTML page,
    # so _parse_oauth_error never sees the error code and every failure collapses to the
    # generic message.
    session_factory = mock.MagicMock(
        return_value=mock.MagicMock(
            post=mock.MagicMock(return_value=_mock_response(200, ok=True, json_data={"access_token": "tok"}))
        )
    )
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session",
        session_factory,
    ):
        _get_shopify_access_token("store", "client-id", "client-secret")
    assert session_factory.call_args.kwargs["headers"] == {"Accept": "application/json"}


def test_get_access_token_4xx_html_body_falls_back_to_generic_message():
    # Shopify (or an intermediary) can still answer a 4xx with a non-JSON body; the parse must
    # degrade to the generic credentials message instead of raising a decode error.
    response = _mock_response(400, ok=False)
    response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
    with _patched_token_call(response):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert SHOPIFY_ACCESS_TOKEN_AUTH_ERROR in error_message
    assert "HTTP 400" in error_message


@pytest.mark.parametrize(
    "status_code,reason",
    [(429, "Too Many Requests"), (500, "Internal Server Error"), (502, "Bad Gateway"), (503, "Service Unavailable")],
)
@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_transient_retries_then_reraises(_mock_sleep, status_code, reason):
    # A 429/5xx on the token endpoint (e.g. the 502 Bad Gateway seen in production) is transient,
    # so it must retry locally with backoff and, if it never recovers, reraise a retryable error
    # rather than a non-retryable one.
    post = mock.MagicMock(return_value=_mock_response(status_code, ok=False, reason=reason))
    with _patched_token_post(post):
        with pytest.raises(ShopifyRetryableError) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert post.call_count == 5
    error_message = str(exc_info.value)
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient token error '{error_message}' should remain retryable"
    )


@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_retries_5xx_then_succeeds(_mock_sleep):
    # A transient 502 followed by a healthy response should mint the token, not fail the import.
    post = mock.MagicMock(
        side_effect=[
            _mock_response(502, ok=False, reason="Bad Gateway"),
            _mock_response(200, ok=True, json_data={"access_token": "tok"}),
        ]
    )
    with _patched_token_post(post):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert post.call_count == 2


def test_get_access_token_success_returns_token():
    with _patched_token_call(_mock_response(200, ok=True, json_data={"access_token": "tok"})):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"


@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_retries_ssl_error_then_succeeds(_mock_sleep):
    # A transient TLS drop on the token endpoint surfaces from `post` as SSLError (a
    # ConnectionError); it's transient, so reissue the request rather than failing the import.
    post = mock.MagicMock(
        side_effect=[
            SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
            _mock_response(200, ok=True, json_data={"access_token": "tok"}),
        ]
    )
    with _patched_token_post(post):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert post.call_count == 2


@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_reraises_after_persistent_ssl_error(_mock_sleep):
    # A persistent connection failure must exhaust the retry budget and re-raise the original
    # error rather than being swallowed, so the import still fails (and Temporal retries it).
    post = mock.MagicMock(side_effect=SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred"))
    with _patched_token_post(post):
        with pytest.raises(SSLError):
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert post.call_count == 5


@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_retries_connection_broken_then_succeeds(_mock_sleep):
    # A connection dropped mid-response surfaces from `post` as ChunkedEncodingError; it's
    # transient, so reissue the request rather than letting it fail the import.
    post = mock.MagicMock(
        side_effect=[
            ChunkedEncodingError("Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"),
            _mock_response(200, ok=True, json_data={"access_token": "tok"}),
        ]
    )
    with _patched_token_post(post):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert post.call_count == 2


@mock.patch("tenacity.nap.time.sleep")
def test_get_access_token_reraises_after_exhausting_retries(_mock_sleep):
    # When the connection breaks on every attempt, the retry must stop after the attempt cap
    # and reraise the underlying error rather than swallowing it.
    post = mock.MagicMock(side_effect=ChunkedEncodingError("Connection broken: IncompleteRead(0 bytes read)"))
    with _patched_token_post(post):
        with pytest.raises(ChunkedEncodingError):
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert post.call_count == 5
