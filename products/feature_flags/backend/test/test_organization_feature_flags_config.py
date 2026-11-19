from posthog.test.base import BaseTest

from parameterized import param, parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import (
    flag_calls_only_in_flag_evaluations,
    is_flag_evaluations_table_enabled,
    reads_flag_calls_from_flag_evaluations,
)
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
            param("self_hosted_events", FlagEvaluationsMode.EVENTS, expected=False),
            param("self_hosted_read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, expected=True),
            param("self_hosted_flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, expected=True),
            param("self_hosted_no_config_row", None, expected=False),
            param(
                "self_hosted_read_flag_evaluations_while_reads_are_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                expected=True,
                reads_forced_to_events=True,
            ),
            param("cloud_events", FlagEvaluationsMode.EVENTS, expected=True, cloud=True),
            param("cloud_no_config_row", None, expected=True, cloud=True),
        ]
    )
    def test_table_is_enabled_on_cloud_or_by_the_organization_mode(
        self,
        _name: str,
        mode: FlagEvaluationsMode | None,
        *,
        expected: bool,
        cloud: bool = False,
        reads_forced_to_events: bool = False,
    ) -> None:
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


class TestFlagCallReadersFollowTheEventsTable(BaseTest):
    @parameterized.expand(
        [
            param("legacy_events", FlagEvaluationsMode.EVENTS, reads=False, only=False),
            param("legacy_read", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, reads=True, only=False),
            param(
                "legacy_read_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=False,
                only=False,
                reads_forced_to_events=True,
            ),
            param("legacy_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, reads=True, only=True),
            param("native_events", FlagEvaluationsMode.EVENTS, reads=True, only=True, native=True),
            param("native_read", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, reads=True, only=True, native=True),
            param(
                "native_read_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=True,
                only=True,
                native=True,
                reads_forced_to_events=True,
            ),
            param(
                "native_query_on_a_legacy_instance",
                FlagEvaluationsMode.EVENTS,
                reads=True,
                only=False,
                query_reads_native=True,
            ),
            param(
                "legacy_query_on_a_native_instance_forced_to_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                reads=False,
                only=True,
                native=True,
                query_reads_native=False,
                reads_forced_to_events=True,
            ),
            param(
                "native_events_without_the_table",
                FlagEvaluationsMode.EVENTS,
                reads=False,
                only=False,
                native=True,
                cloud=False,
            ),
        ]
    )
    def test_flag_call_readers_pick_flag_evaluations_by_mode_and_events_table(
        self,
        _name: str,
        mode: FlagEvaluationsMode,
        *,
        reads: bool,
        only: bool,
        native: bool = False,
        query_reads_native: bool | None = None,
        cloud: bool = True,
        reads_forced_to_events: bool = False,
    ) -> None:
        modifiers = HogQLQueryModifiers(useNewEventsSchema=query_reads_native)
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(flag_evaluations_mode=mode)

        with (
            self.settings(DEBUG=False, E2E_TESTING=False, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native),
            self.is_cloud(cloud),
            override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", reads_forced_to_events),
        ):
            self.assertEqual(reads_flag_calls_from_flag_evaluations(self.team, modifiers), reads)
            self.assertEqual(flag_calls_only_in_flag_evaluations(self.team), only)
