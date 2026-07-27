import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.temporal.canary_logic import (
    evaluate_canary_runs,
    relative_deviation,
    report_canary_results_sync,
    run_metric_canary_sync,
    sample_canary_targets_sync,
)
from products.experiments.backend.temporal.models import (
    OUTCOME_DIVERGENCE,
    OUTCOME_ERROR,
    OUTCOME_PASS,
    OUTCOME_PATH_FLIP,
    OUTCOME_SKIPPED,
    CanaryMetricResult,
    CanaryMetricTarget,
    CanaryReportInputs,
    CanaryRunSnapshot,
    CanaryVariantStats,
    ExperimentPrecomputeCanaryInputs,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _snapshot(label: str, variants: dict[str, tuple[float, int]], is_precomputed: bool = True) -> CanaryRunSnapshot:
    return CanaryRunSnapshot(
        label=label,
        query_id=f"experiment-canary-test-{label}",
        is_precomputed=is_precomputed,
        variants={
            key: CanaryVariantStats(sum=sum_, number_of_samples=samples) for key, (sum_, samples) in variants.items()
        },
    )


_BASE = {"control": (1000.0, 10000), "test": (1100.0, 10000)}


class TestRelativeDeviation:
    @parameterized.expand(
        [
            # name, a, b, expected
            ("both_zero", 0.0, 0.0, 0.0),
            ("denominator_is_larger_value", 1000.0, 1005.0, 5.0 / 1005.0),
            ("one_zero_below_floor", 0.0, 0.5, 0.5),  # denominator floored at 1.0
            ("negative_values", -10.0, 10.0, 2.0),
        ]
    )
    def test_relative_deviation(self, _name, a, b, expected):
        assert relative_deviation(a, b) == pytest.approx(expected)
        assert relative_deviation(b, a) == pytest.approx(expected)


class TestEvaluateCanaryRuns:
    @parameterized.expand(
        [
            # name, metric_type, run_a variants, run_b variants, run_c variants, expected outcome
            ("identical_funnel_passes", "funnel", _BASE, _BASE, _BASE, OUTCOME_PASS),
            (
                "funnel_within_strict_tolerance_passes",
                "funnel",
                _BASE,
                {"control": (1000.4, 10000), "test": (1100.0, 10000)},  # 0.04% < 0.1%
                _BASE,
                OUTCOME_PASS,
            ),
            (
                "funnel_sum_drift_between_precomputed_reads_diverges",
                "funnel",
                _BASE,
                {"control": (1005.0, 10000), "test": (1100.0, 10000)},  # 0.5% > 0.1%
                {"control": (1005.0, 10000), "test": (1100.0, 10000)},
                OUTCOME_DIVERGENCE,
            ),
            (
                "funnel_samples_drift_between_precomputed_reads_diverges",
                "funnel",
                _BASE,
                {"control": (1000.0, 10050), "test": (1100.0, 10000)},  # 0.5% > 0.1%
                {"control": (1000.0, 10050), "test": (1100.0, 10000)},
                OUTCOME_DIVERGENCE,
            ),
            (
                "mean_sum_drift_between_precomputed_reads_passes",
                "mean",
                _BASE,
                {"control": (1010.0, 10000), "test": (1100.0, 10000)},  # 1% < 2% loose, sums join live values
                {"control": (1010.0, 10000), "test": (1100.0, 10000)},
                OUTCOME_PASS,
            ),
            (
                "mean_samples_drift_between_precomputed_reads_diverges",
                "mean",
                _BASE,
                {"control": (1000.0, 10050), "test": (1100.0, 10000)},  # exposures are frozen: strict
                {"control": (1000.0, 10050), "test": (1100.0, 10000)},
                OUTCOME_DIVERGENCE,
            ),
            (
                "direct_scan_within_loose_tolerance_passes",
                "funnel",
                _BASE,
                _BASE,
                {"control": (1010.0, 10080), "test": (1108.0, 10000)},  # ~1% < 2%
                OUTCOME_PASS,
            ),
            (
                "direct_scan_beyond_loose_tolerance_diverges",
                "funnel",
                _BASE,
                _BASE,
                {"control": (1300.0, 10000), "test": (1100.0, 10000)},  # 23% — the incident signature
                OUTCOME_DIVERGENCE,
            ),
        ]
    )
    def test_outcomes(self, _name, metric_type, a, b, c, expected):
        verdict = evaluate_canary_runs(metric_type, _snapshot("a", a), _snapshot("b", b), _snapshot("c", c))
        assert verdict.outcome == expected

    def test_path_flip_is_not_divergence(self):
        diverged = {"control": (1300.0, 12000), "test": (1100.0, 10000)}
        verdict = evaluate_canary_runs(
            "funnel", _snapshot("a", _BASE, is_precomputed=False), _snapshot("b", diverged), _snapshot("c", diverged)
        )
        assert verdict.outcome == OUTCOME_PATH_FLIP
        assert "a" in (verdict.detail or "")

    def test_direct_run_not_precomputed_is_expected(self):
        verdict = evaluate_canary_runs(
            "funnel", _snapshot("a", _BASE), _snapshot("b", _BASE), _snapshot("c", _BASE, is_precomputed=False)
        )
        assert verdict.outcome == OUTCOME_PASS

    def test_path_flip_takes_precedence_over_variant_mismatch(self):
        verdict = evaluate_canary_runs(
            "funnel",
            _snapshot("a", {"control": (1000.0, 10000)}, is_precomputed=False),
            _snapshot("b", _BASE),
            _snapshot("c", _BASE),
        )
        assert verdict.outcome == OUTCOME_PATH_FLIP

    def test_low_volume_in_direct_scan_is_skipped(self):
        thin_c = {"control": (1000.0, 10000), "test": (5.0, 50)}
        verdict = evaluate_canary_runs("funnel", _snapshot("a", _BASE), _snapshot("b", _BASE), _snapshot("c", thin_c))
        assert verdict.outcome == OUTCOME_SKIPPED

    def test_variant_set_mismatch_is_error(self):
        verdict = evaluate_canary_runs(
            "funnel", _snapshot("a", _BASE), _snapshot("b", _BASE), _snapshot("c", {"control": (1000.0, 10000)})
        )
        assert verdict.outcome == OUTCOME_ERROR

    def test_empty_results_are_skipped(self):
        verdict = evaluate_canary_runs("funnel", _snapshot("a", _BASE), _snapshot("b", {}), _snapshot("c", _BASE))
        assert verdict.outcome == OUTCOME_SKIPPED

    def test_low_volume_is_skipped(self):
        low = {"control": (10.0, 50), "test": (12.0, 60)}
        verdict = evaluate_canary_runs("funnel", _snapshot("a", low), _snapshot("b", low), _snapshot("c", low))
        assert verdict.outcome == OUTCOME_SKIPPED

    def test_deviations_are_reported_on_pass(self):
        c = {"control": (1010.0, 10000), "test": (1100.0, 10000)}
        verdict = evaluate_canary_runs("funnel", _snapshot("a", _BASE), _snapshot("b", _BASE), _snapshot("c", c))
        assert verdict.stability_deviation == 0.0
        assert verdict.correctness_deviation == pytest.approx(0.01, rel=0.05)


def _inline_metric(metric_type: str) -> dict:
    return {"uuid": str(uuid.uuid4()), "kind": "ExperimentMetric", "metric_type": metric_type}


def _funnel_metric() -> dict:
    return {**_inline_metric("funnel"), "series": [{"kind": "EventsNode", "event": "purchase"}]}


@pytest.fixture(autouse=True)
def _keep_test_connection(request):
    # close_old_connections() would sever the test transaction's connection.
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    with patch("products.experiments.backend.temporal.canary_logic.close_old_connections"):
        yield


@pytest.mark.django_db(transaction=True)
class TestCanarySampling(BaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
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

    def _experiment(self, metrics: list[dict], days_running: int = 3, **kwargs) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(f"flag-{uuid.uuid4().hex[:8]}"),
            name="exp",
            metrics=metrics,
            start_date=timezone.now() - timedelta(days=days_running),
            **kwargs,
        )

    def _enable_precompute(self) -> None:
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team, defaults={"experiment_precomputation_enabled": True}
        )

    def test_teams_without_precompute_enabled_are_never_sampled(self):
        self._experiment([_inline_metric("funnel")])
        assert sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs()) == []

    @parameterized.expand(
        [
            # name, experiment kwargs
            ("not_launched", {"start_date": None}),
            ("stopped", {"end_date": timezone.now}),
            ("too_young", {"start_date": timezone.now}),
            ("deleted", {"deleted": True}),
            ("archived", {"archived": True}),
        ]
    )
    def test_ineligible_experiments_are_not_sampled(self, _name, overrides):
        self._enable_precompute()
        resolved = {key: value() if callable(value) else value for key, value in overrides.items()}
        experiment = self._experiment([_inline_metric("funnel")])
        Experiment.objects.filter(id=experiment.id).update(**resolved)
        assert sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs()) == []

    def test_retention_and_legacy_metrics_are_dropped(self):
        self._enable_precompute()
        legacy = {"uuid": str(uuid.uuid4()), "kind": "ExperimentTrendsQuery"}  # no metric_type
        self._experiment([_inline_metric("retention"), legacy])
        assert sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs()) == []

    def test_quotas_and_per_experiment_cap(self):
        self._enable_precompute()
        experiment = self._experiment([_inline_metric("funnel") for _ in range(10)])
        targets = sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs(funnel_quota=5, per_experiment_cap=3))
        assert len(targets) == 3
        assert all(t.experiment_id == experiment.id and t.metric_type == "funnel" for t in targets)
        assert len({t.metric_uuid for t in targets}) == 3

        targets = sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs(funnel_quota=2, per_experiment_cap=10))
        assert len(targets) == 2

    def test_includes_secondary_and_saved_metrics(self):
        self._enable_precompute()
        secondary = _inline_metric("mean")
        experiment = self._experiment([])
        Experiment.objects.filter(id=experiment.id).update(metrics_secondary=[secondary])
        saved_uuid = str(uuid.uuid4())
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="saved",
            query={"uuid": saved_uuid, "kind": "ExperimentMetric", "metric_type": "funnel"},
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved, metadata={"type": "primary"})

        targets = sample_canary_targets_sync(ExperimentPrecomputeCanaryInputs(per_experiment_cap=10))
        assert {t.metric_uuid for t in targets} == {secondary["uuid"], saved_uuid}

    def test_forensics_mode_ignores_team_config_and_quotas(self):
        metrics = [_inline_metric("funnel") for _ in range(5)]
        experiment = self._experiment(metrics)  # precompute NOT enabled for the team
        targets = sample_canary_targets_sync(
            ExperimentPrecomputeCanaryInputs(experiment_id=experiment.id, funnel_quota=1, per_experiment_cap=1)
        )
        assert len(targets) == 5

    def test_forensics_mode_metric_uuid_filter(self):
        metrics = [_inline_metric("funnel"), _inline_metric("mean")]
        experiment = self._experiment(metrics)
        targets = sample_canary_targets_sync(
            ExperimentPrecomputeCanaryInputs(experiment_id=experiment.id, metric_uuids=[metrics[1]["uuid"]])
        )
        assert [t.metric_uuid for t in targets] == [metrics[1]["uuid"]]


@pytest.mark.django_db(transaction=True)
class TestRunMetricCanary(BaseTest):
    def _experiment(self, metrics: list[dict]) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=f"flag-{uuid.uuid4().hex[:8]}",
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
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            metrics=metrics,
            start_date=timezone.now() - timedelta(days=3),
        )

    def _target(self, experiment: Experiment, metric_uuid: str) -> CanaryMetricTarget:
        return CanaryMetricTarget(
            team_id=self.team.id, experiment_id=experiment.id, metric_uuid=metric_uuid, metric_type="funnel"
        )

    def test_missing_experiment_is_skipped(self):
        result = run_metric_canary_sync(
            CanaryMetricTarget(team_id=self.team.id, experiment_id=999999, metric_uuid="x", metric_type="funnel")
        )
        assert result.outcome == OUTCOME_SKIPPED

    def test_missing_metric_is_skipped(self):
        experiment = self._experiment([])
        result = run_metric_canary_sync(self._target(experiment, str(uuid.uuid4())))
        assert result.outcome == OUTCOME_SKIPPED

    def test_metric_type_changed_to_ineligible_is_skipped(self):
        metric = _inline_metric("retention")
        experiment = self._experiment([metric])
        result = run_metric_canary_sync(self._target(experiment, metric["uuid"]))  # target still says funnel
        assert result.outcome == OUTCOME_SKIPPED

    def test_unparseable_metric_is_skipped(self):
        metric = {"uuid": str(uuid.uuid4()), "metric_type": "funnel"}  # missing required series
        experiment = self._experiment([metric])
        result = run_metric_canary_sync(self._target(experiment, metric["uuid"]))
        assert result.outcome == OUTCOME_SKIPPED

    def test_runs_three_times_and_evaluates(self):
        metric = _funnel_metric()
        experiment = self._experiment([metric])
        snapshots = [_snapshot("a", _BASE), _snapshot("b", _BASE), _snapshot("c", _BASE)]
        with patch(
            "products.experiments.backend.temporal.canary_logic._execute_canary_run", side_effect=snapshots
        ) as mock_run:
            result = run_metric_canary_sync(self._target(experiment, metric["uuid"]))

        assert result.outcome == OUTCOME_PASS
        assert [call.args[3] for call in mock_run.call_args_list] == ["a", "b", "c"]
        modes = [call.args[2].value for call in mock_run.call_args_list]
        assert modes == ["precomputed", "precomputed", "direct"]
        assert len(result.runs) == 3

    def test_query_failure_raises_for_temporal_retry(self):
        metric = _funnel_metric()
        experiment = self._experiment([metric])
        with patch(
            "products.experiments.backend.temporal.canary_logic._execute_canary_run",
            side_effect=RuntimeError("clickhouse timeout"),
        ):
            with pytest.raises(RuntimeError):
                run_metric_canary_sync(self._target(experiment, metric["uuid"]))


def _result(outcome: str, **kwargs) -> CanaryMetricResult:
    target = CanaryMetricTarget(team_id=1, experiment_id=2, metric_uuid="m-uuid", metric_type="funnel")
    return CanaryMetricResult(target=target, outcome=outcome, runs=[_snapshot("a", _BASE)], **kwargs)


class TestCanaryReporting:
    @override_settings(EXPERIMENT_CANARY_SLACK_WEBHOOK_URL="")
    def test_no_slack_when_webhook_unset(self):
        with patch("products.experiments.backend.temporal.canary_logic.requests.post") as post:
            report_canary_results_sync(CanaryReportInputs(results=[_result(OUTCOME_DIVERGENCE)]))
        post.assert_not_called()

    @override_settings(EXPERIMENT_CANARY_SLACK_WEBHOOK_URL="https://hooks.example.com/secret")
    def test_no_slack_when_nothing_diverged(self):
        with patch("products.experiments.backend.temporal.canary_logic.requests.post") as post:
            report_canary_results_sync(
                CanaryReportInputs(results=[_result(OUTCOME_PASS), _result(OUTCOME_ERROR), _result(OUTCOME_SKIPPED)])
            )
        post.assert_not_called()

    @override_settings(EXPERIMENT_CANARY_SLACK_WEBHOOK_URL="https://hooks.example.com/secret")
    def test_slack_posted_on_divergence(self):
        with patch(
            "products.experiments.backend.temporal.canary_logic.requests.post", return_value=MagicMock()
        ) as post:
            report_canary_results_sync(
                CanaryReportInputs(results=[_result(OUTCOME_DIVERGENCE, stability_deviation=0.3)])
            )
        post.assert_called_once()
        args, kwargs = post.call_args
        assert args[0] == "https://hooks.example.com/secret"
        assert kwargs["timeout"] == 10
        body = str(kwargs["json"])
        assert "experiment 2" in body
        assert "m-uuid" in body

    @override_settings(EXPERIMENT_CANARY_SLACK_WEBHOOK_URL="https://hooks.example.com/secret")
    def test_slack_failure_is_swallowed_and_does_not_log_the_url(self):
        error = requests.RequestException("404 for url: https://hooks.example.com/secret")
        with patch("products.experiments.backend.temporal.canary_logic.requests.post", side_effect=error):
            with patch("products.experiments.backend.temporal.canary_logic.logger.warning") as warning:
                report_canary_results_sync(CanaryReportInputs(results=[_result(OUTCOME_DIVERGENCE)]))
        assert "secret" not in str(warning.call_args)
