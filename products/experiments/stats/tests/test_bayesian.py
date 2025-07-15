"""
Tests for Bayesian statistical methods.

This module tests all Bayesian classes for correctness of calculations,
validation, and edge case handling.
"""

import pytest
import numpy as np
from unittest import TestCase


from products.experiments.stats.bayesian.method import (
    BayesianMethod,
    BayesianConfig,
    PriorType,
)
from products.experiments.stats.bayesian.tests import (
    BayesianResult,
    BayesianGaussianTest,
)
from products.experiments.stats.bayesian.priors import GaussianPrior
from products.experiments.stats.shared.statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    StatisticError,
)
from products.experiments.stats.shared.enums import DifferenceType

from products.experiments.stats.bayesian.utils import (
    calculate_effect_size_and_variance,
    calculate_posterior,
    calculate_risk,
    chance_to_win,
    credible_interval,
)


class TestGaussianPrior:
    """Tests for GaussianPrior class."""

    def test_validation_errors(self):
        """Test prior validation."""
        # Negative variance
        with pytest.raises(ValueError):
            GaussianPrior(variance=-1.0)

        # Zero variance
        with pytest.raises(ValueError):
            GaussianPrior(variance=0.0)

    def test_string_representation(self):
        """Test string representation."""
        # Non-informative prior
        prior = GaussianPrior()
        assert str(prior) == "Non-informative prior"

        # Informative prior
        prior = GaussianPrior(mean=0.05, variance=0.01, proper=True)
        assert "N(μ=0.050, σ²=0.010)" in str(prior)


class TestBayesianConfig(TestCase):
    """Tests for BayesianConfig class."""

    def test_default_config(self):
        """Test default configuration."""
        config = BayesianConfig()

        assert config.ci_level == 0.95
        assert config.inverse is False
        assert config.difference_type == DifferenceType.RELATIVE
        assert config.prior_type == PriorType.RELATIVE
        assert config.prior_mean == 0.0
        assert config.prior_variance == 1.0
        assert config.proper_prior is False

    def test_create_prior(self):
        """Test prior creation from config."""
        config = BayesianConfig(prior_mean=0.05, prior_variance=0.01, proper_prior=True)

        prior = config.create_prior()
        assert prior.mean == 0.05
        assert prior.variance == 0.01
        assert prior.proper is True

    def test_validation_errors(self):
        """Test config validation."""
        # Invalid ci_level
        with pytest.raises(StatisticError):
            BayesianConfig(ci_level=0.0)

        with pytest.raises(StatisticError):
            BayesianConfig(ci_level=1.0)

        # Invalid prior variance
        with pytest.raises(StatisticError):
            BayesianConfig(prior_variance=0.0)


class TestBayesianUtils(TestCase):
    """Tests for Bayesian utility functions."""

    def test_effect_size_calculation_absolute(self):
        """Test absolute effect size calculation."""

        # Sample mean statistics - use valid sum_squares
        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)  # mean=5.5
        control = SampleMeanStatistic(n=100, sum=500, sum_squares=2550)  # mean=5.0

        effect, variance = calculate_effect_size_and_variance(treatment, control, DifferenceType.ABSOLUTE)

        assert abs(effect - 0.5) < 1e-10  # 5.5 - 5.0
        # Calculate actual variances: (sum_squares - sum²/n) / (n-1)
        treatment_var = (3050 - 550**2 / 100) / 99  # ≈ 0.7576
        control_var = (2550 - 500**2 / 100) / 99  # ≈ 0.5051
        expected_variance = treatment_var / 100 + control_var / 100
        assert abs(variance - expected_variance) < 1e-6

    def test_effect_size_calculation_relative(self):
        """Test relative effect size calculation."""

        # Proportion statistics
        treatment = ProportionStatistic(n=1000, sum=110)  # proportion=0.11
        control = ProportionStatistic(n=1000, sum=100)  # proportion=0.10

        effect, variance = calculate_effect_size_and_variance(treatment, control, DifferenceType.RELATIVE)

        expected_effect = (0.11 - 0.10) / 0.10  # 0.1 = 10% increase
        assert abs(effect - expected_effect) < 1e-10
        assert variance > 0  # Should have positive variance

    def test_posterior_calculation(self):
        """Test Bayesian posterior updating."""

        # Non-informative prior
        prior = GaussianPrior(proper=False)
        effect_size = 0.1
        effect_variance = 0.01

        post_mean, post_var = calculate_posterior(effect_size, effect_variance, prior)

        # With non-informative prior, posterior should equal likelihood
        assert abs(post_mean - effect_size) < 1e-10
        assert abs(post_var - effect_variance) < 1e-10

        # Informative prior
        prior = GaussianPrior(mean=0.05, variance=0.02, proper=True)
        post_mean, post_var = calculate_posterior(effect_size, effect_variance, prior)

        # Should be weighted average between prior and data
        assert 0.05 < post_mean < 0.1  # Between prior mean and data
        assert post_var < min(0.02, 0.01)  # Less than both prior and data variance

    def test_chance_to_win(self):
        """Test chance to win calculation."""

        # Clearly positive effect
        prob = chance_to_win(0.1, 0.01, inverse=False)
        assert prob > 0.99  # Very high probability

        # Clearly negative effect
        prob = chance_to_win(-0.1, 0.01, inverse=False)
        assert prob < 0.01  # Very low probability

        # Test inverse logic (lower is better)
        prob = chance_to_win(-0.1, 0.01, inverse=True)
        assert prob > 0.99  # High probability for negative effect when inverse=True

    def test_credible_interval(self):
        """Test credible interval calculation."""

        # 95% credible interval
        lower, upper = credible_interval(0.1, 0.05, alpha=0.05)

        assert lower < 0.1 < upper  # Mean should be in interval
        assert upper - lower > 0.15  # Should be reasonably wide for this std dev

        # 99% credible interval should be wider
        lower_99, upper_99 = credible_interval(0.1, 0.05, alpha=0.01)
        assert upper_99 - lower_99 > upper - lower

    def test_risk_calculation(self):
        """Test risk assessment calculation."""

        # Positive effect with some uncertainty
        risk_control, risk_treatment = calculate_risk(0.05, 0.02)

        # Risk of choosing control should be higher (we're missing positive effect)
        assert risk_control > risk_treatment
        assert risk_control > 0
        assert risk_treatment >= 0  # Can be zero if effect is clearly positive


class TestBayesianGaussianTest(TestCase):
    """Tests for BayesianGaussianTest class."""

    def test_basic_test_execution(self):
        """Test basic Bayesian Gaussian test execution."""
        test = BayesianGaussianTest(ci_level=0.95)

        # Create test data
        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)
        control = SampleMeanStatistic(n=100, sum=500, sum_squares=2550)
        prior = GaussianPrior()

        result = test.run_test(treatment, control, prior, DifferenceType.RELATIVE)

        # Check result structure
        assert isinstance(result, BayesianResult)
        assert 0 <= result.chance_to_win <= 1
        assert len(result.credible_interval) == 2
        assert result.credible_interval[0] < result.credible_interval[1]
        assert result.ci_level == 0.95
        assert result.difference_type == "relative"

    def test_proportion_test(self):
        """Test with proportion statistics."""
        test = BayesianGaussianTest()

        # Conversion rate test: 11% vs 10%
        treatment = ProportionStatistic(n=1000, sum=110)
        control = ProportionStatistic(n=1000, sum=100)
        prior = GaussianPrior()

        result = test.run_test(treatment, control, prior, DifferenceType.RELATIVE)

        assert result.effect_size > 0  # Treatment should be better
        assert result.chance_to_win > 0.5  # Should favor treatment

    def test_invalid_inputs(self):
        """Test with invalid inputs."""
        test = BayesianGaussianTest()

        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)
        control = ProportionStatistic(n=100, sum=50)  # Different type!
        prior = GaussianPrior()

        # Should raise error for mismatched types
        with pytest.raises(StatisticError):
            test.run_test(treatment, control, prior)


class TestBayesianMethod(TestCase):
    """Tests for BayesianMethod class."""

    def test_basic_method_usage(self):
        """Test basic BayesianMethod usage."""
        method = BayesianMethod()

        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)
        control = SampleMeanStatistic(n=100, sum=500, sum_squares=2550)

        result = method.run_test(treatment, control)

        assert isinstance(result, BayesianResult)
        assert result.effect_size > 0  # Treatment is better
        assert result.chance_to_win > 0.5

    def test_with_informative_prior(self):
        """Test with informative prior."""
        config = BayesianConfig(prior_mean=0.05, prior_variance=0.01, proper_prior=True)
        method = BayesianMethod(config)

        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)
        control = SampleMeanStatistic(n=100, sum=500, sum_squares=2550)

        result = method.run_test(treatment, control)

        # Prior should influence the result
        assert result.proper_prior is True
        assert result.prior_mean == 0.05
        assert result.prior_variance == 0.01

    def test_summary_generation(self):
        """Test summary generation."""
        method = BayesianMethod()

        treatment = ProportionStatistic(n=1000, sum=110)
        control = ProportionStatistic(n=1000, sum=100)
        result = method.run_test(treatment, control)

        summary = method.get_summary(result)

        # Check required summary fields
        assert "preferred_variation" in summary
        assert "chance_to_win" in summary
        assert "confidence_in_decision" in summary
        assert "interpretation" in summary
        assert "risk_assessment" in summary
        assert "recommendation" in summary

    def test_create_simple_config(self):
        """Test simple config creation."""
        config = BayesianMethod.create_simple_config(
            ci_level=0.99, difference_type="absolute", prior_mean=0.1, proper_prior=True
        )

        assert config.ci_level == 0.99
        assert config.difference_type == DifferenceType.ABSOLUTE
        assert config.prior_mean == 0.1
        assert config.proper_prior is True

    def test_realistic_example(self):
        """Test basic two-sided t-test with sample mean statistics."""
        treatment = SampleMeanStatistic(sum=1922.7, sum_squares=94698.29, n=2461)
        control = SampleMeanStatistic(sum=1196.87, sum_squares=37377.9767, n=2507)

        config = BayesianConfig(ci_level=0.95, difference_type=DifferenceType.RELATIVE)
        method = BayesianMethod(config)
        result = method.run_test(treatment, control)

        result_dict = method.get_summary(result)
        expected_dict = {
            "effect_size": 0.63646,
            "credible_interval": [-0.0873, 1.36026],
            "chance_to_win": 0.95759,
            "error_message": None,
        }

        # Compare the key values
        self.assertAlmostEqual(result_dict["effect_size"], expected_dict["effect_size"], places=4)
        self.assertAlmostEqual(result_dict["credible_interval"][0], expected_dict["credible_interval"][0], places=4)
        self.assertAlmostEqual(result_dict["credible_interval"][1], expected_dict["credible_interval"][1], places=4)
        self.assertAlmostEqual(result_dict["chance_to_win"], expected_dict["chance_to_win"], places=4)


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_run_simple_bayesian_test(self):
        """Test run_simple_bayesian_test function."""
        treatment = ProportionStatistic(n=1000, sum=110)
        control = ProportionStatistic(n=1000, sum=100)

        config = BayesianMethod.create_simple_config(
            ci_level=0.95,
            inverse=False,
            difference_type="relative",
            prior_mean=0.05,
            prior_variance=0.01,
            proper_prior=True,
        )
        method = BayesianMethod(config)

        result = method.run_test(treatment, control)

        assert isinstance(result, BayesianResult)
        assert result.chance_to_win > 0.5  # Treatment should be favored


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_zero_control_mean_relative(self):
        """Test relative difference with zero control mean."""
        method = BayesianMethod()

        treatment = SampleMeanStatistic(n=100, sum=100, sum_squares=100)  # mean=1
        control = SampleMeanStatistic(n=100, sum=0, sum_squares=0)  # mean=0

        # Should raise error for relative difference
        with pytest.raises(StatisticError):
            method.run_test(treatment, control)

    def test_very_small_variances(self):
        """Test with very small variances."""
        method = BayesianMethod()

        # Almost identical groups (very small variance)
        # Use valid sum_squares: must be >= sum²/n
        treatment = SampleMeanStatistic(n=1000, sum=10000, sum_squares=100001)  # mean=10, tiny variance
        control = SampleMeanStatistic(n=1000, sum=9999, sum_squares=99990.001)  # mean≈10, tiny variance

        result = method.run_test(treatment, control)

        # Should still work, just with tight intervals
        assert isinstance(result, BayesianResult)
        assert result.posterior_variance > 0

    def test_extreme_sample_sizes(self):
        """Test with extreme sample sizes."""
        method = BayesianMethod()

        # Very small sample sizes
        treatment = SampleMeanStatistic(n=2, sum=3, sum_squares=5)
        control = SampleMeanStatistic(n=2, sum=2, sum_squares=2)

        result = method.run_test(treatment, control)

        # Should have high uncertainty
        assert result.posterior_variance > 0
        assert 0.1 < result.chance_to_win < 0.9  # Should be uncertain

    def test_mismatched_statistic_types(self):
        """Test with mismatched statistic types."""
        method = BayesianMethod()

        treatment = SampleMeanStatistic(n=100, sum=550, sum_squares=3050)
        control = ProportionStatistic(n=100, sum=50)

        with pytest.raises(StatisticError):
            method.run_test(treatment, control)


class TestNumericalStability:
    """Tests for numerical stability and precision."""

    def test_large_numbers(self):
        """Test with large numbers."""
        method = BayesianMethod()

        # Large sums but reasonable means - ensure valid sum_squares
        treatment = SampleMeanStatistic(n=1000000, sum=10500000, sum_squares=110250001)  # mean=10.5
        control = SampleMeanStatistic(n=1000000, sum=10000000, sum_squares=100000001)  # mean=10

        result = method.run_test(treatment, control)

        assert np.isfinite(result.effect_size)
        assert np.isfinite(result.posterior_variance)
        assert 0 <= result.chance_to_win <= 1

    def test_small_differences(self):
        """Test with very small effect sizes."""
        method = BayesianMethod()

        # Very small difference - ensure valid sum_squares (must be >= sum²/n)
        treatment = SampleMeanStatistic(n=10000, sum=10001, sum_squares=10002.0002)  # mean≈1.0001
        control = SampleMeanStatistic(n=10000, sum=10000, sum_squares=10000.0001)  # mean=1.0000

        result = method.run_test(treatment, control)

        assert np.isfinite(result.effect_size)
        assert result.effect_size > 0  # Should detect small positive effect

    def test_precision_loss_protection(self):
        """Test protection against precision loss."""
        method = BayesianMethod()

        # Case that passes normal approximation validation
        treatment = ProportionStatistic(n=1000, sum=10)  # 1% proportion
        control = ProportionStatistic(n=1000, sum=5)  # 0.5% proportion

        result = method.run_test(treatment, control, difference_type=DifferenceType.ABSOLUTE)

        # Should handle this gracefully
        assert np.isfinite(result.effect_size)
        assert result.posterior_variance > 0
