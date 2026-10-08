import datetime as dt

import pytest

from parameterized import parameterized

from posthog.hogql import ast

from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.metric_query_runner import _active_since_expr, _histogram_quantile, _pick_interval


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


class TestFormulaParser:
    @parameterized.expand(
        [
            ("add", "a + b", {"a": 3.0, "b": 4.0}, 7.0),
            ("precedence", "a + b * 2", {"a": 1.0, "b": 2.0}, 5.0),
            ("parens", "(a - b) / a", {"a": 10.0, "b": 4.0}, 0.6),
            ("unary_minus", "-a + 5", {"a": 2.0}, 3.0),
            ("division_by_zero_yields_zero", "a / b", {"a": 5.0, "b": 0.0}, 0.0),
            ("number_only_arithmetic", "a * 0 + 1.5", {"a": 9.0}, 1.5),
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
            ("nesting_too_deep_parens", "(" * 40 + "a" + ")" * 40, frozenset({"a"})),
            ("nesting_too_deep_unary", "-" * 40 + "a", frozenset({"a"})),
        ]
    )
    def test_rejects(self, _name, formula, names):
        with pytest.raises(ValueError):
            parse_formula(formula, names)
