import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH,
)
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


def test_payment_required_is_non_retryable():
    error_message = _http_error_message(402, "Payment Required")
    assert SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH in error_message
    patterns = ShopifySource().get_non_retryable_errors()
    assert any(pattern in error_message for pattern in patterns), (
        f"402 Payment Required error '{error_message}' should match a non-retryable pattern"
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
