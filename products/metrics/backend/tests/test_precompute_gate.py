from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from products.metrics.backend.precompute.gate import precompute_enabled


class TestPrecomputeEnabled(BaseTest):
    @parameterized.expand(
        [
            ("us_project_2_with_the_flag", "US", 2, True, True),
            ("us_project_2_without_the_flag", "US", 2, False, False),
            ("another_us_project_with_the_flag", "US", 3, True, False),
            ("eu_project_2_with_the_flag", "EU", 2, True, False),
            ("self_hosted_with_the_flag", None, 3, True, True),
        ]
    )
    def test_needs_dashboard_v2_and_on_cloud_the_allowlist(
        self, _name: str, region: str | None, team_id: int, flag_on: bool, expected: bool
    ):
        self.team.pk = team_id
        with (
            override_settings(CLOUD_DEPLOYMENT=region),
            patch("products.metrics.backend.precompute.gate.posthog_feature_flag_enabled", return_value=flag_on),
        ):
            assert precompute_enabled(self.team) is expected
