from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit, hog_flow_sends_email

TIER_BATCH_CAPS = [100, 1000, 3000, 10000, 30000, 100000, 300000, 1000000]


class TestGetHogflowBatchTriggerLimit(TestCase):
    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={2, 99},
    )
    def test_returns_default_for_unlisted_team(self):
        assert get_hogflow_batch_trigger_limit(1) == 5000
        assert get_hogflow_batch_trigger_limit(7) == 5000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={2, 99},
    )
    def test_returns_elevated_for_listed_team(self):
        assert get_hogflow_batch_trigger_limit(2) == 50000
        assert get_hogflow_batch_trigger_limit(99) == 50000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS=set(),
    )
    def test_returns_default_when_elevated_set_is_empty(self):
        assert get_hogflow_batch_trigger_limit(2) == 5000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=123,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=456,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={42},
    )
    def test_returns_currently_configured_values(self):
        # Doesn't snapshot 5000/50000 — picks up whatever the settings are at call time, so a
        # production tweak via env var is reflected immediately.
        assert get_hogflow_batch_trigger_limit(42) == 456
        assert get_hogflow_batch_trigger_limit(1) == 123


@override_settings(
    HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
    HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
    HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS=set(),
    WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS=TIER_BATCH_CAPS,
)
class TestTieredHogflowBatchTriggerLimit(BaseTest):
    @parameterized.expand([(tier, cap) for tier, cap in enumerate(TIER_BATCH_CAPS)])
    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_enforced_limit_follows_the_teams_tier(self, tier: int, expected_cap: int) -> None:
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": tier})
        assert get_hogflow_batch_trigger_limit(self.team.id) == expected_cap

    @parameterized.expand([("off",), ("shadow",)])
    def test_limit_stays_flat_until_the_mode_is_enforce(self, mode: str) -> None:
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 0})
        with override_settings(WORKFLOWS_EMAIL_TIER_MODE=mode):
            assert get_hogflow_batch_trigger_limit(self.team.id) == 5000

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_allowlisted_team_keeps_the_elevated_limit_regardless_of_tier(self) -> None:
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 0})
        with override_settings(HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={self.team.id}):
            assert get_hogflow_batch_trigger_limit(self.team.id) == 50000

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_database_error_during_resolution_fails_open(self) -> None:
        # A database blip on the send path returns the flat limit instead of raising.
        with patch(
            "products.workflows.backend.utils.email_sending_tiers.TeamWorkflowsConfig.objects.filter",
            side_effect=Exception("db down"),
        ):
            assert get_hogflow_batch_trigger_limit(self.team.id) == 5000

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_a_workflow_without_an_email_step_keeps_the_flat_limit(self) -> None:
        # The tiers protect SES reputation, so an SMS or push batch must not inherit the email cap.
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 0})
        assert get_hogflow_batch_trigger_limit(self.team.id, sends_email=False) == 5000
        assert get_hogflow_batch_trigger_limit(self.team.id, sends_email=True) == TIER_BATCH_CAPS[0]

    @parameterized.expand(
        [
            ("an email step", [{"type": "function_email"}], True),
            (
                "the email template on a generic function step",
                [{"type": "function", "config": {"template_id": "template-email"}}],
                True,
            ),
            (
                "the email template on a mislabeled sms step",
                [{"type": "function_sms", "config": {"template_id": "template-email"}}],
                True,
            ),
            (
                "a webhook template on a generic function step",
                [{"type": "function", "config": {"template_id": "template-webhook"}}],
                False,
            ),
            ("only sms and delay steps", [{"type": "function_sms"}, {"type": "delay"}], False),
            ("a non-list actions value", None, False),
        ]
    )
    def test_email_step_detection(self, _name: str, actions: object, expected: bool) -> None:
        # The serializer accepts the email template on a generic function step and the worker
        # executes it, so the detector must not key on the declared type alone.
        assert hog_flow_sends_email(actions) is expected

    @parameterized.expand(
        [
            ("no rate limit", None, True, TIER_BATCH_CAPS[2]),
            ("the fastest hourly rate that qualifies", {"count": 62, "period": "hour"}, True, 62 * 24 * 7),
            ("an hourly rate over half the daily cap", {"count": 63, "period": "hour"}, True, TIER_BATCH_CAPS[2]),
            ("a per-minute rate", {"count": 1, "period": "minute"}, True, 1 * 24 * 60 * 7),
            ("a rate too slow to beat the tier cap", {"count": 1, "period": "hour"}, True, TIER_BATCH_CAPS[2]),
            ("an unknown period", {"count": 10, "period": "day"}, True, TIER_BATCH_CAPS[2]),
            ("a workflow without an email step", {"count": 62, "period": "hour"}, False, 5000),
        ]
    )
    @override_settings(
        WORKFLOWS_EMAIL_TIER_MODE="enforce",
        WORKFLOWS_EMAIL_TIER_DAILY_CAPS=TIER_BATCH_CAPS,
        WORKFLOWS_RATE_LIMITED_BATCH_MAX_DAILY_SHARE=0.5,
        WORKFLOWS_RATE_LIMITED_BATCH_MAX_DAYS=7,
    )
    def test_a_slow_enough_rate_limit_raises_the_email_limit(
        self, _name: str, email_rate_limit: dict | None, sends_email: bool, expected: int
    ) -> None:
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 2})
        assert (
            get_hogflow_batch_trigger_limit(self.team.id, sends_email=sends_email, email_rate_limit=email_rate_limit)
            == expected
        )

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_team_without_a_config_row_is_treated_as_tier_zero(self) -> None:
        # A brand-new project has no workflows config row yet, and it must land on the lowest tier
        # rather than on the flat ceiling.
        team = Team.objects.create(organization=self.organization, name="no config")
        TeamWorkflowsConfig.objects.filter(team=team).delete()
        assert get_hogflow_batch_trigger_limit(team.id) == TIER_BATCH_CAPS[0]
