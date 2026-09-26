from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.facade.flags import is_flag_evaluations_table_enabled
from products.feature_flags.backend.models import TeamFeatureFlagsConfig
from products.feature_flags.backend.models.team_feature_flags_config import (
    MAX_FEATURE_FLAGS_OVERRIDE_CEILING,
    FlagEvaluationsMode,
)

SIBLING_WITHOUT_A_ROW = "without_a_row"


class TestTeamFeatureFlagsConfig(BaseTest):
    def test_new_team_config_defaults_to_disabled(self):
        team = Team.objects.create(organization=self.organization, name="New Team")

        config = TeamFeatureFlagsConfig.objects.get(team=team)
        self.assertFalse(config.minimal_flag_called_events)
        self.assertEqual(config.property_matching_version, 1)

    def test_lazily_created_config_defaults_to_disabled(self):
        # A team without a row models a legacy team predating this extension. The sibling on mode 1
        # makes this fail if the lazy create copies sibling modes, which would change the mode that
        # readers already reported for the missing row.
        sibling = Team.objects.create(organization=self.organization, name="Sibling")
        TeamFeatureFlagsConfig.objects.filter(team=sibling).update(
            flag_evaluations_mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        self.assertFalse(config.minimal_flag_called_events)
        self.assertEqual(config.property_matching_version, 1)
        self.assertEqual(config.flag_evaluations_mode, FlagEvaluationsMode.EVENTS)

    @parameterized.expand(
        [
            ("first_team_takes_the_setting_at_events", (), 0, FlagEvaluationsMode.EVENTS),
            ("first_team_takes_the_setting_at_read", (), 1, FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("a_sibling_mode_wins_over_the_setting", (1,), 0, FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("a_new_setting_does_not_move_an_existing_organization", (0,), 1, FlagEvaluationsMode.EVENTS),
            ("a_sibling_without_a_row_counts_as_events", (SIBLING_WITHOUT_A_ROW,), 1, FlagEvaluationsMode.EVENTS),
            (
                "the_highest_sibling_mode_wins",
                (FlagEvaluationsMode.EVENTS, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY),
                0,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            ),
            ("an_invalid_setting_falls_back_to_events", (), 7, FlagEvaluationsMode.EVENTS),
        ]
    )
    def test_new_team_flag_evaluations_mode(self, _name, sibling_modes, new_org_mode, expected_mode):
        organization = Organization.objects.create(name="New organization")
        for sibling_mode in sibling_modes:
            sibling = Team.objects.create(organization=organization, name="Sibling")
            sibling_config = TeamFeatureFlagsConfig.objects.filter(team=sibling)
            if sibling_mode == SIBLING_WITHOUT_A_ROW:
                sibling_config.delete()
            else:
                sibling_config.update(flag_evaluations_mode=sibling_mode)

        with self.settings(FLAG_EVALUATIONS_NEW_ORG_MODE=new_org_mode):
            team = Team.objects.create(organization=organization, name="New team")

        self.assertEqual(TeamFeatureFlagsConfig.objects.get(team=team).flag_evaluations_mode, expected_mode)

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


class TestFlagEvaluationsTableGate(BaseTest):
    @parameterized.expand(
        [
            ("events_without_the_flag", FlagEvaluationsMode.EVENTS, False, False),
            ("events_with_the_flag", FlagEvaluationsMode.EVENTS, True, True),
            ("read_flag_evaluations_without_the_flag", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False, True),
            ("flag_evaluations_only_without_the_flag", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False, True),
            ("no_config_row_without_the_flag", None, False, False),
        ]
    )
    def test_table_is_enabled_by_the_mode_or_the_flag(self, _name, mode, flag_enabled, expected):
        config = TeamFeatureFlagsConfig.objects.filter(team=self.team)
        if mode is None:
            config.delete()
        else:
            config.update(flag_evaluations_mode=mode)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            patch("products.feature_flags.backend.facade.flags.feature_enabled_or_false", return_value=flag_enabled),
        ):
            self.assertEqual(is_flag_evaluations_table_enabled(self.team), expected)
