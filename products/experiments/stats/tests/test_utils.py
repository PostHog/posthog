import pytest
from unittest import TestCase

from products.experiments.stats.frequentist.utils import calculate_welch_satterthwaite_df
from products.experiments.stats.shared.statistics import SampleMeanStatistic


class TestFrequentistUtils(TestCase):
    def test_calculate_welch_satterthwaite_df(self):
        """Test calculate_welch_satterthwaite_df function."""
        stat_a = SampleMeanStatistic(sum=1922.7, sum_squares=94698.29, n=2461)
        stat_b = SampleMeanStatistic(sum=1196.87, sum_squares=37377.9767, n=2507)
        df = calculate_welch_satterthwaite_df(stat_a, stat_b)
        assert df == pytest.approx(4105.070, abs=1e-3)
