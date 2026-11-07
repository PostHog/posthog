import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.redis import TEST_clear_clients, get_client
from posthog.token_bucket import Budget, TEST_reset_scripts

from products.signals.backend.source_rate_limit import SourceRateWindow, source_rate_limit_exceeded

MODULE = "products.signals.backend.source_rate_limit"


class TestSourceRateLimitExceeded(SimpleTestCase):
    def setUp(self) -> None:
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)
        get_client().flushdb()

    def test_hourly_cap_applies_per_team_and_source(self) -> None:
        with (
            time_machine.travel("2026-01-01 00:00:00", tick=False),
            patch(f"{MODULE}.HOURLY_BUDGET", Budget(burst=2, per_hour=1)),
        ):
            assert source_rate_limit_exceeded(1, "error_tracking", "issue_created") is None
            assert source_rate_limit_exceeded(1, "error_tracking", "issue_created") is None
            assert source_rate_limit_exceeded(1, "error_tracking", "issue_created") == SourceRateWindow.HOUR

            assert source_rate_limit_exceeded(1, "error_tracking", "issue_reopened") is None
            assert source_rate_limit_exceeded(1, "github", "issue") is None
            assert source_rate_limit_exceeded(2, "error_tracking", "issue_created") is None

    def test_daily_drop_does_not_spend_an_hourly_token(self) -> None:
        with (
            time_machine.travel("2026-01-01 00:00:00", tick=False) as frozen,
            patch(f"{MODULE}.HOURLY_BUDGET", Budget(burst=2, per_hour=1)),
            patch(f"{MODULE}.DAILY_BUDGET", Budget(burst=1, per_hour=3600)),
        ):
            assert source_rate_limit_exceeded(1, "github", "issue") is None
            assert source_rate_limit_exceeded(1, "github", "issue") == SourceRateWindow.DAY

            frozen.shift(1)
            assert source_rate_limit_exceeded(1, "github", "issue") is None

    def test_redis_outage_lets_the_signal_through(self) -> None:
        broken = MagicMock()
        broken.register_script.return_value.side_effect = RedisConnectionError("down")
        TEST_reset_scripts()
        with patch("posthog.token_bucket.get_client", return_value=broken):
            assert source_rate_limit_exceeded(1, "github", "issue") is None
