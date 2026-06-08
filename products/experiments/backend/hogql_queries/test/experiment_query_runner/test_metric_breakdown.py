from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    BreakdownFilter,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentMetricOutlierHandling,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestMetricBreakdown(ExperimentQueryRunnerBaseTest):
    def setUp(self):
        super().setUp()
        # The metric-event breakdown injector is gated by a feature flag; force it on for this
        # entire suite so individual tests exercise the new injector without per-test plumbing.
        flag_patcher = patch(
            "products.experiments.backend.hogql_queries.experiment_query_runner.posthoganalytics.feature_enabled",
            return_value=True,
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    @parameterized.expand(
        [
            ("first_touch", BreakdownAttributionType.FIRST_TOUCH, None, {"StepZeroBrowser"}),
            ("last_touch", BreakdownAttributionType.LAST_TOUCH, None, {"StepOneBrowser"}),
            ("step_1", BreakdownAttributionType.STEP, 1, {"StepOneBrowser"}),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_attribution_modes_bucket_correctly(self, _name, attribution, attribution_value, expected_buckets):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="step_zero"), EventsNode(event="step_one")],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
            breakdownAttributionType=attribution,
            breakdownAttributionValue=attribution_value,
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Step 0 and step 1 carry different breakdown values, so each attribution mode resolves differently.
        for variant in ["control", "test"]:
            distinct_id = f"user_{variant}"
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
            _create_event(
                team=self.team,
                event="step_zero",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant, "$browser": "StepZeroBrowser"},
            )
            _create_event(
                team=self.team,
                event="step_one",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:02:00Z",
                properties={feature_flag_property: variant, "$browser": "StepOneBrowser"},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        self.assertEqual(buckets, expected_buckets)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_breakdown_limit_collapses_to_other(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="purchase")],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")], breakdown_limit=2),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Four browser values with descending user counts: Chrome(4) > Safari(3) > Firefox(2) > Edge(1).
        # With breakdown_limit=2, only Chrome + Safari survive; Firefox + Edge collapse to "Other".
        browser_counts = {"Chrome": 4, "Safari": 3, "Firefox": 2, "Edge": 1}
        user_index = 0
        for browser, count in browser_counts.items():
            for _ in range(count):
                variant = "control" if user_index % 2 == 0 else "test"
                distinct_id = f"user_{user_index}"
                user_index += 1
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
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, "$browser": browser},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # Top 2 by frequency survive; the rest collapse into a single "Other" bucket.
        self.assertEqual(buckets, {"Chrome", "Safari", BREAKDOWN_OTHER_STRING_LABEL})

        # The "Other" bucket is ordered last in the breakdown list.
        ordered_values = [value for br in result.breakdown_results for value in br.breakdown_value]
        self.assertEqual(ordered_values[-1], BREAKDOWN_OTHER_STRING_LABEL)

        # The "Other" bucket preserves totals: per-breakdown baseline samples sum to the overall.
        assert result.baseline is not None
        per_breakdown_baseline = sum(
            br.baseline.number_of_samples for br in result.breakdown_results if br.baseline is not None
        )
        self.assertEqual(per_breakdown_baseline, result.baseline.number_of_samples)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_session_property_mean_breakdown_from_metric_event(self):
        import uuid

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        # Session-property metric (aggregates a session-level property) with an event-property breakdown.
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.AVG,
                math_property="$session_duration",
                math_property_type="session_properties",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Exposure carries "ExposureBrowser"; the metric event carries "MetricBrowser".
        for variant in ["control", "test"]:
            distinct_id = f"user_{variant}"
            session_id = str(uuid.uuid4())
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
                    "$browser": "ExposureBrowser",
                    "$session_id": session_id,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:05:00Z",
                properties={feature_flag_property: variant, "$browser": "MetricBrowser", "$session_id": session_id},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # The breakdown is attributed from the metric event, not the exposure.
        self.assertEqual(buckets, {"MetricBrowser"})

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_limit_collapses_to_other(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(
                breakdowns=[Breakdown(property="$browser")],
                breakdown_limit=2,
            ),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Four browser values with descending user counts: Chrome(4) > Safari(3) > Firefox(2) > Edge(1).
        # With breakdown_limit=2, only Chrome + Safari survive; Firefox + Edge collapse to "Other".
        browser_counts = {"Chrome": 4, "Safari": 3, "Firefox": 2, "Edge": 1}
        user_index = 0
        for browser, count in browser_counts.items():
            for _ in range(count):
                variant = "control" if user_index % 2 == 0 else "test"
                distinct_id = f"user_mean_limit_{user_index}"
                user_index += 1
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
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$browser": browser,
                        "amount": 10,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # Top 2 by frequency survive; the rest collapse into a single "Other" bucket.
        self.assertEqual(buckets, {"Chrome", "Safari", BREAKDOWN_OTHER_STRING_LABEL})

        # The "Other" bucket is ordered last.
        ordered_values = [value for br in result.breakdown_results for value in br.breakdown_value]
        self.assertEqual(ordered_values[-1], BREAKDOWN_OTHER_STRING_LABEL)

        # Per-breakdown baseline samples sum to the overall baseline.
        assert result.baseline is not None
        per_breakdown_samples = sum(
            br.baseline.number_of_samples for br in result.breakdown_results if br.baseline is not None
        )
        self.assertEqual(per_breakdown_samples, result.baseline.number_of_samples)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_first_touch_with_changing_metric_event_values(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Each variant has one user who makes TWO purchases: one with "FirstBrowser" (earlier)
        # and one with "SecondBrowser" (later). First-touch attribution must pick "FirstBrowser".
        for variant in ["control", "test"]:
            distinct_id = f"user_changing_{variant}"
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
            # First metric event — should be picked by argMin
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant, "$browser": "FirstBrowser", "amount": 10},
            )
            # Second metric event — later timestamp, different breakdown value
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:02:00Z",
                properties={feature_flag_property: variant, "$browser": "SecondBrowser", "amount": 20},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # Both users' first metric event had "FirstBrowser", so only that bucket should appear.
        self.assertEqual(buckets, {"FirstBrowser"})
        self.assertNotIn("SecondBrowser", buckets)

        # The single bucket must have one user per variant.
        first_browser_breakdown = next(
            (br for br in result.breakdown_results if br.breakdown_value == ["FirstBrowser"]), None
        )
        self.assertIsNotNone(first_browser_breakdown)
        assert first_browser_breakdown is not None
        self.assertIsNotNone(first_browser_breakdown.baseline)
        self.assertEqual(first_browser_breakdown.baseline.number_of_samples, 1)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_with_winsorization_flag_on(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
            lower_bound_percentile=0.05,
            upper_bound_percentile=0.95,
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two browsers on the metric event side (exposure carries no browser property).
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            variant = "control" if i % 2 == 0 else "test"
            distinct_id = f"user_winsor_{i}"
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
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: variant,
                    "$browser": browser,
                    "amount": 10 + i * 5,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # Buckets come from the metric event, not the exposure event.
        self.assertEqual(buckets, {"Chrome", "Safari"})
        for breakdown_result in result.breakdown_results:
            self.assertIsNotNone(breakdown_result.baseline)

    @parameterized.expand(
        [
            ("two_breakdowns", ["$browser", "$os"], 2),
            ("three_breakdowns", ["$browser", "$os", "$device_type"], 3),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_with_multiple_breakdowns_flag_on(self, _name, breakdown_properties, expected_tuple_len):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property=p) for p in breakdown_properties]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Seed two users per variant with deterministic property combinations.
        combos = [
            {"$browser": "Chrome", "$os": "Windows", "$device_type": "Desktop"},
            {"$browser": "Safari", "$os": "Mac", "$device_type": "Mobile"},
        ]
        for variant in ["control", "test"]:
            for idx, combo in enumerate(combos):
                distinct_id = f"user_multi_{variant}_{idx}"
                metric_props = {k: v for k, v in combo.items() if k in breakdown_properties}
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
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: variant,
                        "amount": 10,
                        **metric_props,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        # Every breakdown_value tuple must have the expected number of elements.
        for breakdown_result in result.breakdown_results:
            self.assertEqual(len(breakdown_result.breakdown_value), expected_tuple_len)

        # The two seeded combinations should appear.
        breakdown_values = [tuple(br.breakdown_value) for br in result.breakdown_results]
        expected_chrome = tuple(combos[0][p] for p in breakdown_properties)
        expected_safari = tuple(combos[1][p] for p in breakdown_properties)
        self.assertIn(expected_chrome, breakdown_values)
        self.assertIn(expected_safari, breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_null_values_flag_on(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two users per variant: one with $browser on the metric event, one without.
        for variant in ["control", "test"]:
            for idx, has_browser in enumerate([True, False]):
                distinct_id = f"user_null_{variant}_{idx}"
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
                purchase_props: dict = {feature_flag_property: variant}
                if has_browser:
                    purchase_props["$browser"] = "Chrome"
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties=purchase_props,
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        # The real bucket and the null/missing bucket must both appear.
        self.assertIn(["Chrome"], breakdown_values)
        self.assertIn([BREAKDOWN_NULL_STRING_LABEL], breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_person_property_flag_on(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="country", type="person")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two users per variant; person property carries country (no event-level country).
        country_by_variant = {"control": "US", "test": "UK"}
        for variant, country in country_by_variant.items():
            for i in range(2):
                distinct_id = f"user_person_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk, properties={"country": country})
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
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, "amount": 10},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["US"], breakdown_values)
        self.assertIn(["UK"], breakdown_values)

        us_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["US"]), None)
        self.assertIsNotNone(us_breakdown)
        assert us_breakdown is not None
        self.assertEqual(us_breakdown.baseline.number_of_samples, 2)

        uk_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["UK"]), None)
        self.assertIsNotNone(uk_breakdown)
        assert uk_breakdown is not None
        self.assertEqual(len(uk_breakdown.variants), 1)
        self.assertEqual(uk_breakdown.variants[0].number_of_samples, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_mean_breakdown_unexposed_user_flag_on(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Exposed and converted — should appear in "Chrome" bucket.
        _create_person(distinct_ids=["user_converting_control"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_converting_control",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_converting_control",
            timestamp="2020-01-02T12:01:00Z",
            properties={feature_flag_property: "control", "$browser": "Chrome", "amount": 10},
        )

        # Exposed but did NOT purchase — contributes to exposure count but no metric event.
        _create_person(distinct_ids=["user_exposed_only_control"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_exposed_only_control",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Query must run without error and the converting user's bucket must be present.
        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["Chrome"], breakdown_values)

    def _create_retention_metric(self, breakdown_limit=None):
        return ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
            breakdownFilter=BreakdownFilter(
                breakdowns=[Breakdown(property="$browser")], breakdown_limit=breakdown_limit
            ),
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_from_start_event(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_retention_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Exposure carries "ExposureBrowser"; the start event carries "StartBrowser".
        for variant in ["control", "test"]:
            distinct_id = f"user_{variant}"
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
                    "$browser": "ExposureBrowser",
                },
            )
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant, "$browser": "StartBrowser"},
            )
            _create_event(
                team=self.team,
                event="login",
                distinct_id=distinct_id,
                timestamp="2020-01-03T12:01:00Z",
                properties={feature_flag_property: variant, "$browser": "StartBrowser"},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # The breakdown is attributed from the start event, not the exposure.
        self.assertEqual(buckets, {"StartBrowser"})

    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_limit_collapses_to_other(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_retention_metric(breakdown_limit=2)
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Four browsers with descending start-event user counts; limit=2 keeps the top two.
        browser_counts = {"Chrome": 4, "Safari": 3, "Firefox": 2, "Edge": 1}
        user_index = 0
        for browser, count in browser_counts.items():
            for _ in range(count):
                variant = "control" if user_index % 2 == 0 else "test"
                distinct_id = f"user_ret_{user_index}"
                user_index += 1
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
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, "$browser": browser},
                )
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=distinct_id,
                    timestamp="2020-01-03T12:01:00Z",
                    properties={feature_flag_property: variant, "$browser": browser},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        self.assertEqual(buckets, {"Chrome", "Safari", BREAKDOWN_OTHER_STRING_LABEL})

        ordered_values = [value for br in result.breakdown_results for value in br.breakdown_value]
        self.assertEqual(ordered_values[-1], BREAKDOWN_OTHER_STRING_LABEL)

    @parameterized.expand(
        [
            ("two_breakdowns", ["$browser", "$os"], 2),
            ("three_breakdowns", ["$browser", "$os", "$device_type"], 3),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_with_multiple_breakdowns(self, _name, breakdown_properties, expected_tuple_len):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property=p) for p in breakdown_properties]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        combos = [
            {"$browser": "Chrome", "$os": "Windows", "$device_type": "Desktop"},
            {"$browser": "Safari", "$os": "Mac", "$device_type": "Mobile"},
        ]
        for variant in ["control", "test"]:
            for idx, combo in enumerate(combos):
                distinct_id = f"user_ret_multi_{variant}_{idx}"
                start_props = {k: v for k, v in combo.items() if k in breakdown_properties}
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
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, **start_props},
                )
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=distinct_id,
                    timestamp="2020-01-03T12:01:00Z",
                    properties={feature_flag_property: variant},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        for breakdown_result in result.breakdown_results:
            self.assertEqual(len(breakdown_result.breakdown_value), expected_tuple_len)

        breakdown_values = [tuple(br.breakdown_value) for br in result.breakdown_results]
        expected_chrome = tuple(combos[0][p] for p in breakdown_properties)
        expected_safari = tuple(combos[1][p] for p in breakdown_properties)
        self.assertIn(expected_chrome, breakdown_values)
        self.assertIn(expected_safari, breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_null_values(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_retention_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two users per variant: one with $browser on the start event, one without.
        for variant in ["control", "test"]:
            for idx, has_browser in enumerate([True, False]):
                distinct_id = f"user_ret_null_{variant}_{idx}"
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
                start_props: dict = {feature_flag_property: variant}
                if has_browser:
                    start_props["$browser"] = "Chrome"
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties=start_props,
                )
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=distinct_id,
                    timestamp="2020-01-03T12:01:00Z",
                    properties={feature_flag_property: variant},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["Chrome"], breakdown_values)
        self.assertIn([BREAKDOWN_NULL_STRING_LABEL], breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_person_property(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="country", type="person")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two users per variant; person property carries country (no event-level country).
        country_by_variant = {"control": "US", "test": "UK"}
        for variant, country in country_by_variant.items():
            for i in range(2):
                distinct_id = f"user_ret_person_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk, properties={"country": country})
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
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=distinct_id,
                    timestamp="2020-01-03T12:01:00Z",
                    properties={feature_flag_property: variant},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["US"], breakdown_values)
        self.assertIn(["UK"], breakdown_values)

        us_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["US"]), None)
        self.assertIsNotNone(us_breakdown)
        assert us_breakdown is not None
        self.assertEqual(us_breakdown.baseline.number_of_samples, 2)

        uk_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["UK"]), None)
        self.assertIsNotNone(uk_breakdown)
        assert uk_breakdown is not None
        self.assertEqual(len(uk_breakdown.variants), 1)
        self.assertEqual(uk_breakdown.variants[0].number_of_samples, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_retention_breakdown_non_retained_users(self):
        # Non-retained users (no login event) must still appear in their start-event browser bucket.
        # This verifies the denominator is preserved: attributing from the start event ensures
        # every cohort member has a breakdown value, so per-bucket samples sum to overall samples.
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_retention_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Seed per variant: 2 Chrome users (1 retained, 1 not) + 2 Safari users (both retained).
        # Total cohort per variant = 4; Chrome bucket = 2, Safari bucket = 2.
        for variant in ["control", "test"]:
            for i in range(4):
                browser = "Chrome" if i < 2 else "Safari"
                distinct_id = f"user_ret_nonret_{variant}_{i}"
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
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, "$browser": browser},
                )
                # user index 1 (second Chrome user) has no login — non-retained.
                if i != 1:
                    _create_event(
                        team=self.team,
                        event="login",
                        distinct_id=distinct_id,
                        timestamp="2020-01-03T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Query must succeed.
        assert result.breakdown_results is not None

        # Both browser buckets must be present — the non-retained Chrome user is still in
        # the cohort and must appear in the Chrome bucket.
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["Chrome"], breakdown_values)
        self.assertIn(["Safari"], breakdown_values)

        # Per-breakdown baseline samples must sum to the overall baseline — start-event
        # attribution keeps the denominator intact across all buckets.
        assert result.baseline is not None
        per_breakdown_baseline = sum(
            br.baseline.number_of_samples for br in result.breakdown_results if br.baseline is not None
        )
        self.assertEqual(per_breakdown_baseline, result.baseline.number_of_samples)

    def _create_ratio_metric(self, breakdown_limit=None):
        return ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(
                breakdowns=[Breakdown(property="$browser")], breakdown_limit=breakdown_limit
            ),
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_from_numerator_event(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_ratio_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Exposure carries "ExposureBrowser"; the numerator (purchase) event carries "NumeratorBrowser".
        for variant in ["control", "test"]:
            distinct_id = f"user_{variant}"
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
                    "$browser": "ExposureBrowser",
                },
            )
            _create_event(
                team=self.team,
                event="view_item",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant, "$browser": "DenominatorBrowser"},
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:02:00Z",
                properties={feature_flag_property: variant, "$browser": "NumeratorBrowser", "amount": 10},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        # The breakdown is attributed from the numerator event, not the exposure or denominator.
        self.assertEqual(buckets, {"NumeratorBrowser"})

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_limit_collapses_to_other(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_ratio_metric(breakdown_limit=2)
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Four browsers with descending numerator-event user counts; limit=2 keeps the top two.
        browser_counts = {"Chrome": 4, "Safari": 3, "Firefox": 2, "Edge": 1}
        user_index = 0
        for browser, count in browser_counts.items():
            for _ in range(count):
                variant = "control" if user_index % 2 == 0 else "test"
                distinct_id = f"user_ratio_{user_index}"
                user_index += 1
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
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant, "$browser": browser},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: variant, "$browser": browser, "amount": 10},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        self.assertEqual(buckets, {"Chrome", "Safari", BREAKDOWN_OTHER_STRING_LABEL})

        ordered_values = [value for br in result.breakdown_results for value in br.breakdown_value]
        self.assertEqual(ordered_values[-1], BREAKDOWN_OTHER_STRING_LABEL)

    @parameterized.expand(
        [
            ("two_breakdowns", ["$browser", "$os"], 2),
            ("three_breakdowns", ["$browser", "$os", "$device_type"], 3),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_with_multiple_breakdowns(self, _name, breakdown_properties, expected_tuple_len):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property=p) for p in breakdown_properties]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        combos = [
            {"$browser": "Chrome", "$os": "Windows", "$device_type": "Desktop"},
            {"$browser": "Safari", "$os": "Mac", "$device_type": "Mobile"},
        ]
        for variant in ["control", "test"]:
            for idx, combo in enumerate(combos):
                distinct_id = f"user_ratio_multi_{variant}_{idx}"
                purchase_props = {k: v for k, v in combo.items() if k in breakdown_properties}
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
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: variant, "amount": 10, **purchase_props},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        for breakdown_result in result.breakdown_results:
            self.assertEqual(len(breakdown_result.breakdown_value), expected_tuple_len)

        breakdown_values = [tuple(br.breakdown_value) for br in result.breakdown_results]
        expected_chrome = tuple(combos[0][p] for p in breakdown_properties)
        expected_safari = tuple(combos[1][p] for p in breakdown_properties)
        self.assertIn(expected_chrome, breakdown_values)
        self.assertIn(expected_safari, breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_null_values(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_ratio_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two users per variant: one with $browser on the purchase (numerator) event, one without.
        for variant in ["control", "test"]:
            for idx, has_browser in enumerate([True, False]):
                distinct_id = f"user_ratio_null_{variant}_{idx}"
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
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                purchase_props: dict = {feature_flag_property: variant, "amount": 10}
                if has_browser:
                    purchase_props["$browser"] = "Chrome"
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:02:00Z",
                    properties=purchase_props,
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["Chrome"], breakdown_values)
        self.assertIn([BREAKDOWN_NULL_STRING_LABEL], breakdown_values)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_person_property(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="country", type="person")]),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        country_by_variant = {"control": "US", "test": "UK"}
        for variant, country in country_by_variant.items():
            for i in range(2):
                distinct_id = f"user_ratio_person_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk, properties={"country": country})
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
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: variant, "amount": 10},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        self.assertIn(["US"], breakdown_values)
        self.assertIn(["UK"], breakdown_values)

        us_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["US"]), None)
        self.assertIsNotNone(us_breakdown)
        assert us_breakdown is not None
        self.assertEqual(us_breakdown.baseline.number_of_samples, 2)

        uk_breakdown = next((br for br in result.breakdown_results if br.breakdown_value == ["UK"]), None)
        self.assertIsNotNone(uk_breakdown)
        assert uk_breakdown is not None
        self.assertEqual(len(uk_breakdown.variants), 1)
        self.assertEqual(uk_breakdown.variants[0].number_of_samples, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_with_winsorization(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
            numerator_outlier_handling=ExperimentMetricOutlierHandling(upper_bound_percentile=0.95),
        )
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Two browsers on the numerator (purchase) event side — breakdown bucket comes from there.
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            variant = "control" if i % 2 == 0 else "test"
            distinct_id = f"user_ratio_winsor_{i}"
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
            _create_event(
                team=self.team,
                event="view_item",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant},
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:02:00Z",
                properties={
                    feature_flag_property: variant,
                    "$browser": browser,
                    "amount": 10 + i * 5,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Winsorized ratio path must run without error and buckets must come from the numerator event.
        assert result.breakdown_results is not None
        buckets = {value for br in result.breakdown_results for value in br.breakdown_value}
        self.assertEqual(buckets, {"Chrome", "Safari"})
        for breakdown_result in result.breakdown_results:
            self.assertIsNotNone(breakdown_result.baseline)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_ratio_breakdown_denominator_only_user(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = self._create_ratio_metric()
        experiment_query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Normal user: has both denominator (view_item) and numerator (purchase) events.
        for variant in ["control", "test"]:
            distinct_id = f"user_ratio_normal_{variant}"
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
            _create_event(
                team=self.team,
                event="view_item",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant},
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:02:00Z",
                properties={feature_flag_property: variant, "$browser": "Chrome", "amount": 10},
            )

        # Denominator-only user: has a view_item but NO purchase — no numerator event to attribute from.
        # Their breakdown is null/absent; they contribute to denominator sum but not a named browser bucket.
        for variant in ["control", "test"]:
            distinct_id = f"user_ratio_denom_only_{variant}"
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
            _create_event(
                team=self.team,
                event="view_item",
                distinct_id=distinct_id,
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: variant},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Query must run without error.
        assert result.breakdown_results is not None
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        # The normal user's Chrome bucket must be present.
        self.assertIn(["Chrome"], breakdown_values)
