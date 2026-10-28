from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.reviewer.constants import CONTROL_ARM_SET, SINGLE_AGENT_ARM_SETS
from products.review_hog.backend.reviewer.feature_flags import (
    DELTA_BAND_FLAG,
    SINGLE_AGENT_ARMS_FLAG,
    STANDARD_COORDINATOR_FLAG,
    ZERO_CHANGE_SKIP_FLAG,
    delta_reviews_low_risk_follow_ups,
    flash_pipeline_kill_switch_on,
    single_agent_arm_set,
    skips_zero_change_follow_ups,
    standard_coordinator_on,
)

_FEATURE_ENABLED = "products.review_hog.backend.reviewer.feature_flags.posthoganalytics.feature_enabled"
_GET_FEATURE_FLAG = "products.review_hog.backend.reviewer.feature_flags.posthoganalytics.get_feature_flag"


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


class TestPullRequestFlags(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{case}", check, flag, feature_enabled, expected)
            for name, check, flag in (
                ("coordinator", standard_coordinator_on, STANDARD_COORDINATOR_FLAG),
                ("zero_change_skip", skips_zero_change_follow_ups, ZERO_CHANGE_SKIP_FLAG),
                ("delta_band", delta_reviews_low_risk_follow_ups, DELTA_BAND_FLAG),
            )
            for case, feature_enabled, expected in (
                ("flag_on", MagicMock(return_value=True), True),
                ("flag_error", MagicMock(side_effect=RuntimeError("flag service down")), False),
                ("flag_unknown", MagicMock(return_value=None), False),
            )
        ]
    )
    def test_reads_its_flag_per_pull_request(
        self, _name: str, check, flag: str, feature_enabled: MagicMock, expected: bool
    ) -> None:
        with patch(_FEATURE_ENABLED, feature_enabled):
            assert check("posthog/posthog", 42) is expected
        assert feature_enabled.call_args.args[:2] == (flag, "posthog/posthog#42")

    @parameterized.expand(
        [
            ("variant_with_an_arm_set", MagicMock(return_value="trial"), "trial"),
            # A typo in a variant, or a flag set up as a plain rollout, must not reach the sandbox as a model.
            ("variant_without_an_arm_set", MagicMock(return_value="trail"), CONTROL_ARM_SET),
            ("boolean_flag", MagicMock(return_value=True), CONTROL_ARM_SET),
            ("flag_off", MagicMock(return_value=None), CONTROL_ARM_SET),
            ("flag_error", MagicMock(side_effect=RuntimeError("flag service down")), CONTROL_ARM_SET),
        ]
    )
    def test_arm_set_comes_from_the_variant_per_pull_request(
        self, _name: str, get_feature_flag: MagicMock, expected: str
    ) -> None:
        with (
            patch(_GET_FEATURE_FLAG, get_feature_flag),
            patch.dict(SINGLE_AGENT_ARM_SETS, {"trial": SINGLE_AGENT_ARM_SETS[CONTROL_ARM_SET]}),
        ):
            assert single_agent_arm_set("posthog/posthog", 42) == expected
        assert get_feature_flag.call_args.args[:2] == (SINGLE_AGENT_ARMS_FLAG, "posthog/posthog#42")
