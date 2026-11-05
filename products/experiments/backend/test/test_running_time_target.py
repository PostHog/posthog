import math
from typing import Any

import pytest

from parameterized import parameterized

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQueryResponse, ExperimentRatioMetric

from products.experiments.backend.metric_resolution import ExperimentMetric
from products.experiments.backend.running_time_target import project_outlook, size_target
from products.feature_flags.backend.facade.edits import FlagVariant

REVENUE = ExperimentMeanMetric.model_validate(
    {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "purchase"}}
)
CHECKOUT = ExperimentFunnelMetric.model_validate(
    {"kind": "ExperimentMetric", "metric_type": "funnel", "series": [{"kind": "EventsNode", "event": "purchase"}]}
)
REVENUE_PER_ORDER = ExperimentRatioMetric.model_validate(
    {
        "kind": "ExperimentMetric",
        "metric_type": "ratio",
        "numerator": {"kind": "EventsNode", "event": "purchase", "math": "sum", "math_property": "amount"},
        "denominator": {"kind": "EventsNode", "event": "purchase"},
    }
)
# A mean of 1 with a variance of about 25, so the spread of a revenue metric rather than of a count.
SPREAD = {"number_of_samples": 1000, "sum": 1000, "sum_squares": 26000}
# A covariate with the metric's own spread and a correlation of 0.5, so CUPED keeps 75% of the variance.
COVARIATE = {"covariate_sum": 1000, "covariate_sum_squares": 26000, "covariate_sum_product": 13500}
CONVERSIONS = {"number_of_samples": 1000, "sum": 100, "sum_squares": 100}
# A ratio of 10 with a delta-method variance of about 32.
ORDERS = {
    "number_of_samples": 10000,
    "sum": 500000,
    "sum_squares": 30000000,
    "denominator_sum": 50000,
    "denominator_sum_squares": 300000,
    "numerator_denominator_sum_product": 2600000,
}
EVEN = (("control", 50), ("test", 50))


def _response(
    *variants: tuple[str, dict[str, Any]], control: dict[str, Any] = SPREAD, control_key: str = "control"
) -> ExperimentQueryResponse:
    return ExperimentQueryResponse.model_validate(
        {
            "baseline": {"key": control_key, **control},
            "variant_results": [{"key": key, "method": "bayesian", **stats} for key, stats in variants],
        }
    )


def _split(*percentages: tuple[str, float | None]) -> tuple[FlagVariant, ...]:
    return tuple(FlagVariant(key=key, rollout_percentage=percentage) for key, percentage in percentages)


class TestSizeTarget:
    @parameterized.expand(
        [
            ("observed_variance", REVENUE, _response(("test", SPREAD)), _split(*EVEN), 8898),
            (
                "variant_with_a_wider_spread",
                REVENUE,
                _response(("test", {**SPREAD, "sum_squares": 51000})),
                _split(*EVEN),
                13347,
            ),
            ("uneven_split", REVENUE, _response(("test", SPREAD)), _split(("control", 80), ("test", 20)), 13903),
            (
                "smallest_of_three_variants_with_the_control_listed_second",
                REVENUE,
                _response(("a", SPREAD), ("b", SPREAD), control_key="original"),
                _split(("b", 10), ("original", 60), ("a", 30)),
                25952,
            ),
            (
                "variant_at_zero_percent_left_out",
                REVENUE,
                _response(("test", SPREAD), ("paused", {"number_of_samples": 0, "sum": 0, "sum_squares": 0})),
                _split(*EVEN, ("paused", 0)),
                8898,
            ),
            (
                "excluded_variant_with_traffic_left_out",
                REVENUE,
                _response(("test", SPREAD)),
                _split(("control", 34), ("test", 33), ("excluded", 33)),
                8900,
            ),
            (
                "unreadable_percentages_as_an_even_split",
                REVENUE,
                _response(("test", SPREAD)),
                _split(("control", None), ("test", 20)),
                8898,
            ),
            (
                "cuped_variance",
                REVENUE,
                _response(("test", {**SPREAD, **COVARIATE}), control={**SPREAD, **COVARIATE}),
                _split(*EVEN),
                6674,
            ),
            (
                "cuped_variance_on_an_uneven_split",
                REVENUE,
                _response(
                    (
                        "test",
                        {
                            "number_of_samples": 400,
                            "sum": 480,
                            "sum_squares": 14940,
                            "covariate_sum": 480,
                            "covariate_sum_squares": 14940,
                            "covariate_sum_product": 12067.2,
                        },
                    ),
                    control={
                        "number_of_samples": 1600,
                        "sum": 1600,
                        "sum_squares": 41575,
                        "covariate_sum": 1600,
                        "covariate_sum_squares": 41575,
                        "covariate_sum_product": 21587.5,
                    },
                ),
                _split(("control", 80), ("test", 20)),
                8640,
            ),
            (
                "funnel_conversion_rate",
                CHECKOUT,
                _response(("test", CONVERSIONS), control=CONVERSIONS),
                _split(*EVEN),
                3200,
            ),
            (
                "ratio_delta_method",
                REVENUE_PER_ORDER,
                _response(("test", ORDERS), control=ORDERS),
                _split(*EVEN),
                114,
            ),
            (
                "stats_that_do_not_fit_together",
                REVENUE,
                _response(("test", SPREAD), control={**SPREAD, "sum_squares": 0}),
                _split(*EVEN),
                None,
            ),
        ]
    )
    def test_sizes_each_comparison_with_the_control(
        self,
        _name: str,
        metric: ExperimentMetric,
        response: ExperimentQueryResponse,
        split: tuple[FlagVariant, ...],
        expected: int | None,
    ) -> None:
        assert size_target(metric=metric, response=response, split=split, minimum_detectable_effect=30) == expected

    @parameterized.expand(
        [
            ("total", {}),
            ("sum", {"math": "sum", "math_property": "amount"}),
            ("avg", {"math": "avg", "math_property": "amount"}),
            ("hogql", {"math": "hogql", "math_hogql": "sum(toFloat(properties.amount))"}),
            ("unique_session", {"math": "unique_session"}),
            ("dau", {"math": "dau"}),
        ]
    )
    def test_sizes_every_mean_math_from_its_spread(self, _name: str, math: dict[str, str]) -> None:
        metric = ExperimentMeanMetric.model_validate(
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "purchase", **math},
            }
        )

        assert (
            size_target(
                metric=metric, response=_response(("test", SPREAD)), split=_split(*EVEN), minimum_detectable_effect=30
            )
            == 8898
        )

    @parameterized.expand([("90_percent", 0.9, 7009), ("95_percent", 0.95, 8898), ("99_percent", 0.99, 13240)])
    def test_sizes_at_the_analysis_confidence_level(self, _name: str, confidence_level: float, expected: int) -> None:
        assert (
            size_target(
                metric=REVENUE,
                response=_response(("test", SPREAD)),
                split=_split(*EVEN),
                minimum_detectable_effect=30,
                confidence_level=confidence_level,
            )
            == expected
        )

    @parameterized.expand([("underflows", 1e-160), ("overflows", 1e160)])
    def test_an_effect_too_extreme_to_compute_gives_no_target(self, _name: str, effect: float) -> None:
        assert (
            size_target(
                metric=REVENUE,
                response=_response(("test", SPREAD)),
                split=_split(*EVEN),
                minimum_detectable_effect=effect,
            )
            is None
        )

    @parameterized.expand(
        [
            ("mean", REVENUE, _response(("test", SPREAD))),
            ("cuped", REVENUE, _response(("test", {**SPREAD, **COVARIATE}), control={**SPREAD, **COVARIATE})),
            ("funnel", CHECKOUT, _response(("test", CONVERSIONS), control=CONVERSIONS)),
            ("ratio", REVENUE_PER_ORDER, _response(("test", ORDERS), control=ORDERS)),
        ]
    )
    def test_sample_scales_with_the_inverse_square_of_the_effect(
        self, _name: str, metric: ExperimentMetric, response: ExperimentQueryResponse
    ) -> None:
        # The page rescales the target by this rule while the user edits the effect, without asking again.
        split = _split(("control", 80), ("test", 20))
        at_30 = size_target(metric=metric, response=response, split=split, minimum_detectable_effect=30)
        at_15 = size_target(metric=metric, response=response, split=split, minimum_detectable_effect=15)

        assert at_30 is not None and at_15 is not None
        assert at_15 == pytest.approx(4 * at_30, abs=4)


class TestProjectOutlook:
    @parameterized.expand(
        [
            ("first_days", 3, 3, (1, 2, 4)),
            ("past_week_four", 30, 30, (6, 8, 12)),
            # Results that end before today set the rate, and the week marks still start after today.
            ("results_from_before_today", 14.2, 13.9, (4, 6, 8)),
            ("first_two_hours", 0.05, 0.05, None),
        ]
    )
    def test_projects_the_next_week_marks_on_the_target_curve(
        self, _name: str, days_since_launch: float, days_measured: float, weeks: tuple[int, ...] | None
    ) -> None:
        response = _response(("test", SPREAD))
        target = size_target(metric=REVENUE, response=response, split=_split(*EVEN), minimum_detectable_effect=30)
        assert target is not None

        outlook = project_outlook(
            metric=REVENUE,
            response=response,
            split=_split(*EVEN),
            days_since_launch=days_since_launch,
            days_measured=days_measured,
        )

        if weeks is None:
            assert outlook is None
            return
        assert outlook is not None
        rate = 2000 / days_measured

        def on_curve(samples: float) -> Any:
            return pytest.approx(30 * math.sqrt(target / samples), rel=1e-3)

        assert outlook.exposures_per_day == pytest.approx(rate)
        assert outlook.detectable_effect_now == on_curve(2000)
        assert [(c.weeks_since_launch, c.detectable_effect) for c in outlook.upcoming_checkpoints] == [
            (week, on_curve(rate * 7 * week)) for week in weeks
        ]
        assert outlook.reachable_effect == on_curve(2000 + rate * 28)

    @parameterized.expand(
        [
            # A covariance larger than the two spreads allow gives the delta method a negative variance.
            ("negative_ratio_variance", REVENUE_PER_ORDER, {**ORDERS, "numerator_denominator_sum_product": 3100000}),
            ("constant_metric", REVENUE, {"number_of_samples": 1000, "sum": 1000, "sum_squares": 1000}),
        ]
    )
    def test_projects_nothing_from_stats_without_a_spread(
        self, _name: str, metric: ExperimentMetric, stats: dict[str, Any]
    ) -> None:
        response = _response(("test", stats), control=stats)

        assert project_outlook(metric=metric, response=response, split=_split(*EVEN), days_since_launch=10) is None
