from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.reviewer.feature_flags import flash_pipeline_kill_switch_on, standard_coordinator_on

_FEATURE_ENABLED = "products.review_hog.backend.reviewer.feature_flags.posthoganalytics.feature_enabled"


class TestFlashPipelineKillSwitch(BaseTest):
    @parameterized.expand(
        [
            ("flag_on", MagicMock(return_value=True), True),
            # A flag service failure must keep Flash on its code default, not fail the fetch activity.
            ("flag_error", MagicMock(side_effect=RuntimeError("flag service down")), False),
            ("flag_unknown", MagicMock(return_value=None), False),
        ]
    )
    def test_kill_switch_reads_the_organization_flag(
        self, _name: str, feature_enabled: MagicMock, expected: bool
    ) -> None:
        with patch(_FEATURE_ENABLED, feature_enabled):
            assert flash_pipeline_kill_switch_on(self.team.id) is expected


class TestStandardCoordinator(SimpleTestCase):
    @parameterized.expand(
        [
            ("flag_on", MagicMock(return_value=True), True),
            ("flag_error", MagicMock(side_effect=RuntimeError("flag service down")), False),
            ("flag_unknown", MagicMock(return_value=None), False),
        ]
    )
    def test_coordinator_reads_the_flag_per_pull_request(
        self, _name: str, feature_enabled: MagicMock, expected: bool
    ) -> None:
        with patch(_FEATURE_ENABLED, feature_enabled):
            assert standard_coordinator_on("posthog/posthog", 42) is expected
        assert feature_enabled.call_args.args[1] == "posthog/posthog#42"
