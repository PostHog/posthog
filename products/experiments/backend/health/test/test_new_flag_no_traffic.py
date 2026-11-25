from datetime import datetime
from typing import Any

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

FULL_ACCESS = ExperimentHealthReaderAccess(
    can_read_flag_history=True,
    can_query_events=True,
    denied_event_properties=frozenset(),
    restricted_properties=frozenset(),
)
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=True,
    can_query_events=False,
    denied_event_properties=frozenset(),
    restricted_properties=frozenset(),
)
FLAG_PROPERTY_DENIED = ExperimentHealthReaderAccess(
    can_read_flag_history=True,
    can_query_events=True,
    denied_event_properties=frozenset({"$feature_flag"}),
    restricted_properties=frozenset(),
)
WAREHOUSE_NATIVE_EXPOSURE = {
    "exposure_config": {
        "kind": "ExperimentWarehouseNativeExposureConfig",
        "connection_id": "00000000-0000-0000-0000-000000000000",
        "query": "SELECT customer_id AS entity_id, variant, exposed_at AS timestamp FROM exposures",
        "unit": {"unit_type": "customer", "id_namespace": "billing_customer_id"},
    }
}
Status = ExperimentHealthCheckStatus


class TestNewFlagNoTraffic(BaseTest):
    @parameterized.expand(
        [
            ("called", timezone.now(), False, False, FlagEvaluationsMode.EVENTS, "events", Status.PASSED),
            ("never_called", None, False, True, FlagEvaluationsMode.EVENTS, "events", Status.FINDING),
            (
                "never_called_with_its_own_flag_active",
                None,
                True,
                False,
                FlagEvaluationsMode.EVENTS,
                "events",
                Status.FINDING,
            ),
            (
                "never_called_without_an_active_flag",
                None,
                False,
                False,
                FlagEvaluationsMode.EVENTS,
                "events",
                Status.NOT_CHECKED,
            ),
            (
                "calls_kept_out_of_events",
                None,
                False,
                True,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "events",
                Status.NOT_CHECKED,
            ),
            (
                "calls_kept_in_events_while_flag_evaluations_is_the_only_read",
                None,
                False,
                True,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "events",
                Status.FINDING,
                FULL_ACCESS,
                True,
            ),
            (
                "calls_kept_out_of_events_with_the_sync_reading_flag_evaluations",
                None,
                False,
                True,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "flag_evaluations",
                Status.FINDING,
            ),
            (
                "called_for_a_reader_who_cant_query_events",
                timezone.now(),
                False,
                False,
                FlagEvaluationsMode.EVENTS,
                "events",
                Status.NOT_CHECKED,
                NO_QUERIES,
            ),
            (
                "called_for_a_reader_denied_the_flag_property",
                timezone.now(),
                False,
                False,
                FlagEvaluationsMode.EVENTS,
                "events",
                Status.NOT_CHECKED,
                FLAG_PROPERTY_DENIED,
            ),
            (
                "never_called_while_the_warehouse_holds_the_exposures",
                None,
                False,
                True,
                FlagEvaluationsMode.EVENTS,
                "events",
                Status.NOT_APPLICABLE,
                FULL_ACCESS,
                False,
                WAREHOUSE_NATIVE_EXPOSURE,
            ),
        ]
    )
    def test_reads_the_flags_recorded_calls_on_a_draft(
        self,
        _name: str,
        last_called_at: datetime | None,
        flag_active: bool,
        another_active_flag: bool,
        mode: FlagEvaluationsMode,
        sync_source: str,
        expected: ExperimentHealthCheckStatus,
        reader_access: ExperimentHealthReaderAccess = FULL_ACCESS,
        keep_writing_flag_calls_to_events: bool = False,
        exposure_criteria: dict[str, Any] | None = None,
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization,
            defaults={
                "flag_evaluations_mode": mode,
                "keep_writing_flag_calls_to_events": keep_writing_flag_calls_to_events,
            },
        )
        if another_active_flag:
            FeatureFlag.objects.create(team=self.team, key="live-flag", created_by=self.user, active=True)
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="new-flag",
            created_by=self.user,
            active=flag_active,
            last_called_at=last_called_at,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team, name="draft", feature_flag=flag, exposure_criteria=exposure_criteria
        )

        with override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE=sync_source):
            health = get_experiment_health(
                team_id=self.team.id, experiment_id=experiment.id, reader_access=reader_access, user=self.user
            )

        check = next(check for check in health.checks if check.key == ExperimentHealthCheckKey.NEW_FLAG_NO_TRAFFIC)
        self.assertEqual(check.status, expected)
