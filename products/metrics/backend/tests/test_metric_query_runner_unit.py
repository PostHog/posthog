import datetime as dt

import pytest

from parameterized import parameterized

from posthog.hogql import ast

from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.metric_query_runner import (
    _active_since_expr,
    _exponential_upper_edges,
    _Histogram,
    _histogram_quantile,
    _merge_histograms,
    _pick_interval,
    _resolution_edges,
)


class TestPickInterval:
    @parameterized.expand(
        [
            ("15m_range_picks_15_seconds", dt.timedelta(minutes=15), "second_15"),
            ("1h_range_picks_minute", dt.timedelta(hours=1), "minute"),
            ("1d_range_picks_30_minutes", dt.timedelta(days=1), "minute_30"),
            ("30d_range_picks_day", dt.timedelta(days=30), "day"),
        ]
    )
    def test_pick_interval(self, _name: str, delta: dt.timedelta, expected: str) -> None:
        start = dt.datetime(2026, 9, 15, 0, 0, 0, tzinfo=dt.UTC)
        assert _pick_interval(start, start + delta) == expected


class TestActiveSinceExpr:
    def test_keeps_series_within_the_last_seen_buffer(self) -> None:
        date_from = dt.datetime(2026, 9, 15, 12, tzinfo=dt.UTC)

        expr = _active_since_expr(date_from)

        assert isinstance(expr, ast.CompareOperation)
        assert isinstance(expr.right, ast.Constant)
        assert expr.right.value == date_from - dt.timedelta(hours=1)


class TestHistogramQuantileInterpolation:
    @parameterized.expand(
        [
            ("p50_mid_bucket", 0.5, [0.1, 0.5, 1.0], [10.0, 10.0, 10.0, 0.0], 0.3),
            ("p25_first_bucket", 0.25, [0.1, 0.5, 1.0], [10.0, 10.0, 10.0, 0.0], 0.075),
            ("overflow_clamps", 0.99, [0.1, 0.5, 1.0], [1.0, 1.0, 1.0, 10.0], 1.0),
            ("empty_counts", 0.5, [0.1, 0.5], [0.0, 0.0, 0.0], 0.0),
            ("no_bounds", 0.5, [], [10.0], 0.0),
        ]
    )
    def test_interpolation(self, _name, q, bounds, counts, expected):
        assert abs(_histogram_quantile(q, bounds, counts) - expected) < 1e-9


class TestExponentialUpperEdges:
    # Ingest stores each exponential bucket's lower edge. The quantile reads upper edges.
    @parameterized.expand(
        [
            ("positive_buckets", [1.0, 2.0, 4.0], [1, 2, 3], [1.0, 2.0, 4.0, 8.0], [0, 1, 2, 3]),
            ("zero_bucket_first", [0.0, 1.0, 2.0], [5, 1, 1], [0.0, 1.0, 2.0, 4.0], [5, 0, 1, 1]),
            # One bucket gives no base: it becomes a zero-width bucket at its lower edge, which is inside the true range.
            ("one_bucket_sits_on_its_lower_edge", [1.0], [3], [1.0, 1.0], [0, 3]),
            # Negative bucket i is [-base**(i+1), -base**i): ingest stores -base**i, closest to zero first.
            ("negative_buckets_ascend", [-1.0, -2.0], [1, 2], [-4.0, -2.0, -1.0], [0, 2, 1]),
            (
                "zero_between_negative_and_positive",
                [0.0, -1.0, -2.0, 1.0, 2.0],
                [5, 1, 2, 3, 4],
                # The zero bucket stays zero-width at 0 instead of spreading over (-1, 0].
                [-4.0, -2.0, -1.0, 0.0, 0.0, 1.0, 2.0, 4.0],
                [0, 2, 1, 0, 5, 0, 3, 4],
            ),
            ("empty", [], [], [], []),
            (
                # Repro: base=sqrt(2) between 2**-20 and 2**-19.5 computes 2**-19 one bit off from the
                # stored bound, so a naive recompute inserts a spurious empty bucket and sorts out of order.
                "consecutive_buckets_at_a_fine_scale_share_an_exact_edge",
                [2**-20, 2**-19.5, 2**-19],
                [5, 5, 5],
                [2**-20, 2**-19.5, 2**-19, 2**-18.5],
                [0, 5, 5, 5],
            ),
            (
                "consecutive_buckets_at_a_coarse_scale_share_an_exact_edge",
                [2**10, 2**10.5, 2**11],
                [2, 3, 4],
                [2**10, 2**10.5, 2**11, 2**11.5],
                [0, 2, 3, 4],
            ),
        ]
    )
    def test_upper_edges(self, _name, bounds, counts, expected_bounds, expected_counts):
        assert _exponential_upper_edges(bounds, counts) == (expected_bounds, expected_counts)

    def test_upper_edges_are_always_sorted_ascending(self):
        # The quantile and _resolution_edges both assume ascending edges; unsorted edges silently
        # drop a real edge (see test_resolution_edges_keep_the_real_edge below).
        edges, _ = _exponential_upper_edges([2**-20, 2**-19.5, 2**-19], [5, 5, 5])
        assert edges == sorted(edges)

    def test_resolution_edges_keep_the_real_edge(self):
        # Before the fix, bisecting this unsorted edge list silently dropped the 2**-19 edge.
        bounds, counts = _exponential_upper_edges([2**-20, 2**-19.5, 2**-19], [5, 5, 5])
        histogram = _Histogram(bounds=bounds, counts=counts)
        merged = _merge_histograms([histogram])
        assert _resolution_edges([histogram], merged.bounds) == merged.bounds

    @parameterized.expand(
        [
            ("positive", [0.1, 0.2, 0.4], [0, 10, 0], 0.3),
            ("one_bucket", [1.0], [10], 1.0),
            ("negative", [-1.0, -2.0, 1.0, 2.0], [0, 10, 0, 0], -3.0),
        ]
    )
    def test_quantile_lands_inside_the_true_bucket(self, _name, bounds, counts, expected):
        upper_bounds, upper_counts = _exponential_upper_edges(bounds, counts)
        assert abs(_histogram_quantile(0.5, upper_bounds, upper_counts) - expected) < 1e-9


class TestMergeHistograms:
    @parameterized.expand(
        [
            (
                "same_layout_sums",
                [([0.1, 0.5], [1.0, 2.0, 3.0]), ([0.1, 0.5], [1.0, 2.0, 3.0])],
                [0.1, 0.5],
                [2.0, 4.0, 6.0],
            ),
            (
                "coarse_bucket_splits_by_width",
                [([1.0], [10.0, 0.0]), ([0.5, 1.0], [4.0, 6.0, 0.0])],
                [0.5, 1.0],
                [9.0, 11.0, 0.0],
            ),
            (
                "overflow_goes_to_the_next_bucket_up",
                [([1.0], [0.0, 3.0]), ([2.0, 4.0], [0.0, 0.0, 0.0])],
                [1.0, 2.0, 4.0],
                [0.0, 3.0, 0.0, 0.0],
            ),
            (
                "overflow_above_every_edge_stays_overflow",
                [([4.0], [0.0, 3.0]), ([2.0], [1.0, 0.0])],
                [2.0, 4.0],
                [1.0, 0.0, 3.0],
            ),
            ("one_layout_is_unchanged", [([0.1, 0.5], [1.0, 2.0, 3.0])], [0.1, 0.5], [1.0, 2.0, 3.0]),
            (
                "edges_from_an_empty_layout_still_split",
                [([1.0], [10.0, 0.0]), ([0.5], [0.0, 0.0])],
                [0.5, 1.0],
                [5.0, 5.0, 0.0],
            ),
            ("no_edges_is_one_open_bucket", [([], [5.0]), ([1.0], [0.0, 0.0])], [1.0], [5.0, 0.0]),
            (
                "counts_past_the_edges_are_overflow",
                [([1.0], [1.0, 2.0, 3.0]), ([2.0], [0.0, 0.0])],
                [1.0, 2.0],
                [1.0, 5.0, 0.0],
            ),
            (
                "overlapping_layouts_spread_by_width",
                [([1.0, 3.0], [0.0, 4.0, 0.0]), ([2.0, 4.0], [0.0, 4.0, 0.0])],
                [1.0, 2.0, 3.0, 4.0],
                [0.0, 2.0, 4.0, 2.0, 0.0],
            ),
        ]
    )
    def test_merge(self, _name, distributions, expected_bounds, expected_counts):
        merged = _merge_histograms([_Histogram(bounds=bounds, counts=counts) for bounds, counts in distributions])
        assert merged.bounds == expected_bounds
        assert merged.counts == pytest.approx(expected_counts)

    def test_total_count_is_kept(self):
        merged = _merge_histograms(
            [
                _Histogram(bounds=[0.1, 0.3, 0.9], counts=[5.0, 7.0, 11.0, 2.0]),
                _Histogram(bounds=[0.2, 1.0], counts=[3.0, 4.0, 1.0]),
            ]
        )
        assert sum(merged.counts) == pytest.approx(33.0)


class TestResolutionEdges:
    @parameterized.expand(
        [
            ("one_layout_keeps_every_edge", [([0.1, 0.3], [1.0, 1.0, 0.0])], [0.1, 0.3]),
            # Rebucketing a coarse (1, 10] bucket onto finer edges adds no precision.
            (
                "coarse_bucket_hides_finer_edges",
                [([1.0, 10.0], [0.0, 4.0, 0.0]), ([2.0, 4.0, 10.0], [0.0] * 4)],
                [1.0, 10.0],
            ),
            (
                "empty_bucket_hides_nothing",
                [([1.0, 10.0], [4.0, 0.0, 0.0]), ([2.0, 4.0], [0.0] * 3)],
                [1.0, 2.0, 4.0, 10.0],
            ),
            ("overflow_hides_edges_above_it", [([1.0], [0.0, 3.0]), ([2.0, 4.0], [0.0] * 3)], [1.0]),
        ]
    )
    def test_resolution_edges(self, _name, distributions, expected):
        histograms = [_Histogram(bounds=bounds, counts=counts) for bounds, counts in distributions]
        assert _resolution_edges(histograms, _merge_histograms(histograms).bounds) == expected


class TestFormulaParser:
    @parameterized.expand(
        [
            ("add", "a + b", {"a": 3.0, "b": 4.0}, 7.0),
            ("precedence", "a + b * 2", {"a": 1.0, "b": 2.0}, 5.0),
            ("parens", "(a - b) / a", {"a": 10.0, "b": 4.0}, 0.6),
            ("unary_minus", "-a + 5", {"a": 2.0}, 3.0),
            ("division_by_zero_yields_zero", "a / b", {"a": 5.0, "b": 0.0}, 0.0),
            ("number_only_arithmetic", "a * 0 + 1.5", {"a": 9.0}, 1.5),
            ("exponent_literal", "a * 1e3", {"a": 2.0}, 2000.0),
            ("negative_exponent_literal", "a * 2.5E-2", {"a": 4.0}, 0.1),
        ]
    )
    def test_evaluate(self, _name, formula, values, expected):
        node = parse_formula(formula, frozenset(values))
        assert abs(evaluate(node, values) - expected) < 1e-9

    @parameterized.expand(
        [
            ("unknown_clause", "a + zz", frozenset({"a", "b"})),
            ("unbalanced_parens", "(a + b", frozenset({"a", "b"})),
            ("trailing_garbage", "a + b )", frozenset({"a", "b"})),
            ("empty", "   ", frozenset({"a"})),
            ("bad_char", "a ^ b", frozenset({"a", "b"})),
            ("non_finite_literal", "9" * 400, frozenset({"a"})),
            ("non_finite_exponent_literal", "a * 1e400", frozenset({"a"})),
            ("nesting_too_deep_parens", "(" * 40 + "a" + ")" * 40, frozenset({"a"})),
            ("nesting_too_deep_unary", "-" * 40 + "a", frozenset({"a"})),
        ]
    )
    def test_rejects(self, _name, formula, names):
        with pytest.raises(ValueError):
            parse_formula(formula, names)

    def test_overflowing_exponent_asks_for_a_smaller_number(self):
        with pytest.raises(ValueError, match="too large"):
            parse_formula("a * 1e400", frozenset({"a"}))
