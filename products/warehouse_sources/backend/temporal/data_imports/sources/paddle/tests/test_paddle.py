from typing import cast

from requests.adapters import HTTPAdapter

from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    _get_paddle_session,
)


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
