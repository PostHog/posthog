from posthog.test.base import BaseTest

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.models import TeamFeatureFlagsConfig


class TestTeamFeatureFlagsConfig(BaseTest):
    def test_new_team_config_defaults_to_disabled(self):
        team = Team.objects.create(organization=self.organization, name="New Team")

        config = TeamFeatureFlagsConfig.objects.get(team=team)
        self.assertFalse(config.minimal_flag_called_events)

    def test_lazily_created_config_defaults_to_disabled(self):
        # A team without a row models a legacy team predating this extension.
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        self.assertFalse(config.minimal_flag_called_events)
