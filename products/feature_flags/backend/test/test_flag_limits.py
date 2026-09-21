from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.flag_limits import get_max_feature_flags_for_team
from products.feature_flags.backend.models.team_feature_flags_config import TeamFeatureFlagsConfig


class TestGetMaxFeatureFlagsForTeam(BaseTest):
    @parameterized.expand(
        [
            # 777 rather than the production default of 2000, so a resolver that returned the
            # literal instead of reading the setting would fail these two rows.
            ("no_config_row", None, False, 777),
            ("null_override", None, True, 777),
            ("small_override_below_global", 1, True, 1),
            ("override_above_global", 5000, True, 5000),
        ]
    )
    def test_resolves_effective_limit(self, _name, override, has_row, expected_limit):
        if has_row:
            config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
            config.max_feature_flags_override = override
            config.save(update_fields=["max_feature_flags_override"])
        else:
            # Models a legacy team that predates this field, or any lookup that hasn't
            # lazily created the row yet: get_max_feature_flags_for_team must fall back to
            # the global default rather than raising on the missing row.
            TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=777):
            self.assertEqual(get_max_feature_flags_for_team(self.team.id), expected_limit)

    def test_environment_team_resolves_the_override_from_its_project_root(self):
        # Flags are project-scoped, so an environment team is charged its project's whole flag
        # count. Reading the override off the environment team instead of the root would leave a
        # granted team on the global default for every create routed through that environment.
        root_config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        root_config.max_feature_flags_override = 5000
        root_config.save(update_fields=["max_feature_flags_override"])
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Environment"
        )

        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=777):
            self.assertEqual(get_max_feature_flags_for_team(environment.id), 5000)
