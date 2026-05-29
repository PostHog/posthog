import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.temporal.models import RecalculationProgressUpdate
from products.experiments.backend.temporal.recalculation_logic import (
    _calculate_experiment_metric_for_recalculation_sync,
    _discover_experiment_metrics_sync,
    _update_recalculation_progress_sync,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_discover_raw = _discover_experiment_metrics_sync.func  # type: ignore[attr-defined]
_update_raw = _update_recalculation_progress_sync.func  # type: ignore[attr-defined]
_calculate_raw = _calculate_experiment_metric_for_recalculation_sync.func  # type: ignore[attr-defined]


def _discover(recalculation_id: str):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _discover_raw(recalculation_id)


def _update(update: RecalculationProgressUpdate):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _update_raw(update)


def _calculate(experiment_id: int, metric_uuid: str, recalculation_id: str, query_to: str):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _calculate_raw(experiment_id, metric_uuid, recalculation_id, query_to)


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


_QUERY_TO = "2026-05-29T12:00:00+00:00"


def _mean_metric(uuid: str) -> dict:
    # ExperimentMeanMetric requires a `source`; a bare {uuid, metric_type} dict fails pydantic validation.
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


@pytest.mark.django_db(transaction=True)
class TestCalculateActivity(BaseTest):
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

    def _experiment(self, flag_key: str, *, with_start_date: bool = True, metrics=None) -> Experiment:
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(flag_key),
            name="exp",
            start_date=timezone.now() if with_start_date else None,
        )
        if metrics is not None:
            exp.metrics = metrics
            exp.save()
        return exp

    def _recalc(self, exp: Experiment, total: int = 1) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, total_metrics=total)

    def test_metric_not_found_fails_at_discovery(self):
        exp = self._experiment(flag_key="calc-missing", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp)

        result = _calculate(exp.id, "does-not-exist", str(recalc.id), _QUERY_TO)

        assert result.success is False
        assert result.error_step == "discovery"
        recalc.refresh_from_db()
        assert recalc.failed_metrics == 1
        assert "does-not-exist" in recalc.errors

    def test_bad_metric_type_fails_at_calculation(self):
        # Legacy metrics never reach this workflow, so there's no discovery-time type guard; an unexpected
        # metric_type raises while building the metric and surfaces as a calculation-step failure.
        exp = self._experiment(
            flag_key="calc-badtype",
            metrics=[{"uuid": "m-bad", "metric_type": "nonsense", "kind": "ExperimentMetric"}],
        )
        recalc = self._recalc(exp)

        result = _calculate(exp.id, "m-bad", str(recalc.id), _QUERY_TO)

        assert result.success is False
        assert result.error_step == "calculation"
        recalc.refresh_from_db()
        assert recalc.failed_metrics == 1
        assert "m-bad" in recalc.errors

    def test_missing_start_date_fails(self):
        exp = self._experiment(flag_key="calc-no-start", with_start_date=False, metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp)

        result = _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        assert result.success is False
        recalc.refresh_from_db()
        assert recalc.failed_metrics == 1

    def test_saved_metric_is_resolvable(self):
        # A saved/shared metric (uuid only on saved_metric.query) must be found by the calc lookup; otherwise it
        # would wrongly fail at the discovery step. We force a calculation error so the run reaches the metric via
        # the saved-metric branch but fails for a non-lookup reason.
        exp = self._experiment(flag_key="calc-saved")
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="saved-s1",
            query=_mean_metric("s1"),
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": "primary"})
        recalc = self._recalc(exp)

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value._calculate.side_effect = RuntimeError("kaboom")
            result = _calculate(exp.id, "s1", str(recalc.id), _QUERY_TO)

        # Found the saved metric (did not fail at discovery) but failed during calculation.
        assert result.success is False
        assert result.error_step == "calculation"
        recalc.refresh_from_db()
        assert "s1" in recalc.errors

    def test_concurrent_failures_do_not_lose_error_entries(self):
        exp = self._experiment(flag_key="calc-concurrent")
        recalc = self._recalc(exp, total=2)

        _calculate(exp.id, "missing-a", str(recalc.id), _QUERY_TO)
        _calculate(exp.id, "missing-b", str(recalc.id), _QUERY_TO)

        recalc.refresh_from_db()
        assert recalc.failed_metrics == 2
        assert set(recalc.errors.keys()) == {"missing-a", "missing-b"}

    def test_unexpected_error_calls_capture_exception_and_caps_message(self):
        exp = self._experiment(flag_key="calc-capture", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp)

        with (
            patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner,
            patch("products.experiments.backend.temporal.recalculation_logic.capture_exception") as mock_capture,
        ):
            mock_runner.return_value._calculate.side_effect = RuntimeError("x" * 5000)
            result = _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        assert result.success is False
        assert mock_capture.called
        assert result.error_message is not None
        assert len(result.error_message) <= 2000
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.status == ExperimentMetricResult.Status.FAILED
        assert row.error_message is not None
        assert len(row.error_message) <= 2000
