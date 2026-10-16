import ssl

import pytest
from unittest import mock

from requests.exceptions import ChunkedEncodingError, SSLError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_APP_NOT_INSTALLED_ERROR,
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
    SHOPIFY_ACCESS_TOKEN_INVALID_CLIENT_ERROR,
    SHOPIFY_ACCESS_TOKEN_IS_APP_SECRET_ERROR,
    SHOPIFY_ACCESS_TOKEN_SHOP_NOT_PERMITTED_ERROR,
    SHOPIFY_ACCESS_TOKEN_UNSUPPORTED_GRANT_ERROR,
    SHOPIFY_MISSING_CREDENTIALS_ERROR,
    SHOPIFY_STORE_NOT_FOUND_ERROR,
    ShopifyRetryableError,
    _get_shopify_access_token,
    _resolve_access_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

TOKEN_OK = ScriptedResponse(json={"access_token": "tok"})
# A chunked body with an invalid chunk length fails the read as a connection dropped mid-response.
BROKEN_CHUNK = ScriptedResponse(headers={"Transfer-Encoding": "chunked"}, body=b"zz\r\n")


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_get_access_token_4xx_is_non_retryable(status_code):
    with scripted_network(always(ScriptedResponse(status=status_code))):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert SHOPIFY_ACCESS_TOKEN_AUTH_ERROR in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"4xx token error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_code,expected_message",
    [
        ("invalid_client", SHOPIFY_ACCESS_TOKEN_INVALID_CLIENT_ERROR),
        ("unsupported_grant_type", SHOPIFY_ACCESS_TOKEN_UNSUPPORTED_GRANT_ERROR),
        ("shop_not_permitted", SHOPIFY_ACCESS_TOKEN_SHOP_NOT_PERMITTED_ERROR),
        ("app_not_installed", SHOPIFY_ACCESS_TOKEN_APP_NOT_INSTALLED_ERROR),
    ],
)
def test_get_access_token_4xx_maps_shopify_error_code(error_code, expected_message):
    # Shopify names the cause in the 4xx body, so each recognized code must surface its own
    # message. The wizard shows this string, so Shopify's raw error, description and status
    # must stay out of it and live in the log instead.
    body = {"error": error_code, "error_description": "Shopify says so"}
    with scripted_network(always(ScriptedResponse(status=400, json=body))):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert error_message == expected_message
    assert "Shopify says so" not in error_message
    assert "400" not in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"4xx token error '{error_message}' should match a non-retryable pattern"
    )


def test_get_access_token_asks_shopify_for_json_errors():
    # Without an explicit JSON Accept header Shopify renders 4xx OAuth errors as an HTML page,
    # so _parse_oauth_error never sees the error code and every failure collapses to the
    # generic message.
    with scripted_network([TOKEN_OK]) as network:
        _get_shopify_access_token("store", "client-id", "client-secret")

    assert network.session_options[0]["headers"] == {"Accept": "application/json"}
    assert network.requests_log[0].headers["accept"] == "application/json"


def test_get_access_token_4xx_html_body_falls_back_to_generic_message():
    # Shopify (or an intermediary) can still answer a 4xx with a non-JSON body; the parse must
    # degrade to the generic credentials message instead of raising a decode error.
    with scripted_network(always(ScriptedResponse(status=400, body=b"<html>Bad request</html>"))):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert error_message == SHOPIFY_ACCESS_TOKEN_AUTH_ERROR


def test_get_access_token_404_reports_missing_store():
    # A 404 means the store subdomain doesn't resolve to a real store — a distinct,
    # non-retryable failure that reconnecting the app can't fix, so it must surface the
    # store-not-found message rather than the credentials error.
    with scripted_network(always(ScriptedResponse(status=404))):
        with pytest.raises(Exception) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")

    error_message = str(exc_info.value)
    assert SHOPIFY_STORE_NOT_FOUND_ERROR in error_message
    assert SHOPIFY_ACCESS_TOKEN_AUTH_ERROR not in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"404 token error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_get_access_token_transient_retries_then_reraises(status_code):
    # A 429/5xx on the token endpoint (e.g. the 502 Bad Gateway seen in production) is transient,
    # so it must retry locally with backoff and, if it never recovers, reraise a retryable error
    # rather than a non-retryable one.
    with scripted_network(always(ScriptedResponse(status=status_code))) as network:
        with pytest.raises(ShopifyRetryableError) as exc_info:
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert len(network.requests_log) == 5
    error_message = str(exc_info.value)
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient token error '{error_message}' should remain retryable"
    )


def test_get_access_token_retries_5xx_then_succeeds():
    # A transient 502 followed by a healthy response should mint the token, not fail the import.
    with scripted_network([ScriptedResponse(status=502), TOKEN_OK]) as network:
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert len(network.requests_log) == 2


def test_get_access_token_success_returns_token():
    with scripted_network([TOKEN_OK]):
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"


def test_get_access_token_retries_ssl_error_then_succeeds():
    # A transient TLS drop on the token endpoint surfaces from `post` as SSLError (a
    # ConnectionError); it's transient, so reissue the request rather than failing the import.
    ssl_error = ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
    with scripted_network([ssl_error, TOKEN_OK]) as network:
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert len(network.requests_log) == 2


def test_get_access_token_reraises_after_persistent_ssl_error():
    # A persistent connection failure must exhaust the retry budget and re-raise the original
    # error rather than being swallowed, so the import still fails (and Temporal retries it).
    with scripted_network(always(ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred"))) as network:
        with pytest.raises(SSLError):
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert {request.path for request in network.requests_log} == {"/admin/oauth/access_token"}
    assert len(network.requests_log) >= 5


def test_get_access_token_retries_connection_broken_then_succeeds():
    # A connection dropped mid-response surfaces from `post` as ChunkedEncodingError; it's
    # transient, so reissue the request rather than letting it fail the import.
    with scripted_network([BROKEN_CHUNK, TOKEN_OK]) as network:
        assert _get_shopify_access_token("store", "client-id", "client-secret") == "tok"
    assert len(network.requests_log) == 2


def test_get_access_token_reraises_after_exhausting_retries():
    # When the connection breaks on every attempt, the retry must stop after the attempt cap
    # and reraise the underlying error rather than swallowing it.
    with scripted_network(always(BROKEN_CHUNK)) as network:
        with pytest.raises(ChunkedEncodingError):
            _get_shopify_access_token("store", "client-id", "client-secret")
    assert len(network.requests_log) == 5


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Access denied for fulfillmentOrders field.",
        "Shopify GraphQL error: Access denied for paymentTerms field. Required access: `read_payment_terms` access scope.",
        "Shopify GraphQL error: Access denied for orders field.; Access denied for paymentTerms field.",
    ],
)
def test_graphql_access_denied_is_non_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"GraphQL access-scope error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "402 Client Error: Payment Required for url: https://my-store.myshopify.com/admin/api/2025-10/graphql.json",
        "402 Client Error: Payment Required for url: https://another-store.myshopify.com/admin/api/2024-01/graphql.json",
    ],
)
def test_payment_required_is_non_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"402 Payment Required error '{error_message}' should match a non-retryable pattern"
    )


def test_resolve_access_token_uses_a_supplied_token_without_calling_shopify():
    # A supplied Admin API token belongs to one store, so it works where the client_credentials
    # grant cannot. Minting anyway would send the token endpoint credentials it does not have.
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token"
    ) as mint:
        assert _resolve_access_token("store", None, None, "shpat_supplied") == "shpat_supplied"
    mint.assert_not_called()


def test_resolve_access_token_mints_when_only_client_credentials_are_set():
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token",
        return_value="minted",
    ) as mint:
        assert _resolve_access_token("store", "client-id", "client-secret", None) == "minted"
    mint.assert_called_once_with("store", "client-id", "client-secret")


@pytest.mark.parametrize(
    "client_id,client_secret,access_token,expected_message",
    [
        # The client secret and the Admin API token sit on adjacent screens in Shopify and both
        # are opaque strings, so name the mix-up instead of sending the secret to the Admin API
        # and reporting the 401 it comes back with.
        ("", "", "shpss_looks_like_a_secret", SHOPIFY_ACCESS_TOKEN_IS_APP_SECRET_ERROR),
        (None, None, None, SHOPIFY_MISSING_CREDENTIALS_ERROR),
        # Half a client credentials pair cannot mint a token, and the form no longer marks
        # either half required, so this reaches the resolver rather than being caught earlier.
        ("client-id", None, None, SHOPIFY_MISSING_CREDENTIALS_ERROR),
        (None, "client-secret", None, SHOPIFY_MISSING_CREDENTIALS_ERROR),
    ],
)
def test_resolve_access_token_rejects_unusable_credentials(client_id, client_secret, access_token, expected_message):
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token"
    ) as mint:
        with pytest.raises(Exception) as exc_info:
            _resolve_access_token("store", client_id, client_secret, access_token)

    mint.assert_not_called()
    error_message = str(exc_info.value)
    assert expected_message in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"credential error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify: rate limit exceeded...",
        "Shopify: internal error from request 503 Service Unavailable",
        "Unexpected graphql response format in Shopify rows read. Keys: ['extensions']",
        "429 Client Error: Too Many Requests for url: https://my-store.myshopify.com/admin/api/2025-10/graphql.json",
    ],
)
def test_transient_graphql_errors_stay_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )
