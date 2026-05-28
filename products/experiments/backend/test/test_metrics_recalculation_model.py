from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Status = ExperimentMetricsRecalculation.Status


class TestExperimentMetricsRecalculationModel(BaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

    def _experiment(self, flag_key: str = "recalc-model-flag") -> Experiment:
        return Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag(flag_key), name="exp"
        )

    def test_defaults(self):
        recalc = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=self._experiment())
        assert recalc.status == Status.PENDING
        assert recalc.total_metrics == 0
        assert recalc.completed_metrics == 0
        assert recalc.failed_metrics == 0
        assert recalc.errors == {}
        assert recalc.metric_uuids == []
        assert recalc.trigger == ExperimentMetricsRecalculation.Trigger.MANUAL
        assert recalc.started_at is None
        assert recalc.completed_at is None
        assert recalc.query_to is None

    @parameterized.expand(
        [
            (Status.PENDING, True),
            (Status.IN_PROGRESS, True),
            (Status.COMPLETED, False),
            (Status.FAILED, False),
        ]
    )
    def test_active_recalculation_uniqueness(self, existing_status: str, should_block: bool):
        exp = self._experiment(flag_key=f"recalc-uniq-{existing_status}")
        ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=existing_status)

        def _create_second() -> None:
            ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=Status.PENDING)

        if should_block:
            with self.assertRaises(IntegrityError), transaction.atomic():
                _create_second()
        else:
            _create_second()
            assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 2
