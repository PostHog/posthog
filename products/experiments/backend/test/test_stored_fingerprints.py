from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.stored_fingerprints import (
    FingerprintRewriteReport,
    rewrite_stored_fingerprints,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str, **fields: Any) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
        **fields,
    }


class TestStoredFingerprints(BaseTest):
    def _experiment(self, key: str, *, deleted: bool = False) -> Experiment:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key=key)
        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name=key,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            deleted=deleted,
            metrics=[_mean_metric("stale"), _mean_metric("unstamped")],
            metrics_secondary=[_mean_metric("current")],
        )
        keys = {
            calculation_config.metric_id: calculation_config
            for calculation_config in (get_metric_calculation_config(experiment, uuid) for uuid in ("stale", "current"))
            if calculation_config
        }
        # A metric stamped before the key version changed, one never stamped, and one stamped with the current key.
        Experiment.objects.filter(pk=experiment.pk).update(
            metrics=[_mean_metric("stale", fingerprint=keys["stale"].legacy_key()), _mean_metric("unstamped")],
            metrics_secondary=[_mean_metric("current", fingerprint=keys["current"].calculation_key())],
        )
        experiment.refresh_from_db()
        return experiment

    def _current_key(self, experiment: Experiment, uuid: str) -> str:
        calculation_config = get_metric_calculation_config(experiment, uuid)
        assert calculation_config is not None
        return calculation_config.calculation_key()

    @parameterized.expand([("dry_run", False), ("apply", True)])
    def test_rewrites_only_the_stale_fingerprints(self, _name: str, apply: bool) -> None:
        experiment = self._experiment("rewrite")
        self._experiment("rewrite-deleted", deleted=True)
        before = Experiment.objects.values("metrics", "metrics_secondary", "version", "updated_at").get(
            pk=experiment.pk
        )
        activity = ActivityLog.objects.filter(scope="Experiment", item_id=str(experiment.pk))
        activity_before = activity.count()

        report = rewrite_stored_fingerprints(apply=apply)

        assert report == FingerprintRewriteReport(
            experiments_scanned=1, experiments_to_rewrite=1, metrics_to_rewrite=1, experiments_failed=0
        )
        after = Experiment.objects.values("metrics", "metrics_secondary", "version", "updated_at").get(pk=experiment.pk)
        expected_metrics = (
            [_mean_metric("stale", fingerprint=self._current_key(experiment, "stale")), _mean_metric("unstamped")]
            if apply
            else before["metrics"]
        )
        assert after == {**before, "metrics": expected_metrics}
        assert activity.count() == activity_before
        # A second run finds nothing left to rewrite.
        assert rewrite_stored_fingerprints(apply=apply).experiments_to_rewrite == (0 if apply else 1)

    @parameterized.expand(
        [
            ("dry_run_by_default", [], False),
            ("apply", ["--apply"], True),
            ("apply_to_another_team", ["--apply", "--team-id", "0"], False),
        ]
    )
    def test_the_command_writes_only_when_asked(self, _name: str, arguments: list[str], rewritten: bool) -> None:
        experiment = self._experiment("command")
        stored = experiment.metrics

        call_command("rewrite_experiment_metric_fingerprints", *arguments)

        experiment.refresh_from_db()
        assert (experiment.metrics != stored) is rewritten
