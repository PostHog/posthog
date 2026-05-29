import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.temporal.models import RecalculationProgressUpdate
from products.experiments.backend.temporal.recalculation_activities import (
    _discover_experiment_metrics_sync,
    _update_recalculation_progress_sync,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_discover_raw = _discover_experiment_metrics_sync.func  # type: ignore[attr-defined]
_update_raw = _update_recalculation_progress_sync.func  # type: ignore[attr-defined]


def _discover(recalculation_id: str):
    with patch("products.experiments.backend.temporal.recalculation_activities.close_old_connections"):
        return _discover_raw(recalculation_id)


def _update(update: RecalculationProgressUpdate):
    with patch("products.experiments.backend.temporal.recalculation_activities.close_old_connections"):
        return _update_raw(update)


@pytest.mark.django_db(transaction=True)
class TestRecalculationActivities(BaseTest):
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

    def _experiment(self, flag_key: str) -> Experiment:
        return Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag(flag_key), name="exp"
        )

    def _recalc(self, exp: Experiment) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp)

    def _attach_saved_metric(self, exp: Experiment, uuid: str, metric_type: str) -> None:
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name=f"saved-{uuid}",
            query={"uuid": uuid, "kind": "ExperimentMetric", "metric_type": "mean"},
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": metric_type})

    @parameterized.expand(
        [
            (
                "primary_and_secondary",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [{"uuid": "m2", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                {"m1", "m2"},
                {"primary", "secondary"},
            ),
            ("no_metrics", [], [], [], set(), set()),
            (
                "primary_only",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                [],
                {"m1"},
                {"primary"},
            ),
            (
                "saved_metrics_only",
                [],
                [],
                [("s1", "primary"), ("s2", "secondary")],
                {"s1", "s2"},
                {"primary", "secondary"},
            ),
            (
                "inline_and_saved_mixed",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                [("s1", "secondary")],
                {"m1", "s1"},
                {"primary", "secondary"},
            ),
        ]
    )
    def test_discover_persists_metric_uuids(self, name: str, primary, secondary, saved, expected_uuids, expected_types):
        exp = self._experiment(flag_key=f"discover-{name}")
        exp.metrics = primary
        exp.metrics_secondary = secondary
        exp.save()
        for uuid, metric_type in saved:
            self._attach_saved_metric(exp, uuid, metric_type)
        recalc = self._recalc(exp)

        metrics = _discover(str(recalc.id))

        recalc.refresh_from_db()
        assert set(recalc.metric_uuids) == expected_uuids
        assert {m.metric_uuid for m in metrics} == expected_uuids
        assert {m.metric_type for m in metrics} == expected_types

    @parameterized.expand(
        [
            (
                "start",
                {
                    "status": "in_progress",
                    "total_metrics": 3,
                    "metric_uuids": ["m1", "m2", "m3"],
                    "mark_started": True,
                },
                "in_progress",
                True,  # expects query_to set + returned
            ),
            (
                "finish",
                {"status": "completed", "mark_completed": True},
                "completed",
                False,  # finish does not set/return query_to
            ),
        ]
    )
    def test_update_progress(self, name: str, update_kwargs: dict, expected_status: str, expects_query_to: bool):
        recalc = self._recalc(self._experiment(flag_key=f"progress-{name}"))
        returned = _update(RecalculationProgressUpdate(recalculation_id=str(recalc.id), **update_kwargs))

        recalc.refresh_from_db()
        assert recalc.status == expected_status

        if expects_query_to:
            assert recalc.started_at is not None
            assert recalc.total_metrics == update_kwargs["total_metrics"]
            assert recalc.metric_uuids == update_kwargs["metric_uuids"]
            assert recalc.query_to is not None
            # Returns the query_to it set (ISO string) so the workflow can thread it into calc activities.
            assert returned == recalc.query_to.isoformat()
        else:
            assert recalc.completed_at is not None
            assert returned is None
