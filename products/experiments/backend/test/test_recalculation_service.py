from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import get_latest_recalculation, get_run_results, request_recalculation
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


@pytest.mark.django_db(transaction=True)
class TestRecalculationService(BaseTest):
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

    def _launched_experiment(self, flag_key: str = "svc-flag") -> Experiment:
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(flag_key),
            name="exp",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        exp.metrics = [_mean_metric("m1")]
        exp.save()
        return exp

    def test_request_recalculation_creates_pending(self):
        exp = self._launched_experiment()
        result = request_recalculation(exp, self.user, "manual")
        assert result["status"] == "pending"
        assert result["is_existing"] is False
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    def test_request_recalculation_is_idempotent(self):
        exp = self._launched_experiment()
        first = request_recalculation(exp, self.user, "manual")
        second = request_recalculation(exp, self.user, "manual")
        assert second["is_existing"] is True
        assert second["id"] == first["id"]
        # Only one job row was created across both calls.
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    def test_request_recalculation_rejects_unlaunched(self):
        exp = Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag("unlaunched"), name="draft"
        )
        with pytest.raises(ValidationError):
            request_recalculation(exp, self.user, "manual")

    @parameterized.expand(
        [
            ("manual",),
            ("experiment_launch",),
            ("experiment_stop",),
            ("experiment_update",),
        ]
    )
    def test_request_recalculation_persists_trigger(self, trigger: str):
        exp = self._launched_experiment(flag_key=f"trigger-{trigger}")
        result = request_recalculation(exp, self.user, trigger)
        assert result["trigger"] == trigger
        row = ExperimentMetricsRecalculation.objects.get(id=result["id"])
        assert row.trigger == trigger

    def test_get_latest_recalculation_returns_most_recent(self):
        exp = self._launched_experiment()
        first = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="completed")
        second = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        latest = get_latest_recalculation(exp)
        assert latest is not None
        assert latest.id == second.id
        assert latest.id != first.id

    def test_get_latest_recalculation_none_when_no_runs(self):
        exp = self._launched_experiment()
        assert get_latest_recalculation(exp) is None

    def test_get_run_results_scopes_by_recalc_fingerprint(self):
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=["m1"],
            status="completed",
            query_to=timezone.now(),
        )
        config_fp = compute_metric_fingerprint(
            exp.metrics[0],
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
        )
        recalc_fp = compute_recalc_fingerprint(config_fp, str(recalc.id))

        # The row from THIS run (recalc-fingerprinted) — must be returned.
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=exp.start_date,
            query_to=recalc.query_to,
            status="completed",
            result={"ok": True},
        )
        # A stale row from another run / different fingerprint — must NOT be returned.
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint="some-other-fingerprint",
            query_from=exp.start_date,
            query_to=datetime(2026, 4, 1, tzinfo=UTC),
            status="completed",
            result={"stale": True},
        )

        results = get_run_results(recalc)
        assert len(results) == 1
        assert results[0]["metric_uuid"] == "m1"
        assert results[0]["status"] == "completed"
        assert results[0]["result"] == {"ok": True}
        assert results[0]["error_message"] is None

    def test_get_run_results_returns_empty_when_no_rows_yet(self):
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team, experiment=exp, metric_uuids=["m1"], status="in_progress"
        )
        assert get_run_results(recalc) == []

    def test_get_run_results_returns_empty_when_no_metrics_persisted(self):
        # Discovery hasn't yet persisted metric_uuids onto the job.
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        assert get_run_results(recalc) == []
