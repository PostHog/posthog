import pytest
from unittest.mock import MagicMock, patch

import requests
from requests.exceptions import ChunkedEncodingError
from tenacity import Future, RetryCallState, Retrying

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    SHOPIFY_GRAPHQL_OBJECTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    _SHOPIFY_MAX_THROTTLE_WAIT_SECONDS,
    ShopifyRetryableError,
    _get_retryable_error,
    _make_paginated_shopify_request,
    _shopify_retry_wait,
    _throttle_retry_after,
)


def _throttled_payload(requested: float, available: float, restore_rate: float) -> dict:
    return {
        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
        "extensions": {
            "cost": {
                "requestedQueryCost": requested,
                "throttleStatus": {
                    "maximumAvailable": 2000,
                    "currentlyAvailable": available,
                    "restoreRate": restore_rate,
                },
            }
        },
    }


def _retry_state(exc: Exception) -> RetryCallState:
    state = RetryCallState(retry_object=Retrying(), fn=None, args=(), kwargs={})
    state.outcome = Future.construct(1, exc, True)
    return state


def test_throttle_retry_after_computes_refill_time():
    # deficit 90 points at 50/sec => 1.8s
    assert _throttle_retry_after(_throttled_payload(100, 10, 50)) == pytest.approx(1.8)


def test_throttle_retry_after_is_capped():
    # An enormous deficit (or tiny restore rate) must not stall the worker indefinitely.
    assert _throttle_retry_after(_throttled_payload(10_000, 0, 1)) == _SHOPIFY_MAX_THROTTLE_WAIT_SECONDS


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"extensions": {}},
        {"extensions": {"cost": {"requestedQueryCost": 100}}},
        {"extensions": {"cost": {"requestedQueryCost": 100, "throttleStatus": {"currentlyAvailable": 10}}}},
        # restoreRate of 0 would divide by zero
        _throttled_payload(100, 10, 0),
        # bucket already has enough headroom
        _throttled_payload(100, 200, 50),
    ],
)
def test_throttle_retry_after_returns_none_when_unavailable(payload):
    assert _throttle_retry_after(payload) is None


def test_get_retryable_error_attaches_retry_after():
    error = _get_retryable_error(_throttled_payload(100, 10, 50))
    assert isinstance(error, ShopifyRetryableError)
    assert error.retry_after == pytest.approx(1.8)


def test_get_retryable_error_throttled_without_cost_has_no_retry_after():
    error = _get_retryable_error({"errors": [{"message": "Throttled"}]})
    assert isinstance(error, ShopifyRetryableError)
    assert error.retry_after is None


def test_retry_wait_honors_throttle_refill_time():
    # The exponential floor is ~1s on the first attempt; Shopify's refill time must win.
    wait = _shopify_retry_wait(_retry_state(ShopifyRetryableError("rate limit", retry_after=20.0)))
    assert wait >= 20.0


def test_retry_wait_falls_back_to_backoff_without_retry_after():
    wait = _shopify_retry_wait(_retry_state(ShopifyRetryableError("internal error")))
    assert 1.0 <= wait <= 2.0  # initial=1, max=30, jitter up to 1s on attempt 1


def _ok_page() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": {ABANDONED_CHECKOUTS: {"nodes": [{"id": "1"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
    }
    return response


@patch("tenacity.nap.time.sleep")
def test_request_retries_connection_broken_mid_stream_then_succeeds(_mock_sleep):
    # A connection dropped mid-response surfaces from `post` as ChunkedEncodingError; it's
    # transient, so the request is reissued rather than failing the import.
    sess = MagicMock()
    sess.post.side_effect = [
        ChunkedEncodingError("Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"),
        _ok_page(),
    ]

    batches = list(
        _make_paginated_shopify_request(
            "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS], MagicMock()
        )
    )

    assert batches == [[{"id": "1"}]]
    assert sess.post.call_count == 2


@pytest.mark.parametrize(
    "transient_error",
    [
        # The observed failure: a 504 from the egress proxy tunnel surfaces as ProxyError.
        requests.exceptions.ProxyError("Tunnel connection failed: 504 Gateway timeout"),
        requests.exceptions.ConnectionError("Connection reset by peer"),
        requests.exceptions.ReadTimeout("Read timed out"),
    ],
)
@patch("tenacity.nap.time.sleep")
def test_request_retries_transient_connection_error_then_succeeds(_mock_sleep, transient_error):
    # Transient network errors escaping `post` (proxy hiccup, reset, timeout) are reissued
    # rather than failing the import.
    sess = MagicMock()
    sess.post.side_effect = [transient_error, _ok_page()]

    batches = list(
        _make_paginated_shopify_request(
            "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS], MagicMock()
        )
    )

    assert batches == [[{"id": "1"}]]
    assert sess.post.call_count == 2


@patch("tenacity.nap.time.sleep")
def test_request_reraises_retryable_after_persistent_connection_broken(_mock_sleep):
    sess = MagicMock()
    sess.post.side_effect = ChunkedEncodingError("Connection broken: InvalidChunkLength(got length b'', 0 bytes read)")

    with pytest.raises(ShopifyRetryableError):
        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS], MagicMock()
            )
        )

    assert sess.post.call_count == 5


@patch("tenacity.nap.time.sleep")
def test_request_reraises_after_persistent_connection_error(_mock_sleep):
    sess = MagicMock()
    sess.post.side_effect = requests.exceptions.ProxyError("Tunnel connection failed: 504 Gateway timeout")

    with pytest.raises(requests.exceptions.ProxyError):
        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS], MagicMock()
            )
        )

    assert sess.post.call_count == 5
