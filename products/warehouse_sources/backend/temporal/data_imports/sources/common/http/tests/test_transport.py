import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from urllib3.exceptions import MaxRetryError, ReadTimeoutError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import transport
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    DEFAULT_RETRY,
    BoundedRetry,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point


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

    @parameterized.expand(
        [
            ("status", {"response": MagicMock(status=503, **{"get_redirect_location.return_value": False})}),
            ("read_error", {"error": ReadTimeoutError(MagicMock(), "/items", "read timed out")}),
        ]
    )
    @override_settings(DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS=600.0)
    def test_retries_of_one_request_stop_at_the_budget(self, _name: str, failure: dict) -> None:
        now = 0.0
        retry = BoundedRetry(total=10, status_forcelist=(503,), raise_on_status=False)
        with patch.object(transport, "_monotonic", lambda: now):
            retry = retry.increment("GET", "/items", **failure)
            now = 599.0
            retry = retry.increment("GET", "/items", **failure)
            now = 600.0
            with pytest.raises(MaxRetryError):
                retry.increment("GET", "/items", **failure)

    @parameterized.expand([("worker_running", False, 60.0), ("worker_shutting_down", True, 0.0)])
    def test_a_retry_wait_ends_when_the_worker_shuts_down(
        self, _name: str, shutting_down: bool, expected_sleep: float
    ) -> None:
        safe_point = MagicMock()
        with (
            patch("time.sleep") as sleep,
            activate_safe_point(safe_point, covers_framework_checkpoints=True, is_shutting_down=lambda: shutting_down),
        ):
            BoundedRetry(total=3).sleep(_response_with_retry_after("60"))

        assert sum(call.args[0] for call in sleep.call_args_list) == expected_sleep
        # The adapter cannot know where the source is, so it never reaches a safe point by itself.
        safe_point.assert_not_called()
