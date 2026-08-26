from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    DEFAULT_RETRY,
    BoundedRetry,
)


def _response_with_retry_after(value: str) -> MagicMock:
    response = MagicMock()
    response.headers = {"Retry-After": value}
    return response


class TestBoundedRetry:
    @parameterized.expand(
        [
            # An absurd Retry-After used to reach time.sleep uncapped and raise
            # OverflowError ("timestamp too large to convert to C PyTime_t").
            ("huge_integer", "100000000000"),
            ("above_cap", "600"),
        ]
    )
    def test_retry_after_is_capped(self, _name: str, header_value: str) -> None:
        retry = BoundedRetry(total=3)
        assert retry.get_retry_after(_response_with_retry_after(header_value)) == BoundedRetry.DEFAULT_BACKOFF_MAX

    def test_retry_after_below_cap_is_untouched(self) -> None:
        retry = BoundedRetry(total=3)
        assert retry.get_retry_after(_response_with_retry_after("5")) == 5

    def test_no_retry_after_header_returns_none(self) -> None:
        retry = BoundedRetry(total=3)
        response = MagicMock()
        response.headers = {}
        assert retry.get_retry_after(response) is None

    def test_default_retry_is_bounded_and_survives_clone(self) -> None:
        # urllib3 rebuilds the Retry via `new()` on each attempt; the cap must survive.
        assert isinstance(DEFAULT_RETRY, BoundedRetry)
        assert isinstance(DEFAULT_RETRY.new(), BoundedRetry)

    @parameterized.expand(
        [
            ("rate_limited", 429, True),
            ("bad_gateway", 502, True),
            ("gateway_timeout", 504, True),
            # Cloudflare 52x family — a slow or unreachable origin behind Cloudflare (e.g. Cal.com).
            ("cloudflare_unknown", 520, True),
            ("cloudflare_web_server_down", 521, True),
            ("cloudflare_connection_timeout", 522, True),
            ("cloudflare_origin_unreachable", 523, True),
            ("cloudflare_timeout", 524, True),
            ("cloudflare_dns", 530, True),
            # Not transient: a real 4xx or an origin that answered.
            ("not_implemented", 501, False),
            ("bad_request", 400, False),
            ("ok", 200, False),
        ]
    )
    def test_default_retry_covers_transient_statuses(self, _name: str, status: int, retried: bool) -> None:
        assert DEFAULT_RETRY.is_retry("GET", status) is retried

    def test_default_retry_skips_non_idempotent_methods(self) -> None:
        # A POST is not safe to replay, so even a transient timeout must not be retried.
        assert DEFAULT_RETRY.is_retry("POST", 524) is False
