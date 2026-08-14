from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.models import TeamFeatureFlagsConfig
from products.feature_flags.backend.models.team_feature_flags_config import MAX_FEATURE_FLAGS_OVERRIDE_CEILING


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

    @parameterized.expand(
        [
            ("above_the_ceiling", MAX_FEATURE_FLAGS_OVERRIDE_CEILING + 1),
            ("zero", 0),
        ]
    )
    def test_database_rejects_an_out_of_range_override(self, _name, value):
        # The staff serializer's bounds are the only other guard, and .save() runs neither the
        # serializer nor the field validators. Without the CHECK constraint a management command
        # writing this field directly could grant an unbounded limit, which is the memory risk the
        # ceiling exists to prevent.
        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        config.max_feature_flags_override = value

        with self.assertRaises(IntegrityError), transaction.atomic():
            config.save(update_fields=["max_feature_flags_override"])

    @parameterized.expand(
        [
            ("the_ceiling_itself", MAX_FEATURE_FLAGS_OVERRIDE_CEILING),
            ("one", 1),
            ("no_override", None),
        ]
    )
    def test_database_accepts_an_in_range_override(self, _name, value):
        # Pins both ends as inclusive and keeps null writable, so a constraint tightened by one
        # would fail here rather than in production.
        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        config.max_feature_flags_override = value
        config.save(update_fields=["max_feature_flags_override"])

        config.refresh_from_db()
        self.assertEqual(config.max_feature_flags_override, value)
