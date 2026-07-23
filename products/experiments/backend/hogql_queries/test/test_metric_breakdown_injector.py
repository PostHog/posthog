from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    BreakdownFilter,
    BreakdownType,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

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


def _mean_metric(breakdown_limit=None):
    return ExperimentMeanMetric(
        source=EventsNode(event="purchase"),
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")], breakdown_limit=breakdown_limit),
    )


def _dw_mean_metric():
    return ExperimentMeanMetric(
        source=ExperimentDataWarehouseNode(
            table_name="usage",
            events_join_key="properties.$user_id",
            data_warehouse_join_key="userid",
            timestamp_field="ds",
            math=ExperimentMetricMathType.SUM,
            math_property="usage",
        ),
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="plan", type=BreakdownType.DATA_WAREHOUSE)]),
    )


def _mean_query() -> ast.SelectQuery:
    # Minimal stand-in mirroring the standard mean shape: metric_events + entity_metrics.
    query = parse_select("SELECT variant FROM entity_metrics")
    assert isinstance(query, ast.SelectQuery)
    me = parse_select("SELECT entity_id, timestamp, value FROM events")
    em = parse_select(
        "SELECT exposures.entity_id, exposures.variant, sum(value) AS value FROM exposures GROUP BY exposures.entity_id, exposures.variant"
    )
    assert isinstance(me, ast.SelectQuery) and isinstance(em, ast.SelectQuery)
    query.ctes = {
        "metric_events": ast.CTE(name="metric_events", expr=me, cte_type="subquery"),
        "entity_metrics": ast.CTE(name="entity_metrics", expr=em, cte_type="subquery"),
    }
    return query


def _session_mean_query() -> ast.SelectQuery:
    # Stand-in for the session-property mean shape:
    # metric_events_by_session -> metric_events -> entity_metrics.
    query = parse_select("SELECT variant FROM entity_metrics")
    assert isinstance(query, ast.SelectQuery)
    mebs = parse_select(
        "SELECT entity_id, `$session_id` AS session_id, any(session.x) AS session_value, "
        "min(timestamp) AS first_event_timestamp FROM events GROUP BY entity_id, `$session_id`"
    )
    me = parse_select(
        "SELECT exposures.entity_id AS entity_id, exposures.variant AS variant, "
        "metric_events_by_session.session_value AS value FROM exposures "
        "INNER JOIN metric_events_by_session ON exposures.entity_id = metric_events_by_session.entity_id"
    )
    em = parse_select("SELECT entity_id, variant, sum(value) AS value FROM metric_events GROUP BY entity_id, variant")
    assert isinstance(mebs, ast.SelectQuery) and isinstance(me, ast.SelectQuery) and isinstance(em, ast.SelectQuery)
    query.ctes = {
        "metric_events_by_session": ast.CTE(name="metric_events_by_session", expr=mebs, cte_type="subquery"),
        "metric_events": ast.CTE(name="metric_events", expr=me, cte_type="subquery"),
        "entity_metrics": ast.CTE(name="entity_metrics", expr=em, cte_type="subquery"),
    }
    return query


def _dw_retention_metric():
    return ExperimentRetentionMetric(
        start_event=ExperimentDataWarehouseNode(
            table_name="events_dw",
            events_join_key="properties.$user_id",
            data_warehouse_join_key="userid",
            timestamp_field="ds",
            math=ExperimentMetricMathType.TOTAL,
        ),
        completion_event=EventsNode(event="returned"),
        retention_window_start=1,
        retention_window_end=7,
        retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
        start_handling=StartHandling.FIRST_SEEN,
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="plan", type=BreakdownType.DATA_WAREHOUSE)]),
    )


def _retention_metric(breakdown_limit=None):
    return ExperimentRetentionMetric(
        start_event=EventsNode(event="signed_up"),
        completion_event=EventsNode(event="returned"),
        retention_window_start=1,
        retention_window_end=7,
        retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
        start_handling=StartHandling.FIRST_SEEN,
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")], breakdown_limit=breakdown_limit),
    )


def _retention_query() -> ast.SelectQuery:
    # Stand-in for the retention shape: start_events (GROUP BY entity) -> completion_events ->
    # entity_metrics (joins exposures + start + completion).
    query = parse_select("SELECT variant FROM entity_metrics")
    assert isinstance(query, ast.SelectQuery)
    se = parse_select(
        "SELECT exposures.entity_id AS entity_id, min(timestamp) AS start_timestamp "
        "FROM events INNER JOIN exposures ON entity_id = exposures.entity_id GROUP BY exposures.entity_id"
    )
    ce = parse_select("SELECT entity_id, timestamp AS completion_timestamp FROM events")
    em = parse_select(
        "SELECT exposures.entity_id AS entity_id, exposures.variant AS variant, max(value) AS value "
        "FROM exposures INNER JOIN start_events ON exposures.entity_id = start_events.entity_id "
        "LEFT JOIN completion_events ON exposures.entity_id = completion_events.entity_id "
        "GROUP BY exposures.entity_id, exposures.variant"
    )
    assert isinstance(se, ast.SelectQuery) and isinstance(ce, ast.SelectQuery) and isinstance(em, ast.SelectQuery)
    query.ctes = {
        "start_events": ast.CTE(name="start_events", expr=se, cte_type="subquery"),
        "completion_events": ast.CTE(name="completion_events", expr=ce, cte_type="subquery"),
        "entity_metrics": ast.CTE(name="entity_metrics", expr=em, cte_type="subquery"),
    }
    return query


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
        # count() DESC plus a breakdown-value tiebreak keeps the cutoff deterministic on ties
        assert in_top.right.order_by is not None
        assert [o.order for o in in_top.right.order_by] == ["DESC", "ASC"]
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


class TestMetricBreakdownInjectorMean:
    def test_breakdown_read_from_metric_event(self):
        metric = _mean_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _mean_query()

        injector.inject_mean_breakdown_columns(query)

        assert query.ctes is not None
        me_cte = query.ctes["metric_events"]
        assert isinstance(me_cte, ast.CTE) and isinstance(me_cte.expr, ast.SelectQuery)
        me_aliases = [c.alias for c in me_cte.expr.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in me_aliases

    def test_entity_metrics_uses_first_touch_argmin_from_metric_event(self):
        metric = _mean_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _mean_query()

        injector.inject_mean_breakdown_columns(query)

        expr = _entity_metrics_aliases(query)["breakdown_value_1"]
        # argMin(metric_events.breakdown_value_1, metric_events.timestamp) — first metric event per user.
        assert isinstance(expr, ast.Call)
        assert expr.name == "argMin"
        assert expr.args[0] == ast.Field(chain=["metric_events", "breakdown_value_1"])
        assert expr.args[1] == ast.Field(chain=["metric_events", "timestamp"])

    def test_final_select_applies_top_n_other_limit(self):
        metric = _mean_metric(breakdown_limit=3)
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _mean_query()

        injector.inject_mean_breakdown_columns(query)

        final_alias = next(c for c in query.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        assert isinstance(final_alias.expr, ast.Call)
        assert final_alias.expr.name == "if"
        other = final_alias.expr.args[2]
        assert isinstance(other, ast.Constant)
        assert other.value == "$$_posthog_breakdown_other_$$"

    def test_session_property_reads_breakdown_in_by_session_cte(self):
        metric = _mean_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _session_mean_query()

        injector.inject_mean_breakdown_columns(query)

        assert query.ctes is not None
        # Breakdown is read off raw events in the by-session layer (deduped via any()), since the
        # metric_events CTE there has no access to raw event properties.
        mebs_cte = query.ctes["metric_events_by_session"]
        assert isinstance(mebs_cte, ast.CTE) and isinstance(mebs_cte.expr, ast.SelectQuery)
        mebs_aliases = [c.alias for c in mebs_cte.expr.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in mebs_aliases

    def test_session_property_first_touch_uses_first_event_timestamp(self):
        metric = _mean_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _session_mean_query()

        injector.inject_mean_breakdown_columns(query)

        expr = _entity_metrics_aliases(query)["breakdown_value_1"]
        # First-touch over the session's first_event_timestamp (carried up from the by-session layer).
        assert isinstance(expr, ast.Call)
        assert expr.name == "argMin"
        assert expr.args[0] == ast.Field(chain=["metric_events", "breakdown_value_1"])
        assert expr.args[1] == ast.Field(chain=["metric_events", "first_event_timestamp"])

    def test_data_warehouse_breakdown_reads_warehouse_column(self):
        metric = _dw_mean_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _mean_query()

        injector.inject_mean_breakdown_columns(query)

        assert query.ctes is not None
        me_cte = query.ctes["metric_events"]
        assert isinstance(me_cte, ast.CTE) and isinstance(me_cte.expr, ast.SelectQuery)
        bd = next(c for c in me_cte.expr.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        # A DW breakdown is a direct warehouse column (the metric_events CTE reads FROM the warehouse
        # table), so it must read bare `plan`, NOT be wrapped in an event `properties` chain.
        coalesce_call = bd.expr
        assert isinstance(coalesce_call, ast.Call) and coalesce_call.name == "coalesce"
        to_string = coalesce_call.args[0]
        assert isinstance(to_string, ast.Call) and to_string.name == "toString"
        field = to_string.args[0]
        assert isinstance(field, ast.Field)
        assert field.chain == ["plan"]


class TestMetricBreakdownInjectorRetention:
    def test_breakdown_read_from_start_event(self):
        metric = _retention_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _retention_query()

        injector.inject_retention_breakdown_columns(query)

        assert query.ctes is not None
        se_cte = query.ctes["start_events"]
        assert isinstance(se_cte, ast.CTE) and isinstance(se_cte.expr, ast.SelectQuery)
        se_aliases = [c.alias for c in se_cte.expr.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in se_aliases

    def test_entity_metrics_first_touch_from_start_event(self):
        metric = _retention_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _retention_query()

        injector.inject_retention_breakdown_columns(query)

        expr = _entity_metrics_aliases(query)["breakdown_value_1"]
        # Carried from the start_events CTE (first-touch attributed there over start_timestamp).
        assert isinstance(expr, ast.Field)
        assert expr.chain == ["start_events", "breakdown_value_1"]

    def test_start_events_uses_argmin_over_start_timestamp(self):
        metric = _retention_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _retention_query()

        injector.inject_retention_breakdown_columns(query)

        assert query.ctes is not None
        se_cte = query.ctes["start_events"]
        assert isinstance(se_cte, ast.CTE) and isinstance(se_cte.expr, ast.SelectQuery)
        bd = next(c for c in se_cte.expr.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        # start_events groups by entity, so the breakdown is deduped first-touch via argMin.
        assert isinstance(bd.expr, ast.Call)
        assert bd.expr.name == "argMin"
        assert bd.expr.args[1] == ast.Field(chain=["timestamp"])

    def test_final_select_applies_top_n_other_limit(self):
        metric = _retention_metric(breakdown_limit=3)
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _retention_query()

        injector.inject_retention_breakdown_columns(query)

        final_alias = next(c for c in query.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        assert isinstance(final_alias.expr, ast.Call)
        assert final_alias.expr.name == "if"
        other = final_alias.expr.args[2]
        assert isinstance(other, ast.Constant)
        assert other.value == "$$_posthog_breakdown_other_$$"

    def test_data_warehouse_breakdown_reads_warehouse_column(self):
        metric = _dw_retention_metric()
        injector = MetricBreakdownInjector(metric.breakdownFilter.breakdowns, metric)
        query = _retention_query()

        injector.inject_retention_breakdown_columns(query)

        assert query.ctes is not None
        se_cte = query.ctes["start_events"]
        assert isinstance(se_cte, ast.CTE) and isinstance(se_cte.expr, ast.SelectQuery)
        bd = next(c for c in se_cte.expr.select if isinstance(c, ast.Alias) and c.alias == "breakdown_value_1")
        # A DW breakdown reads bare `plan` from the warehouse table (no `properties` wrapper).
        argmin_call = bd.expr
        assert isinstance(argmin_call, ast.Call) and argmin_call.name == "argMin"
        coalesce_call = argmin_call.args[0]
        assert isinstance(coalesce_call, ast.Call) and coalesce_call.name == "coalesce"
        to_string = coalesce_call.args[0]
        assert isinstance(to_string, ast.Call) and to_string.name == "toString"
        field = to_string.args[0]
        assert isinstance(field, ast.Field)
        assert field.chain == ["plan"]
