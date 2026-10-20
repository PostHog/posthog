from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import is_flag_evaluations_table_enabled
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig


class TestOrganizationFeatureFlagsConfig(BaseTest):
    @parameterized.expand(
        [
            ("events", 0, FlagEvaluationsMode.EVENTS),
            ("read_flag_evaluations", 1, FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("an_invalid_setting_falls_back_to_events", 7, FlagEvaluationsMode.EVENTS),
        ]
    )
    def test_a_new_organization_takes_the_new_org_mode(self, _name, new_org_mode, expected_mode):
        with self.settings(FLAG_EVALUATIONS_NEW_ORG_MODE=new_org_mode):
            organization = Organization.objects.create(name="New organization")

        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=organization).flag_evaluations_mode, expected_mode
        )

    def test_saving_an_existing_organization_keeps_its_mode(self):
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )

        with self.settings(FLAG_EVALUATIONS_NEW_ORG_MODE=FlagEvaluationsMode.EVENTS):
            self.organization.name = "Renamed"
            self.organization.save()

        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=self.organization).flag_evaluations_mode,
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )


class TestFlagEvaluationsTableGate(BaseTest):
    @parameterized.expand(
        [
            ("events_without_the_flag", FlagEvaluationsMode.EVENTS, False, False, False),
            ("events_with_the_flag", FlagEvaluationsMode.EVENTS, True, False, True),
            ("read_flag_evaluations_without_the_flag", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False, False, True),
            (
                "flag_evaluations_only_without_the_flag",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                False,
                False,
                True,
            ),
            ("no_config_row_without_the_flag", None, False, False, False),
            (
                "read_flag_evaluations_while_reads_are_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                False,
                True,
                True,
            ),
        ]
    )
    def test_table_is_enabled_by_the_organization_mode_or_the_flag(
        self, _name, mode, flag_enabled, reads_forced_to_events, expected
    ):
        config = OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization)
        if mode is None:
            config.delete()
        else:
            config.update(flag_evaluations_mode=mode)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            patch("products.feature_flags.backend.facade.flags.feature_enabled_or_false", return_value=flag_enabled),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            self.assertEqual(is_flag_evaluations_table_enabled(self.team), expected)
