from typing import Any

import pytest
from unittest import TestCase

import numpy as np
from parameterized import parameterized

from ..shared.statistics import (
    QUANTILE_N_STAR_GRID,
    InvalidStatisticError,
    ProportionStatistic,
    QuantileBounds,
    QuantileGridLevel,
    QuantileStatistic,
    RatioStatistic,
    SampleMeanStatistic,
    choose_quantile_bounds,
    quantile_grid_levels,
)

# Sufficient statistics of a seeded synthetic dataset: 400 users per arm, Poisson(3) events
# per user (some users have none), lognormal values with a per-user random effect, nu = 0.9.
QUANTILE_CONTROL = QuantileStatistic(
    nu=0.9,
    n=1263,
    n_clusters=400,
    quantile=10.899,
    quantile_lower=10.34,
    quantile_upper=11.633,
    n_star=800,
    s_sum=1137,
    s_sum_squares=4443,
    n_sum=1263,
    n_sum_squares=5193,
    s_n_sum_of_products=4684,
)
QUANTILE_TREATMENT = QuantileStatistic(
    nu=0.9,
    n=1217,
    n_clusters=400,
    quantile=12.314,
    quantile_lower=11.178,
    quantile_upper=13.101,
    n_star=800,
    s_sum=1096,
    s_sum_squares=4138,
    n_sum=1217,
    n_sum_squares=4793,
    s_n_sum_of_products=4330,
)


def _iid_quantile(
    nu: float, n: int, lower: float, upper: float, n_clusters: int | None = None, quantile: float | None = None
) -> QuantileStatistic:
    # One event per user, so the design effect is K / (K - 1).
    k = n if n_clusters is None else n_clusters
    return QuantileStatistic(
        nu=nu,
        n=n,
        n_clusters=k,
        quantile=(lower + upper) / 2 if quantile is None else quantile,
        quantile_lower=lower,
        quantile_upper=upper,
        n_star=max([n_star for n_star in QUANTILE_N_STAR_GRID if n_star <= n], default=QUANTILE_N_STAR_GRID[0]),
        s_sum=nu * n,
        s_sum_squares=nu * n,
        n_sum=n,
        n_sum_squares=n,
        s_n_sum_of_products=nu * n,
    )


# 10 users with 90 events each and 100 users with one event each, so the events come from about 12 effective users.
DOMINANT_USERS_QUANTILE = QuantileStatistic(
    nu=0.9,
    n=1000,
    n_clusters=500,
    quantile=12.0,
    quantile_lower=11.0,
    quantile_upper=13.0,
    n_star=800,
    s_sum=900,
    s_sum_squares=65860,
    n_sum=1000,
    n_sum_squares=81100,
    s_n_sum_of_products=72990,
)

ZERO_VARIANCE_ERROR = "Quantile has zero variance"
TIED_VALUES_ERROR = "Quantile variance is unreliable - too many events tie with the quantile value"
DOMINANT_USERS_ERROR = "Quantile variance is unreliable - a few users produce most of the events"

DEGENERATE_QUANTILE_CASES = [
    (
        "collapsed_bounds",
        _iid_quantile(nu=0.6, n=700, lower=4.0, upper=4.0),
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.1),
        ZERO_VARIANCE_ERROR,
    ),
    (
        "tail_too_small_for_quantile",
        _iid_quantile(nu=0.98, n=150, lower=3.9, upper=4.1),
        _iid_quantile(nu=0.98, n=6_000, lower=3.9, upper=4.1),
        ZERO_VARIANCE_ERROR,
    ),
    (
        "single_cluster",
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.1, n_clusters=1),
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.1),
        ZERO_VARIANCE_ERROR,
    ),
    (
        "quantile_tied_with_lower_bound",
        _iid_quantile(nu=0.6, n=700, lower=4.0, upper=4.1, quantile=4.0),
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.1),
        TIED_VALUES_ERROR,
    ),
    (
        "quantile_tied_with_upper_bound",
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.0, quantile=4.0),
        _iid_quantile(nu=0.6, n=700, lower=3.9, upper=4.1),
        TIED_VALUES_ERROR,
    ),
    (
        "few_effective_users",
        DOMINANT_USERS_QUANTILE,
        _iid_quantile(nu=0.9, n=1000, lower=11.0, upper=13.0),
        DOMINANT_USERS_ERROR,
    ),
]


class TestSampleMeanStatistic:
    """Tests for SampleMeanStatistic."""

    def test_basic_calculations(self):
        """Test basic mean and variance calculations."""
        # Test case: [1, 2, 3, 4, 5]
        stat = SampleMeanStatistic(n=5, sum=15, sum_squares=55)

        assert stat.mean == 3.0
        assert stat.variance == 2.5  # Sample variance
        assert abs(stat.standard_error - np.sqrt(2.5 / 5)) < 1e-10

    def test_single_observation(self):
        """Test with single observation."""
        stat = SampleMeanStatistic(n=1, sum=10, sum_squares=100)

        assert stat.mean == 10.0
        assert stat.variance == 0.0
        assert stat.standard_error == 0.0

    def test_zero_variance(self):
        """Test with all identical values."""
        # All values are 5: [5, 5, 5]
        stat = SampleMeanStatistic(n=3, sum=15, sum_squares=75)

        assert stat.mean == 5.0
        assert stat.variance == 0.0
        assert stat.standard_error == 0.0

    def test_validation_errors(self):
        """Test input validation."""
        # Negative sample size
        with pytest.raises(InvalidStatisticError):
            SampleMeanStatistic(n=-1, sum=10, sum_squares=100)

        # Zero sample size
        with pytest.raises(InvalidStatisticError):
            SampleMeanStatistic(n=0, sum=10, sum_squares=100)

        # Invalid sum_squares (too small)
        with pytest.raises(InvalidStatisticError):
            SampleMeanStatistic(n=5, sum=15, sum_squares=40)  # 40 < 15²/5 = 45


class TestProportionStatistic:
    """Tests for ProportionStatistic."""

    def test_basic_calculations(self):
        """Test basic proportion calculations."""
        stat = ProportionStatistic(n=100, sum=25)

        assert stat.proportion == 0.25
        assert stat.variance == 0.25 * 0.75  # p(1-p)
        assert abs(stat.standard_error - np.sqrt(0.25 * 0.75 / 100)) < 1e-10

    def test_extreme_proportions(self):
        """Test with extreme proportions."""
        # All successes
        stat = ProportionStatistic(n=10, sum=10)
        assert stat.proportion == 1.0
        assert stat.variance == 0.0

        # No successes
        stat = ProportionStatistic(n=10, sum=0)
        assert stat.proportion == 0.0
        assert stat.variance == 0.0

    def test_validation_errors(self):
        """Test input validation."""
        # Negative sample size
        with pytest.raises(InvalidStatisticError):
            ProportionStatistic(n=-1, sum=5)

        # Negative successes
        with pytest.raises(InvalidStatisticError):
            ProportionStatistic(n=10, sum=-1)

        # More successes than trials
        with pytest.raises(InvalidStatisticError):
            ProportionStatistic(n=10, sum=15)


class TestRatioStatistic:
    """Tests for RatioStatistic."""

    def test_basic_calculations(self):
        """Test basic ratio calculations."""
        # Revenue per user: revenue=[10, 20, 30], users=[1, 1, 1]
        numerator = SampleMeanStatistic(n=3, sum=60, sum_squares=1400)  # Revenue
        denominator = SampleMeanStatistic(n=3, sum=3, sum_squares=3)  # Users

        stat = RatioStatistic(
            n=3,
            m_statistic=numerator,
            d_statistic=denominator,
            m_d_sum_of_products=60,  # sum(revenue * users)
        )

        assert stat.ratio == 20.0  # 60 / 3

        # Test covariance calculation
        expected_cov = (60 - 60 * 3 / 3) / (3 - 1)  # Should be 0
        assert abs(stat.covariance - expected_cov) < 1e-10

    def test_with_proportion_denominator(self):
        """Test ratio with proportion denominator (e.g., revenue per conversion)."""
        revenue = SampleMeanStatistic(n=100, sum=500, sum_squares=5000)
        conversions = ProportionStatistic(n=100, sum=20)  # 20% conversion rate

        stat = RatioStatistic(
            n=100,
            m_statistic=revenue,
            d_statistic=conversions,
            m_d_sum_of_products=100,  # sum(revenue * conversion_indicator)
        )

        assert stat.ratio == 500 / 20  # Total revenue / total conversions

    def test_validation_errors(self):
        """Test input validation."""
        numerator = SampleMeanStatistic(n=5, sum=25, sum_squares=125)
        denominator = SampleMeanStatistic(n=5, sum=0, sum_squares=0)  # Zero denominator

        # Zero denominator
        with pytest.raises(InvalidStatisticError):
            RatioStatistic(n=5, m_statistic=numerator, d_statistic=denominator, m_d_sum_of_products=0)

        # Mismatched sample sizes
        denominator_wrong_n = SampleMeanStatistic(n=3, sum=15, sum_squares=75)
        with pytest.raises(InvalidStatisticError):
            RatioStatistic(n=5, m_statistic=numerator, d_statistic=denominator_wrong_n, m_d_sum_of_products=0)


class TestStatisticIntegration:
    """Integration tests across statistic types."""

    def test_mean_extraction(self):
        """Test that all statistics can provide a mean value."""
        sample_mean = SampleMeanStatistic(n=10, sum=50, sum_squares=300)
        proportion = ProportionStatistic(n=100, sum=25)

        assert hasattr(sample_mean, "mean")
        assert hasattr(proportion, "proportion")

        # Both should be usable in calculations
        assert sample_mean.mean == 5.0
        assert proportion.proportion == 0.25

    def test_variance_extraction(self):
        """Test that all statistics can provide variance."""
        sample_mean = SampleMeanStatistic(n=10, sum=50, sum_squares=300)
        proportion = ProportionStatistic(n=100, sum=25)

        assert hasattr(sample_mean, "variance")
        assert hasattr(proportion, "variance")

        # Both should be non-negative
        assert sample_mean.variance >= 0
        assert proportion.variance >= 0

    def test_standard_error_calculation(self):
        """Test standard error calculations across types."""
        sample_mean = SampleMeanStatistic(n=10, sum=50, sum_squares=300)
        proportion = ProportionStatistic(n=100, sum=25)

        # Standard error should be sqrt(variance / n)
        expected_se_mean = np.sqrt(sample_mean.variance / sample_mean.n)
        expected_se_prop = np.sqrt(proportion.variance / proportion.n)

        assert abs(sample_mean.standard_error - expected_se_mean) < 1e-10
        assert abs(proportion.standard_error - expected_se_prop) < 1e-10


class TestQuantileStatistic(TestCase):
    @parameterized.expand(
        [
            ("control", QUANTILE_CONTROL, 86.97348405307501, 0.00013708395792512163, 167.31479431374606),
            ("treatment", QUANTILE_TREATMENT, 192.3691290860306, 0.0001531846058978492, 398.4726987554284),
        ]
    )
    def test_clustered_variance(self, _name, stat, iid_variance, cdf_cluster_variance, variance):
        assert stat.mean == stat.quantile
        assert stat.iid_variance == pytest.approx(iid_variance, rel=1e-12)
        assert stat.cdf_cluster_variance == pytest.approx(cdf_cluster_variance, rel=1e-12)
        assert stat.variance == pytest.approx(variance, rel=1e-12)
        assert stat.standard_error == pytest.approx(np.sqrt(variance / stat.n), rel=1e-12)
        assert not stat.has_zero_variance

    @parameterized.expand(
        [
            ("floored_at_n_100_or_more", 400, 1e-5),
            ("not_floored_below_n_100", 50, 6.507944290644809e-08),
        ]
    )
    def test_variance_floor(self, _name, n, expected_variance):
        stat = _iid_quantile(nu=0.5, n=n, lower=10.0, upper=10.0001)
        assert stat.variance == pytest.approx(expected_variance, rel=1e-9)

    @parameterized.expand(
        [
            ("collapsed_bounds_large_n", 0.75, 50_000_000, 8.0, 8.0, None, True),
            ("collapsed_bounds_small_n", 0.75, 2_000, 8.0, 8.0, None, True),
            ("open_bounds_large_n", 0.75, 50_000_000, 7.98, 8.02, None, False),
            ("interval_leaves_unit_range", 0.99, 300, 7.98, 8.02, None, True),
            ("single_cluster", 0.75, 2_000, 7.98, 8.02, 1, True),
        ]
    )
    def test_has_zero_variance(self, _name, nu, n, lower, upper, n_clusters, expected):
        stat = _iid_quantile(nu=nu, n=n, lower=lower, upper=upper, n_clusters=n_clusters)
        assert stat.has_zero_variance is expected

    @parameterized.expand(
        [
            ("nu_out_of_range", {"nu": 1.0}),
            ("no_events", {"n": 0, "n_sum": 0}),
            ("no_clusters", {"n_clusters": 0}),
            ("n_sum_differs_from_n", {"n_sum": 1262}),
            ("s_sum_above_n_sum", {"s_sum": 1264}),
            ("lower_above_upper", {"quantile_lower": 12.0}),
        ]
    )
    def test_validation_errors(self, _name, overrides: dict[str, Any]):
        fields = {name: getattr(QUANTILE_CONTROL, name) for name in QUANTILE_CONTROL.__dataclass_fields__}
        with pytest.raises(InvalidStatisticError):
            QuantileStatistic(**{**fields, **overrides})


class TestQuantileGridLevels(TestCase):
    @parameterized.expand(
        [
            ("nu_75_smallest_grid", 0.75, 0, (100, 0.6651310699, 0.8348689301)),
            ("nu_75_n_star_1600", 0.75, 4, (1600, 0.7287827675, 0.7712172325)),
            ("upper_clamped_below_one", 0.99, 0, (100, 0.9704986046, 0.99999999)),
        ]
    )
    def test_levels(self, _name, nu, index, expected):
        levels = quantile_grid_levels(nu)
        assert [level.n_star for level in levels] == QUANTILE_N_STAR_GRID
        n_star, lower_level, upper_level = expected
        assert levels[index] == QuantileGridLevel(n_star=n_star, lower_level=lower_level, upper_level=upper_level)


class TestChooseQuantileBounds(TestCase):
    BOUNDS = [(100, 1.0, 3.0), (200, 1.5, 2.5), (400, 1.8, 2.2), (800, 2.0, 2.0)]

    @staticmethod
    def _bounds(n_star: int, lower: float, upper: float) -> QuantileBounds:
        return QuantileBounds(n_star=n_star, lower=lower, upper=upper)

    @parameterized.expand(
        [
            ("largest_n_star_below_n", 300, BOUNDS, (200, 1.5, 2.5)),
            ("n_star_equal_to_n", 400, BOUNDS, (400, 1.8, 2.2)),
            ("smallest_grid_size_when_n_below_it", 40, BOUNDS, (100, 1.0, 3.0)),
            ("steps_down_when_bounds_collapse", 1000, BOUNDS, (400, 1.8, 2.2)),
            ("none_when_all_bounds_collapse", 1000, [(100, 2.0, 2.0), (200, 2.0, 2.0)], None),
        ]
    )
    def test_choose(self, _name, n, bounds, expected):
        chosen = choose_quantile_bounds(n, [self._bounds(*b) for b in bounds])
        assert chosen == (self._bounds(*expected) if expected is not None else None)
