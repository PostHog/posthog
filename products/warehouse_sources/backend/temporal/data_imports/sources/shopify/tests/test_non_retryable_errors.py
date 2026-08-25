import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource


def _http_error_message(status_code: int, reason: str) -> str:
    # Build the exact string requests.raise_for_status produces, so the test breaks if
    # the match substring ever drifts from the real message format.
    response = requests.models.Response()
    response.status_code = status_code
    response.reason = reason
    response.url = "https://msivuk-gs.myshopify.com/admin/api/2025-10/graphql.json"
    with pytest.raises(requests.HTTPError) as exc_info:
        response.raise_for_status()
    return str(exc_info.value)


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Access denied for fulfillmentOrders field.",
        "Shopify GraphQL error: Access denied for markets field.",
    ],
)
def test_graphql_access_denied_is_non_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"GraphQL access-denied error '{error_message}' should match a non-retryable pattern"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify GraphQL error: Throttled",
        "Shopify: internal error from request 500 Internal Server Error",
        "Unexpected graphql response format in Shopify rows read. Keys: ['extensions']",
    ],
)
def test_transient_graphql_errors_stay_retryable(error_message):
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )


@pytest.mark.parametrize(
    "status_code,reason",
    [
        (429, "Too Many Requests"),
        (500, "Internal Server Error"),
        (502, "Bad Gateway"),
        (503, "Service Unavailable"),
    ],
)
def test_transient_http_errors_stay_retryable(status_code, reason):
    error_message = _http_error_message(status_code, reason)
    patterns = ShopifySource().get_non_retryable_errors()
    assert not any(pattern in error_message for pattern in patterns), (
        f"transient error '{error_message}' should remain retryable"
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "Shopify: rate limit exceeded...",
        "Shopify: internal error from request 500 Internal Server Error",
        'Shopify: internal errors in payload [{"message": "internal error", "extensions": {"code": "internal_server_error"}}]',
        "Shopify: connection broken while reading response: Connection broken: IncompleteRead(0 bytes read)",
    ],
)
def test_exhausted_internal_retries_are_classified_as_retryable(error_message):
    # These messages only reach `_handle_import_error` after `_make_paginated_shopify_request`'s
    # own tenacity retries (5 attempts) are exhausted, so they should be logged as a warning
    # and left for Temporal's activity retry rather than reported to error tracking as noise.
    patterns = ShopifySource().get_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"exhausted-retry error '{error_message}' should be classified as retryable"
    )
