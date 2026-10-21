from datetime import datetime

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
    can_read_flag_history=True, can_query_events=True, denied_event_properties=frozenset()
)
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
                "calls_kept_out_of_events_with_the_sync_reading_flag_evaluations",
                None,
                False,
                True,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "flag_evaluations",
                Status.FINDING,
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
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
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
        experiment = Experiment.objects.create(team=self.team, name="draft", feature_flag=flag)

        with override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE=sync_source):
            health = get_experiment_health(team_id=self.team.id, experiment_id=experiment.id, reader_access=FULL_ACCESS)

        check = next(check for check in health.checks if check.key == ExperimentHealthCheckKey.NEW_FLAG_NO_TRAFFIC)
        self.assertEqual(check.status, expected)
