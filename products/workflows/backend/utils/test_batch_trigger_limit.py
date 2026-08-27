from posthog.test.base import BaseTest

from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit

TIER_BATCH_CAPS = [1000, 3000, 10000, 30000, 100000, 300000, 1000000]


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

    @override_settings(
        WORKFLOWS_EMAIL_TIER_MODE="enforce",
        WORKFLOWS_EMAIL_TIER_ENFORCE_TEAMS_CREATED_AFTER="2099-01-01",
    )
    def test_team_created_before_the_cutoff_keeps_the_flat_limit(self) -> None:
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 0})
        assert get_hogflow_batch_trigger_limit(self.team.id) == 5000

    @override_settings(WORKFLOWS_EMAIL_TIER_MODE="enforce")
    def test_team_without_a_config_row_is_treated_as_tier_zero(self) -> None:
        # A brand-new project has no workflows config row yet, and it must land on the lowest tier
        # rather than on the flat ceiling.
        team = Team.objects.create(organization=self.organization, name="no config")
        TeamWorkflowsConfig.objects.filter(team=team).delete()
        assert get_hogflow_batch_trigger_limit(team.id) == TIER_BATCH_CAPS[0]
