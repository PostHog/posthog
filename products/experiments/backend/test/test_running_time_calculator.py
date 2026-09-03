import math
from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.experiments.backend.running_time_calculator import (
    BaselineStats,
    RunningTimeEstimate,
    baseline_stats_from_result_blob,
    calculate_baseline_value,
    calculate_recommended_sample_size,
    calculate_running_time_days,
    calculate_sample_size,
    calculate_variance,
    calculate_variance_from_stats,
    estimate_running_time_for_experiment,
    resolve_minimum_detectable_effect,
    select_sizing_metric,
)


class TestCalculateBaselineValue:
    @parameterized.expand(
        [
            # mean total count: avg events per user = sum / samples
            ("mean_count", BaselineStats(number_of_samples=14000, sum=56000, step_counts=[]), 4),
            # mean sum: avg property value per user
            ("mean_sum_or_avg", BaselineStats(number_of_samples=14000, sum=700000, step_counts=[]), 50),
            # funnel: conversion rate = final step / samples
            ("funnel", BaselineStats(number_of_samples=1000, sum=100, step_counts=[1000, 100]), 0.1),
        ]
    )
    def test_baseline_value(self, metric_type, baseline, expected):
        assert calculate_baseline_value(baseline, metric_type) == expected

    def test_funnel_falls_back_to_sum_when_no_step_counts(self):
        baseline = BaselineStats(number_of_samples=1000, sum=100, step_counts=[])
        assert calculate_baseline_value(baseline, "funnel") == 0.1

    def test_ratio_uses_denominator_sum(self):
        baseline = BaselineStats(number_of_samples=10000, sum=500000, denominator_sum=50000)
        assert calculate_baseline_value(baseline, "ratio") == 10

    def test_returns_none_when_no_samples(self):
        baseline = BaselineStats(number_of_samples=0, sum=100)
        assert calculate_baseline_value(baseline, "mean_count") is None

    def test_ratio_returns_none_when_denominator_zero(self):
        baseline = BaselineStats(number_of_samples=1000, sum=100, denominator_sum=0)
        assert calculate_baseline_value(baseline, "ratio") is None


class TestCalculateVariance:
    @parameterized.expand(
        [
            ("mean_count", 4, 8),  # 2 * 4
            ("mean_sum_or_avg", 50, 625),  # 0.25 * 50^2
            ("funnel", 0.1, None),  # embedded in p(1-p)
        ]
    )
    def test_variance_from_baseline_value(self, metric_type, baseline_value, expected):
        assert calculate_variance(metric_type, baseline_value) == expected


class TestCalculateVarianceFromStats:
    def test_ratio_delta_method(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=500000,
            sum_squares=30000000,
            denominator_sum=50000,
            denominator_sum_squares=300000,
            numerator_denominator_sum_product=2600000,
        )
        variance = calculate_variance_from_stats(10, "ratio", baseline)
        assert variance is not None
        assert math.isclose(variance, 32, rel_tol=1e-6)

    def test_ratio_zero_covariance(self):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=5000,
            sum_squares=30000,
            denominator_sum=10000,
            denominator_sum_squares=105000,
            numerator_denominator_sum_product=50000,
        )
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None
        assert math.isclose(variance, 0.0625, rel_tol=1e-6)

    def test_ratio_high_positive_covariance_reduces_variance(self):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=5000,
            sum_squares=30000,
            denominator_sum=10000,
            denominator_sum_squares=105000,
            numerator_denominator_sum_product=52000,
        )
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None
        assert variance < 0.0625

    def test_retention_delta_method(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=7000,
            sum_squares=7000,
            denominator_sum=10000,
            denominator_sum_squares=10000,
            numerator_denominator_sum_product=7000,
        )
        variance = calculate_variance_from_stats(0.7, "retention", baseline)
        assert variance is not None
        assert math.isclose(variance, 0.21, rel_tol=1e-6)

    @parameterized.expand(
        [
            ("zero_retention", 0, 0, 0, 0),
            ("perfect_retention", 1000, 1000, 1000, 1000),
        ]
    )
    def test_retention_edge_cases_have_zero_variance(self, _name, sum_, sum_squares, product, _denom_unused):
        baseline = BaselineStats(
            number_of_samples=1000,
            sum=sum_,
            sum_squares=sum_squares,
            denominator_sum=1000,
            denominator_sum_squares=1000,
            numerator_denominator_sum_product=product,
        )
        baseline_value = calculate_baseline_value(baseline, "retention")
        assert baseline_value is not None
        variance = calculate_variance_from_stats(baseline_value, "retention", baseline)
        assert variance is not None
        assert math.isclose(variance, 0, abs_tol=1e-9)

    def test_returns_none_without_baseline(self):
        assert calculate_variance_from_stats(0.05, "ratio", None) is None

    def test_returns_none_when_samples_zero(self):
        baseline = BaselineStats(number_of_samples=0, sum=100, denominator_sum=1000)
        assert calculate_variance_from_stats(10, "ratio", baseline) is None

    def test_handles_missing_optional_fields(self):
        baseline = BaselineStats(number_of_samples=1000, sum=5000, sum_squares=30000, denominator_sum=10000)
        variance = calculate_variance_from_stats(0.5, "ratio", baseline)
        assert variance is not None


class TestCalculateSampleSize:
    @parameterized.expand(
        [
            # metric_type, baseline_value, mde, variants, expected
            ("mean_count", 4, 5, 2, 6400),
            ("mean_sum_or_avg", 50, 5, 2, 3200),
            ("funnel", 0.1, 50, 2, 1152),
        ]
    )
    def test_sample_size(self, metric_type, baseline_value, mde, variants, expected):
        assert calculate_sample_size(metric_type, baseline_value, mde, variants) == expected

    def test_returns_none_for_zero_mde(self):
        assert calculate_sample_size("funnel", 0.1, 0, 2) is None

    def test_returns_none_for_zero_baseline(self):
        assert calculate_sample_size("mean_count", 0, 5, 2) is None

    def test_ratio_requires_variance(self):
        assert calculate_sample_size("ratio", 10, 10, 2) is None
        assert calculate_sample_size("ratio", 10, 10, 2, variance=32) == 1024

    def test_returns_none_for_funnel_baseline_above_one(self):
        # A conversion rate above 1 flips the (1 - p) term negative, so the sample size is negative.
        assert calculate_sample_size("funnel", 1.5, 50, 2) is None

    def test_returns_none_for_negative_variance(self):
        # The delta method can return a negative variance, which yields a negative sample size.
        assert calculate_sample_size("ratio", 10, 10, 2, variance=-32) is None


class TestCalculateRecommendedSampleSize:
    @parameterized.expand(
        [
            ("mean_count", 4, 5, 2, None, 6400),
            ("mean_sum_or_avg", 50, 5, 2, None, 3200),
            ("funnel", 0.1, 50, 2, None, 1152),
        ]
    )
    def test_simple_metrics(self, metric_type, baseline_value, mde, variants, baseline, expected):
        assert calculate_recommended_sample_size(metric_type, mde, baseline_value, variants, baseline) == expected

    def test_ratio(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=500000,
            sum_squares=30000000,
            denominator_sum=50000,
            denominator_sum_squares=300000,
            numerator_denominator_sum_product=2600000,
        )
        assert calculate_recommended_sample_size("ratio", 10, 10, 2, baseline) == 1024

    def test_retention(self):
        baseline = BaselineStats(
            number_of_samples=10000,
            sum=7000,
            sum_squares=7000,
            denominator_sum=10000,
            denominator_sum_squares=10000,
            numerator_denominator_sum_product=7000,
        )
        assert calculate_recommended_sample_size("retention", 10, 0.7, 2, baseline) == 1372


class TestCalculateRunningTimeDays:
    @parameterized.expand(
        [
            (6400, 100, 64),
            (1000, 300, 4),  # ceil(3.33)
            (None, 100, None),
            (6400, 0, None),
            (6400, None, None),
        ]
    )
    def test_running_time(self, sample_size, exposure_rate, expected):
        assert calculate_running_time_days(sample_size, exposure_rate) == expected


class TestBaselineStatsFromResultBlob:
    def test_maps_funnel_blob_including_step_counts(self):
        blob = {
            "baseline": {
                "key": "control",
                "number_of_samples": 12500,
                "sum": 3120.0,
                "sum_squares": 3120.0,
                "step_counts": [12500, 8400, 3120],
            }
        }
        stats = baseline_stats_from_result_blob(blob)
        assert stats == BaselineStats(
            number_of_samples=12500,
            sum=3120.0,
            sum_squares=3120.0,
            step_counts=[12500, 8400, 3120],
        )

    def test_maps_ratio_blob_including_denominator_stats(self):
        blob = {
            "baseline": {
                "key": "control",
                "number_of_samples": 10000,
                "sum": 500000.0,
                "sum_squares": 30000000.0,
                "denominator_sum": 50000.0,
                "denominator_sum_squares": 300000.0,
                "numerator_denominator_sum_product": 2600000.0,
            }
        }
        stats = baseline_stats_from_result_blob(blob)
        assert stats is not None
        assert stats.denominator_sum == 50000.0
        assert stats.denominator_sum_squares == 300000.0
        assert stats.numerator_denominator_sum_product == 2600000.0

    def test_absent_optional_fields_become_unset(self):
        blob = {"baseline": {"key": "control", "number_of_samples": 9800, "sum": 4567.5, "sum_squares": 8912.75}}
        stats = baseline_stats_from_result_blob(blob)
        assert stats is not None
        assert stats.denominator_sum is None
        assert stats.step_counts == []

    @parameterized.expand(
        [
            ("no_baseline_key", {}),
            ("null_baseline", {"baseline": None}),
            ("baseline_not_dict", {"baseline": []}),
            ("missing_number_of_samples", {"baseline": {"sum": 100.0}}),
        ]
    )
    def test_returns_none_for_unusable_blob(self, _name, blob):
        assert baseline_stats_from_result_blob(blob) is None


class TestSelectSizingMetric:
    def _funnel(self, uuid="f"):
        return {"kind": "ExperimentMetric", "metric_type": "funnel", "uuid": uuid, "series": []}

    def _mean(self, uuid="m", math="total"):
        return {"kind": "ExperimentMetric", "metric_type": "mean", "uuid": uuid, "source": {"math": math}}

    def _ratio(self, uuid="r"):
        return {"kind": "ExperimentMetric", "metric_type": "ratio", "uuid": uuid}

    def _retention(self, uuid="ret"):
        return {"kind": "ExperimentMetric", "metric_type": "retention", "uuid": uuid}

    @parameterized.expand(
        [
            ("funnel", "funnel", None, "funnel"),
            ("ratio", "ratio", None, "ratio"),
            ("retention", "retention", None, "retention"),
            ("mean_count_total", "mean", "total", "mean_count"),
            ("mean_count_avg", "mean", "avg", "mean_count"),
            ("mean_sum", "mean", "sum", "mean_sum_or_avg"),
        ]
    )
    def test_classifies_single_metric(self, _name, metric_type, math, expected_calc_type):
        metric = {"kind": "ExperimentMetric", "metric_type": metric_type, "uuid": "u", "source": {"math": math}}
        result = select_sizing_metric([metric], None)
        assert result is not None
        selected, calc_type = result
        assert selected["uuid"] == "u"
        assert calc_type == expected_calc_type

    def test_picks_first_by_display_order_not_list_order(self):
        metrics = [self._mean(uuid="second", math="sum"), self._funnel(uuid="first")]
        result = select_sizing_metric(metrics, ["first", "second"])
        assert result is not None
        selected, calc_type = result
        assert selected["uuid"] == "first"
        assert calc_type == "funnel"

    def test_falls_back_to_list_order_when_no_ordering(self):
        metrics = [self._ratio(uuid="a"), self._funnel(uuid="b")]
        result = select_sizing_metric(metrics, None)
        assert result is not None
        selected, _ = result
        assert selected["uuid"] == "a"

    @parameterized.expand([("empty", []), ("none", None)])
    def test_returns_none_without_metrics(self, _name, metrics):
        assert select_sizing_metric(metrics, None) is None

    def test_returns_none_for_unknown_metric_type(self):
        metrics = [{"kind": "ExperimentMetric", "metric_type": "bogus", "uuid": "x"}]
        assert select_sizing_metric(metrics, None) is None


class TestResolveMinimumDetectableEffect:
    @parameterized.expand(
        [
            ("saved_wins", 5, 20, 5),
            ("team_default_when_no_saved", None, 20, 20),
            ("fallback_when_neither", None, None, 30),
            ("saved_zero_is_ignored", 0, 20, 20),
            ("team_zero_is_ignored", None, 0, 30),
        ]
    )
    def test_resolution_chain(self, _name, saved, team_default, expected):
        assert resolve_minimum_detectable_effect(saved, team_default) == expected


class TestEstimateRunningTimeForExperiment:
    NOW = datetime(2026, 8, 27, tzinfo=UTC)

    def _funnel_metric(self):
        return {"kind": "ExperimentMetric", "metric_type": "funnel", "uuid": "f", "series": []}

    def _funnel_blob(self, samples=600):
        # 10% conversion baseline: final step is 10% of exposed control users.
        return {
            "baseline": {
                "key": "control",
                "number_of_samples": samples,
                "sum": samples // 10,
                "step_counts": [samples, samples // 10],
            }
        }

    def _manual_config(self):
        return {
            "minimum_detectable_effect": 50,
            "exposure_estimate_config": {
                "conversionRateInputType": "manual",
                "manualMetricType": "funnel",
                "manualBaselineValue": 10,
                "manualExposureRate": 100,
            },
        }

    def test_manual_mode_uses_live_exposures_like_detail_page(self):
        # Manual uses the fixed rate but live exposures, matching the detail page:
        # target 1152, 300 exposed so far, 100/day -> (1152-300)/100 = 8.52 -> 9.
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation=self._manual_config(),
            start_date=self.NOW - timedelta(days=4),
            number_of_variants=2,
            result_blob=self._funnel_blob(samples=300),
            now=self.NOW,
        )
        assert estimate.target_sample_size == 1152
        assert estimate.current_exposures == 300
        assert estimate.remaining_days == 9

    def test_manual_mode_too_little_data_shows_total(self):
        # <100 exposures -> fall back to total from the fixed rate: 1152/100 = 12.
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation=self._manual_config(),
            start_date=self.NOW - timedelta(hours=6),
            number_of_variants=2,
            result_blob=self._funnel_blob(samples=20),
            now=self.NOW,
        )
        assert estimate.remaining_days == 12

    def test_manual_mode_without_results_shows_total(self):
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation=self._manual_config(),
            start_date=self.NOW - timedelta(days=4),
            number_of_variants=2,
            result_blob=None,
            now=self.NOW,
        )
        assert estimate.current_exposures is None
        assert estimate.remaining_days == 12

    def test_manual_mode_target_reached_is_zero(self):
        blob = {
            "baseline": {"key": "control", "number_of_samples": 1000, "sum": 100, "step_counts": [1000, 100]},
            "variant_results": [{"key": "test", "number_of_samples": 1000, "sum": 110}],
        }
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation=self._manual_config(),
            start_date=self.NOW - timedelta(days=20),
            number_of_variants=2,
            result_blob=blob,  # 2000 exposed > 1152 target
            now=self.NOW,
        )
        assert estimate.current_exposures == 2000
        assert estimate.remaining_days == 0

    def test_automatic_mode_with_enough_data_subtracts_current_exposures(self):
        # 10 days elapsed, 2000 exposures so far -> 200/day. Target 1152, remaining 1152-2000<0 -> complete.
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation={
                "minimum_detectable_effect": 50,
                "exposure_estimate_config": {"conversionRateInputType": "automatic"},
            },
            start_date=self.NOW - timedelta(days=10),
            number_of_variants=2,
            result_blob={
                "baseline": {"key": "control", "number_of_samples": 1000, "sum": 100, "step_counts": [1000, 100]},
                "variant_results": [{"key": "test", "number_of_samples": 1000, "sum": 110}],
            },
            now=self.NOW,
        )
        assert estimate.target_sample_size == 1152
        assert estimate.current_exposures == 2000
        assert estimate.remaining_days == 0

    def test_automatic_mode_too_little_data_shows_total_time(self):
        # <1 day elapsed and <100 exposures -> fall back to ceil(target/rate) using rate from exposures/day.
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation={
                "minimum_detectable_effect": 50,
                "exposure_estimate_config": {"conversionRateInputType": "automatic"},
            },
            start_date=self.NOW - timedelta(hours=12),
            number_of_variants=2,
            result_blob=self._funnel_blob(samples=40),
            now=self.NOW,
        )
        assert estimate.target_sample_size == 1152
        assert estimate.current_exposures == 40
        # rate = 40 exposures / 0.5 days = 80/day; ceil(1152/80) = 15
        assert estimate.remaining_days == 15

    def test_automatic_mode_without_saved_mde_is_all_null(self):
        # Guards the reported bug: an experiment with no saved MDE must not silently size to null.
        # The service is responsible for passing a fallback via mde_override (see resolve_minimum_detectable_effect).
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation={"exposure_estimate_config": {"conversionRateInputType": "automatic"}},
            start_date=self.NOW - timedelta(days=10),
            number_of_variants=2,
            result_blob=self._funnel_blob(samples=1000),
            now=self.NOW,
        )
        assert estimate.target_sample_size is None

    def test_automatic_mode_with_mde_override_when_no_saved_mde(self):
        estimate = estimate_running_time_for_experiment(
            metrics=[self._funnel_metric()],
            primary_metrics_ordered_uuids=None,
            running_time_calculation={"exposure_estimate_config": {"conversionRateInputType": "automatic"}},
            start_date=self.NOW - timedelta(days=10),
            number_of_variants=2,
            result_blob=self._funnel_blob(samples=1000),
            now=self.NOW,
            mde_override=30,
        )
        assert estimate.target_sample_size is not None
        assert estimate.current_exposures == 1000

    def test_automatic_mode_without_usable_metric_returns_empty(self):
        estimate = estimate_running_time_for_experiment(
            metrics=[],
            primary_metrics_ordered_uuids=None,
            running_time_calculation={"exposure_estimate_config": {"conversionRateInputType": "automatic"}},
            start_date=self.NOW - timedelta(days=10),
            number_of_variants=2,
            result_blob=None,
            now=self.NOW,
        )
        assert estimate == RunningTimeEstimate(target_sample_size=None, current_exposures=None, remaining_days=None)

    def test_mde_override_beats_saved_value(self):
        base_kwargs = {
            "metrics": [self._funnel_metric()],
            "primary_metrics_ordered_uuids": None,
            "running_time_calculation": {
                "minimum_detectable_effect": 50,
                "exposure_estimate_config": {"conversionRateInputType": "automatic"},
            },
            "start_date": self.NOW - timedelta(days=10),
            "number_of_variants": 2,
            "result_blob": self._funnel_blob(samples=1000),
            "now": self.NOW,
        }
        saved = estimate_running_time_for_experiment(**base_kwargs)
        overridden = estimate_running_time_for_experiment(**{**base_kwargs, "mde_override": 25})
        assert overridden.target_sample_size is not None
        assert saved.target_sample_size is not None
        # Smaller MDE needs a larger sample; a 25% MDE roughly quadruples the 50% target.
        assert overridden.target_sample_size > saved.target_sample_size
