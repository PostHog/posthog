import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.redis import TEST_clear_clients, get_client
from posthog.token_bucket import TEST_reset_scripts

from products.signals.backend.source_rate_limit import (
    DEFAULT_CAPS,
    SourceCap,
    SourceCaps,
    SourceRateWindow,
    parse_caps,
    source_rate_limit_exceeded,
)

MODULE = "products.signals.backend.source_rate_limit"


def _caps(per_hour: int, per_day: int, *, enabled: bool = True) -> SourceCaps:
    return SourceCaps(enabled=enabled, default=SourceCap(per_hour=per_hour, per_day=per_day), sources={}, projects={})


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
            patch(f"{MODULE}.current_caps", return_value=_caps(per_hour=2, per_day=100)),
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
            patch(f"{MODULE}.current_caps", return_value=_caps(per_hour=2, per_day=1)),
        ):
            assert source_rate_limit_exceeded(1, "github", "issue") is None
            assert source_rate_limit_exceeded(1, "github", "issue") == SourceRateWindow.DAY

            frozen.shift(86400)
            assert source_rate_limit_exceeded(1, "github", "issue") is None

    def test_redis_outage_lets_the_signal_through(self) -> None:
        broken = MagicMock()
        broken.register_script.return_value.side_effect = RedisConnectionError("down")
        TEST_reset_scripts()
        with (
            patch("posthog.token_bucket.get_client", return_value=broken),
            patch(f"{MODULE}.current_caps", return_value=DEFAULT_CAPS),
        ):
            assert source_rate_limit_exceeded(1, "github", "issue") is None

    def test_disabled_caps_charge_nothing(self) -> None:
        with patch(f"{MODULE}.current_caps", return_value=_caps(per_hour=1, per_day=1, enabled=False)):
            for _ in range(3):
                assert source_rate_limit_exceeded(1, "github", "issue") is None


PROJECT_7 = {"default": {"per_hour": 9, "per_day": 9}, "sources": {"linear": {"per_hour": 8, "per_day": 8}}}
PAYLOAD = {
    "default": {"per_hour": 300, "per_day": 900},
    "sources": {
        "error_tracking:issue_created": {"per_hour": 50, "per_day": 100},
        "github": {"per_hour": "lots", "per_day": 10},
    },
    "projects": {
        "US:7": PROJECT_7,
    },
}


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSourceCaps(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_payload_uses_defaults", None, 1, "linear", "issue", DEFAULT_CAPS.sources["linear"]),
            (
                "type_beats_product_and_default",
                PAYLOAD,
                1,
                "error_tracking",
                "issue_created",
                SourceCap(per_hour=50, per_day=100),
            ),
            (
                "payload_default_for_unlisted_source",
                PAYLOAD,
                1,
                "conversations",
                "ticket",
                SourceCap(per_hour=300, per_day=900),
            ),
            ("invalid_entry_keeps_code_default", PAYLOAD, 1, "github", "issue", DEFAULT_CAPS.sources["github"]),
            ("project_source_override", PAYLOAD, 7, "linear", "issue", SourceCap(per_hour=8, per_day=8)),
            (
                "project_default_beats_global_source",
                PAYLOAD,
                7,
                "replay_vision",
                "scanner_finding",
                SourceCap(per_hour=9, per_day=9),
            ),
            (
                "same_team_id_other_region_ignored",
                {"projects": {"EU:7": PROJECT_7}},
                7,
                "linear",
                "issue",
                DEFAULT_CAPS.sources["linear"],
            ),
        ]
    )
    def test_resolve(self, _name, payload, team_id, source_product, source_type, expected) -> None:
        assert parse_caps(payload).resolve(team_id, source_product, source_type) == expected

    def test_enabled_false_turns_the_gate_off(self) -> None:
        assert parse_caps({"enabled": False}).enabled is False
        assert parse_caps({}).enabled is True
