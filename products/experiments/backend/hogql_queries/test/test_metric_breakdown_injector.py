from parameterized import parameterized

from posthog.schema import Breakdown, BreakdownAttributionType, BreakdownFilter, EventsNode, ExperimentFunnelMetric

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from products.experiments.backend.hogql_queries.metric_breakdown_injector import MetricBreakdownInjector


def _funnel_metric(attribution=None, attribution_value=None, num_steps=2):
    return ExperimentFunnelMetric(
        series=[EventsNode(event=f"step_{i}") for i in range(num_steps)],
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        breakdownAttributionType=attribution,
        breakdownAttributionValue=attribution_value,
    )


def _optimized_query() -> ast.SelectQuery:
    query = parse_select("SELECT variant FROM base_events AS entity_metrics")
    assert isinstance(query, ast.SelectQuery)
    base = parse_select("SELECT variant, entity_id, timestamp, step_0, step_1, step_2 FROM events")
    em = parse_select("SELECT variant FROM base_events GROUP BY variant")
    assert isinstance(base, ast.SelectQuery) and isinstance(em, ast.SelectQuery)
    query.ctes = {
        "base_events": ast.CTE(name="base_events", expr=base, cte_type="subquery"),
        "entity_metrics": ast.CTE(name="entity_metrics", expr=em, cte_type="subquery"),
    }
    return query


def _entity_metrics_aliases(query: ast.SelectQuery) -> dict[str, ast.Expr]:
    assert query.ctes is not None
    cte = query.ctes["entity_metrics"]
    assert isinstance(cte, ast.CTE) and isinstance(cte.expr, ast.SelectQuery)
    return {c.alias: c.expr for c in cte.expr.select if isinstance(c, ast.Alias)}


class TestMetricBreakdownInjector:
    # step_0 is the exposure step; metric series events are step_1..step_N.
    @parameterized.expand(
        [
            ("first_touch", BreakdownAttributionType.FIRST_TOUCH, None, "argMinIf", "step_1"),
            ("last_touch", BreakdownAttributionType.LAST_TOUCH, None, "argMaxIf", "step_2"),
            ("step_series_0", BreakdownAttributionType.STEP, 0, "argMinIf", "step_1"),
            ("step_series_1", BreakdownAttributionType.STEP, 1, "argMinIf", "step_2"),
            ("all_events", BreakdownAttributionType.ALL_EVENTS, None, "argMinIf", "step_1"),
            ("default_none", None, None, "argMinIf", "step_1"),
        ]
    )
    def test_optimized_attribution_modes(self, _name, attribution, value, expected_agg, expected_step):
        metric = _funnel_metric(attribution=attribution, attribution_value=value, num_steps=2)
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _optimized_query()

        injector.inject_funnel_breakdown_columns_optimized(query)

        expr = _entity_metrics_aliases(query)["breakdown_value_1"]
        assert isinstance(expr, ast.Call)
        assert expr.name == expected_agg
        cond = expr.args[2]
        assert isinstance(cond, ast.CompareOperation)
        assert cond.left == ast.Field(chain=[expected_step])

    def test_breakdown_read_from_metric_event_in_base_events(self):
        metric = _funnel_metric(attribution=BreakdownAttributionType.FIRST_TOUCH)
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _optimized_query()

        injector.inject_funnel_breakdown_columns_optimized(query)

        assert query.ctes is not None
        base_cte = query.ctes["base_events"]
        assert isinstance(base_cte, ast.CTE) and isinstance(base_cte.expr, ast.SelectQuery)
        base_aliases = [c.alias for c in base_cte.expr.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in base_aliases

    def test_breakdown_added_to_final_select_and_group_by(self):
        metric = _funnel_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _optimized_query()

        injector.inject_funnel_breakdown_columns_optimized(query)

        select_aliases = [c.alias for c in query.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in select_aliases
        # The limit relabel groups by the output alias (the relabeled column), not the raw
        # entity_metrics column, so "Other" rows merge.
        assert query.group_by is not None
        assert ast.Field(chain=["breakdown_value_1"]) in query.group_by

    def test_final_breakdown_column_applies_top_n_other_relabel(self):
        metric = _funnel_metric()
        metric.breakdownFilter.breakdown_limit = 3
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _optimized_query()

        injector.inject_funnel_breakdown_columns_optimized(query)

        final_alias = next(c for c in query.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        # if(<in top-N>, value, 'Other')
        assert isinstance(final_alias.expr, ast.Call)
        assert final_alias.expr.name == "if"
        in_top = final_alias.expr.args[0]
        assert isinstance(in_top, ast.CompareOperation)
        assert in_top.op == ast.CompareOperationOp.In
        assert isinstance(in_top.right, ast.SelectQuery)
        assert isinstance(in_top.right.limit, ast.Constant)
        assert in_top.right.limit.value == 3
        other = final_alias.expr.args[2]
        assert isinstance(other, ast.Constant)
        assert other.value == "$$_posthog_breakdown_other_$$"

    def test_step_attribution_out_of_range_raises(self):
        metric = _funnel_metric(attribution=BreakdownAttributionType.STEP, attribution_value=5, num_steps=2)
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _optimized_query()

        try:
            injector.inject_funnel_breakdown_columns_optimized(query)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
