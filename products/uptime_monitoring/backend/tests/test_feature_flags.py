from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from products.uptime_monitoring.backend.facade.api import is_enabled


class TestUptimeMonitoringFeatureFlag(TestCase):
    @parameterized.expand(
        [
            ("flag_on", {"return_value": True}, True),
            ("flag_off", {"return_value": False}, False),
            ("flag_missing", {"return_value": None}, False),
            ("flag_service_raises", {"side_effect": RuntimeError("flags unreachable")}, False),
        ]
    )
    def test_gate_reflects_flag_state(self, _name: str, mock_kwargs: dict, expected: bool) -> None:
        with patch("posthoganalytics.feature_enabled", **mock_kwargs):
            assert is_enabled(team_id=1) is expected
