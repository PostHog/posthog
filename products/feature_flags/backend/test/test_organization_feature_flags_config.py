from posthog.test.base import BaseTest

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
            ("self_hosted_events", FlagEvaluationsMode.EVENTS, False, False, False),
            ("self_hosted_read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False, False, True),
            ("self_hosted_flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False, False, True),
            ("self_hosted_no_config_row", None, False, False, False),
            (
                "self_hosted_read_flag_evaluations_while_reads_are_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                False,
                True,
                True,
            ),
            ("cloud_events", FlagEvaluationsMode.EVENTS, True, False, True),
            ("cloud_no_config_row", None, True, False, True),
            ("cloud_read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, True, False, True),
        ]
    )
    def test_table_is_enabled_on_cloud_or_by_the_organization_mode(
        self, _name, mode, cloud, reads_forced_to_events, expected
    ):
        config = OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization)
        if mode is None:
            config.delete()
        else:
            config.update(flag_evaluations_mode=mode)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False),
            self.is_cloud(cloud),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            self.assertEqual(is_flag_evaluations_table_enabled(self.team), expected)
