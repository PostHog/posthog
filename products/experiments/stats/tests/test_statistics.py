import pytest

import numpy as np

from ..shared.statistics import InvalidStatisticError, ProportionStatistic, RatioStatistic, SampleMeanStatistic


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
