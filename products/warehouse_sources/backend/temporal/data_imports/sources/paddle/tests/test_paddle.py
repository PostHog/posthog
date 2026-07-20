from typing import cast

import pytest

from requests.adapters import HTTPAdapter

from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    _get_paddle_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import PaddleSource


class TestPaddleSession:
    def test_session_retries_rate_limits(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # A transient 429 must back off and retry rather than failing the whole sync.
        assert retry.total is not None and retry.total > 0
        assert retry.is_retry("GET", 429) is True
        assert retry.respect_retry_after_header is True
        # Persistent failures still surface via response.raise_for_status(), not MaxRetryError.
        assert retry.raise_on_status is False

    def test_auth_failures_are_not_retried(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # 401/403/400 are credential/config problems handled by get_non_retryable_errors;
        # retrying them would only delay surfacing the error to the user.
        assert retry.is_retry("GET", 401) is False
        assert retry.is_retry("GET", 403) is False
        assert retry.is_retry("GET", 400) is False


class TestPaddleNonRetryableErrors:
    @pytest.mark.parametrize(
        "observed_error",
        [
            # A 404 on a list endpoint we know exists means the resource isn't reachable for this
            # account (Billing not enabled, or a wrong-environment key) — retrying can't fix it.
            "404 Client Error: Not Found for url: https://api.paddle.com/subscriptions?per_page=200&order_by=id%5BASC%5D",
            "400 Client Error: Bad Request for url: https://api.paddle.com/transactions?per_page=200",
            "401 Client Error: Unauthorized for url: https://api.paddle.com/customers",
            "403 Client Error: Forbidden for url: https://api.paddle.com/products",
        ],
    )
    def test_non_retryable_errors_match_client_failures(self, observed_error):
        non_retryable_errors = PaddleSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient/infra errors must stay retryable.
            "HTTPSConnectionPool(host='api.paddle.com', port=443): Read timed out.",
            "500 Server Error: Internal Server Error for url: https://api.paddle.com/subscriptions",
            "Connection reset by peer",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = PaddleSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
