from freezegun import freeze_time

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType, ExperimentQuery

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from products.experiments.backend.models.experiment import ExperimentHoldout


@override_settings(IN_UNIT_TESTING=True)
class TestExcludedVariants(ExperimentQueryRunnerBaseTest):
    # Sentinel used in `excluded_variants` specs to mean "the attached holdout's pseudo-key",
    # resolved to `holdout-{id}` once the holdout row exists.
    _HOLDOUT_KEY = "<holdout>"

    def _make_runner(self, experiment):
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return ExperimentQueryRunner(query=query, team=self.team)

    @parameterized.expand(
        [
            # name, extra_variants, attach_holdout, excluded_variants ("unset" leaves the column as None)
            ("excluded_variant_dropped", ["test-2"], False, ["test-2"]),
            ("empty_exclusions", [], False, []),
            ("column_unset", [], False, "unset"),
            ("holdout_and_excluded_both_filtered", ["test-2"], True, ["test-2"]),
            ("holdout_attached_no_exclusions", [], True, "unset"),
            ("excluded_variants_naming_holdout_is_idempotent", [], True, [_HOLDOUT_KEY]),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_runner_variant_filtering(self, name, extra_variants, attach_holdout, excluded_variants):
        feature_flag = self.create_feature_flag(key=f"{name.replace('_', '-')}-test")
        for index, variant_key in enumerate(extra_variants):
            feature_flag.filters["multivariate"]["variants"].append(
                {"key": variant_key, "name": f"Test {index + 2}", "rollout_percentage": 33}
            )
        if extra_variants:
            feature_flag.save()

        experiment = self.create_experiment(feature_flag=feature_flag)

        holdout = None
        if attach_holdout:
            holdout = ExperimentHoldout.objects.create(
                team=self.team,
                name=f"Holdout {name}",
                filters=[{"properties": [], "rollout_percentage": 20}],
            )
            experiment.holdout = holdout

        if excluded_variants != "unset":
            holdout_key = f"holdout-{holdout.id}" if holdout is not None else self._HOLDOUT_KEY
            experiment.excluded_variants = [
                holdout_key if key == self._HOLDOUT_KEY else key for key in excluded_variants
            ]
        experiment.save()

        runner = self._make_runner(experiment)

        # The runner always reports exactly the analyzable variants — holdout pseudo-variants
        # and excluded variants are filtered out regardless of how they were specified.
        assert set(runner.variants) == {"control", "test"}
        for excluded in extra_variants:
            assert excluded not in runner.variants
        if holdout is not None:
            assert f"holdout-{holdout.id}" not in runner.variants
            assert runner.experiment.holdout is not None  # still readable for UI/etc.


def test_fingerprint_changes_when_excluded_variants_change():
    metric = {"kind": "ExperimentMeanMetric", "source": {"kind": "EventsNode", "event": "$pageview"}}
    start = "2026-01-01T00:00:00+00:00"

    fp_none = compute_metric_fingerprint(metric, start, excluded_variants=None)
    fp_empty = compute_metric_fingerprint(metric, start, excluded_variants=[])
    fp_one = compute_metric_fingerprint(metric, start, excluded_variants=["test-2"])
    fp_two = compute_metric_fingerprint(metric, start, excluded_variants=["test-2", "test-3"])
    fp_two_reversed = compute_metric_fingerprint(metric, start, excluded_variants=["test-3", "test-2"])
    fp_one_other = compute_metric_fingerprint(metric, start, excluded_variants=["test-3"])

    assert fp_none == fp_empty
    assert fp_one != fp_empty
    assert fp_two != fp_one
    assert fp_two_reversed == fp_two, "Order of excluded keys must not affect fingerprint"
    assert fp_one != fp_one_other
