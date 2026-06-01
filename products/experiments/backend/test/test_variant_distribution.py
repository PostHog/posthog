from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.variant_distribution import even_distribution, is_evenly_distributed


class TestEvenDistribution(TestCase):
    @parameterized.expand(
        [
            ("zero_variants", 0, []),
            ("one_variant", 1, [100]),
            ("two_variants", 2, [50, 50]),
            ("three_variants", 3, [34, 33, 33]),
            ("four_variants", 4, [25, 25, 25, 25]),
            ("seven_variants", 7, [15, 15, 14, 14, 14, 14, 14]),
        ]
    )
    def test_distribution(self, _name, variant_count, expected):
        self.assertEqual(even_distribution(variant_count), expected)

    def test_distribution_always_sums_to_100(self):
        for n in range(1, 20):
            self.assertEqual(sum(even_distribution(n)), 100, f"failed for {n} variants")


class TestIsEvenlyDistributed(TestCase):
    @parameterized.expand(
        [
            ("empty", [], True),
            ("single_100", [100], True),
            ("balanced_50_50", [50, 50], True),
            ("auto_even_34_33_33", [34, 33, 33], True),
            ("auto_even_25x4", [25, 25, 25, 25], True),
            ("uneven_80_20", [80, 20], False),
            ("uneven_60_30_10", [60, 30, 10], False),
            ("reordered_33_34_33", [33, 34, 33], False),
            ("reordered_33_33_34", [33, 33, 34], False),
        ]
    )
    def test_evenly_distributed(self, _name, rollout_percentages, expected):
        self.assertEqual(is_evenly_distributed(rollout_percentages), expected)
