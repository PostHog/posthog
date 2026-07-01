from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentVariantResultFrequentist,
)

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentValueBreakdown(ExperimentQueryRunnerBaseTest):
    # Each (distinct_id, amount, plan) purchase, plus exposed users with no purchase and a
    # purchase with no `plan` property. Shared by the decomposition and headline tests so the
    # expected per-value sums below stay in sync with the data.
    CONTROL_PURCHASES = [
        ("user_control_0", 10, "free"),
        ("user_control_1", 20, "free"),
        ("user_control_1", 5, "pro"),
        ("user_control_2", 8, "pro"),
        ("user_control_4", 7, None),  # no `plan` -> null bucket
    ]
    CONTROL_EXPOSED = ["user_control_0", "user_control_1", "user_control_2", "user_control_3", "user_control_4"]
    TEST_PURCHASES = [
        ("user_test_0", 12, "free"),
        ("user_test_1", 30, "free"),
        ("user_test_2", 6, "pro"),
        ("user_test_4", 9, None),
    ]
    TEST_EXPOSED = ["user_test_0", "user_test_1", "user_test_2", "user_test_3", "user_test_4"]

    def _create_value_breakdown_data(self, feature_flag) -> None:
        feature_flag_property = f"$feature/{feature_flag.key}"

        for variant, exposed, purchases in (
            ("control", self.CONTROL_EXPOSED, self.CONTROL_PURCHASES),
            ("test", self.TEST_EXPOSED, self.TEST_PURCHASES),
        ):
            for distinct_id in exposed:
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
            for distinct_id, amount, plan in purchases:
                properties = {feature_flag_property: variant, "amount": amount}
                if plan is not None:
                    properties["plan"] = plan
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties=properties,
                )

        flush_persons_and_events()

    def _run(self, experiment, metric) -> ExperimentQueryResponse:
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return cast(ExperimentQueryResponse, ExperimentQueryRunner(query=experiment_query, team=self.team).calculate())

    @parameterized.expand(
        [
            # math, expected control per-bucket sums, expected control overall sum
            ("sum", ExperimentMetricMathType.SUM, {"free": 30.0, "pro": 13.0, BREAKDOWN_NULL_STRING_LABEL: 7.0}, 50.0),
            ("count", ExperimentMetricMathType.TOTAL, {"free": 2.0, "pro": 2.0, BREAKDOWN_NULL_STRING_LABEL: 1.0}, 5.0),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_value_breakdown_decomposition(self, _name, math, expected_control_sums, expected_control_total):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()
        self._create_value_breakdown_data(feature_flag)

        # math_property is ignored for count (TOTAL) math, so it is safe to always pass.
        source = EventsNode(event="purchase", math=math, math_property="amount")
        metric = ExperimentMeanMetric(source=source, value_breakdown_property="plan")

        result = self._run(experiment, metric)

        assert result.breakdown_results is not None
        by_bucket = {tuple(br.breakdown_value): br for br in result.breakdown_results}

        # Every property value is its own split (including the null bucket for the property-less event).
        self.assertEqual(set(by_bucket.keys()), {("free",), ("pro",), (BREAKDOWN_NULL_STRING_LABEL,)})

        # Full exposure denominator: each split is measured over ALL 5 control users, not just the
        # ones who hit that value. This is the core difference from a breakdownFilter.
        for br in result.breakdown_results:
            self.assertEqual(br.baseline.number_of_samples, len(self.CONTROL_EXPOSED))

        # Effect decomposition: the per-value sums add back to the un-split total.
        for bucket, expected_sum in expected_control_sums.items():
            self.assertAlmostEqual(by_bucket[(bucket,)].baseline.sum, expected_sum, places=6)
        self.assertAlmostEqual(
            sum(br.baseline.sum for br in result.breakdown_results), expected_control_total, places=6
        )
        # The headline (un-split) total equals that same sum.
        assert result.baseline is not None
        self.assertAlmostEqual(result.baseline.sum, expected_control_total, places=6)
        self.assertEqual(result.baseline.number_of_samples, len(self.CONTROL_EXPOSED))

    @freeze_time("2020-01-01T12:00:00Z")
    def test_value_breakdown_full_denominator_when_variant_missing_value(self):
        # "premium" occurs only for control; no test user has it. The test arm's premium split must
        # still cover ALL exposed test users (sum 0), not collapse to 0 samples — otherwise the
        # decomposition silently drops one variant for any value that appears in just one arm.
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"
        exposed = {"control": ["c0", "c1", "c2"], "test": ["t0", "t1", "t2"]}
        purchases = [
            ("control", "c0", 10, "free"),
            ("control", "c1", 5, "premium"),  # premium: control only
            ("test", "t0", 8, "free"),
        ]
        for variant, distinct_ids in exposed.items():
            for distinct_id in distinct_ids:
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
        for variant, distinct_id, amount, plan in purchases:
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant, "amount": amount, "plan": plan},
            )
        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            value_breakdown_property="plan",
        )
        result = self._run(experiment, metric)

        assert result.breakdown_results is not None
        premium = next(br for br in result.breakdown_results if br.breakdown_value == ["premium"])

        # Control hit premium: full denominator and the real sum.
        self.assertEqual(premium.baseline.number_of_samples, 3)
        self.assertAlmostEqual(premium.baseline.sum, 5.0, places=6)

        # Test had zero premium events, but its split still covers all 3 exposed users with sum 0.
        test_variant = cast(
            ExperimentVariantResultFrequentist,
            next(variant for variant in premium.variants if variant.key == "test"),
        )
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertAlmostEqual(test_variant.sum, 0.0, places=6)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_value_breakdown_headline_matches_unsplit_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()
        self._create_value_breakdown_data(feature_flag)

        def make_source() -> EventsNode:
            return EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")

        plain = self._run(experiment, ExperimentMeanMetric(source=make_source()))
        split = self._run(experiment, ExperimentMeanMetric(source=make_source(), value_breakdown_property="plan"))

        # Turning on value breakdown must not move the overall numbers — it only adds splits.
        assert plain.baseline is not None and split.baseline is not None
        assert plain.variant_results is not None and split.variant_results is not None
        self.assertEqual(split.baseline.number_of_samples, plain.baseline.number_of_samples)
        self.assertAlmostEqual(split.baseline.sum, plain.baseline.sum, places=6)
        self.assertAlmostEqual(split.baseline.sum_squares, plain.baseline.sum_squares, places=6)
        # stats_config is frequentist, so the variant lists are ExperimentVariantResultFrequentist;
        # cast narrows the list[Frequentist] | list[Bayesian] union (which mypy joins to BaseModel).
        plain_variants = cast(list[ExperimentVariantResultFrequentist], plain.variant_results)
        split_variants = cast(list[ExperimentVariantResultFrequentist], split.variant_results)
        self.assertEqual(len(split_variants), len(plain_variants))
        for plain_variant, split_variant in zip(plain_variants, split_variants):
            self.assertEqual(split_variant.number_of_samples, plain_variant.number_of_samples)
            self.assertAlmostEqual(split_variant.sum, plain_variant.sum, places=6)
        self.assertIsNone(plain.breakdown_results)
        self.assertIsNotNone(split.breakdown_results)

    @parameterized.expand(
        [
            (
                "avg_math",
                lambda: ExperimentMeanMetric(
                    source=EventsNode(event="purchase", math=ExperimentMetricMathType.AVG, math_property="amount"),
                    value_breakdown_property="plan",
                ),
            ),
            (
                "data_warehouse_source",
                lambda: ExperimentMeanMetric(
                    source=ExperimentDataWarehouseNode(
                        table_name="usage",
                        timestamp_field="ds",
                        events_join_key="properties.userid",
                        data_warehouse_join_key="userid",
                        math=ExperimentMetricMathType.SUM,
                        math_property="usage",
                    ),
                    value_breakdown_property="plan",
                ),
            ),
            (
                "combined_with_breakdown_filter",
                lambda: ExperimentMeanMetric(
                    source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
                    breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
                    value_breakdown_property="plan",
                ),
            ),
            (
                "combined_with_winsorization",
                lambda: ExperimentMeanMetric(
                    source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
                    lower_bound_percentile=0.01,
                    value_breakdown_property="plan",
                ),
            ),
            (
                "combined_with_threshold",
                lambda: ExperimentMeanMetric(
                    source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
                    threshold=2,
                    value_breakdown_property="plan",
                ),
            ),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_value_breakdown_rejects_invalid_configuration(self, _name, make_metric):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=make_metric())
        with self.assertRaises(ValidationError):
            ExperimentQueryRunner(query=experiment_query, team=self.team)
