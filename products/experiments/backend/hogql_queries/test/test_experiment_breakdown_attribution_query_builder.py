from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    BreakdownFilter,
    EventsNode,
    ExperimentFunnelMetric,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.experiment_breakdown_attribution_query_builder import (
    ExperimentBreakdownAttributionQueryBuilder,
)
from products.experiments.backend.hogql_queries.experiment_breakdown_attribution_query_context import (
    ExperimentBreakdownAttributionContext,
)


def _funnel_metric(
    attribution: BreakdownAttributionType | None = None,
    attribution_value: int | None = None,
    num_steps: int = 2,
    funnel_order_type: StepOrderValue | None = None,
    properties: tuple[str, ...] = ("$browser",),
    breakdown_limit: int | None = None,
) -> ExperimentFunnelMetric:
    return ExperimentFunnelMetric(
        series=[EventsNode(event=f"step_{i}") for i in range(num_steps)],
        breakdownFilter=BreakdownFilter(
            breakdowns=[Breakdown(property=p) for p in properties], breakdown_limit=breakdown_limit
        ),
        breakdownAttributionType=attribution,
        breakdownAttributionValue=attribution_value,
        funnel_order_type=funnel_order_type,
    )


def _builder(metric: ExperimentFunnelMetric) -> ExperimentBreakdownAttributionQueryBuilder:
    assert metric.breakdownFilter is not None and metric.breakdownFilter.breakdowns is not None
    context = ExperimentBreakdownAttributionContext(
        breakdowns=tuple(metric.breakdownFilter.breakdowns),
        metric=metric,
    )
    return ExperimentBreakdownAttributionQueryBuilder(context)


def _unwrap_attribution(expr: ast.Expr) -> ast.Call:
    """Users with no attribution event get the null label, so the attribution agg is nested in an
    ``if(countIf(cond) = 0, null_label, agg(...))``. Return the inner argMin/argMax call."""
    assert isinstance(expr, ast.Call) and expr.name == "if"
    attributed = expr.args[2]
    assert isinstance(attributed, ast.Call)
    return attributed


def _split_condition(condition: ast.Expr) -> tuple[ast.Expr, ast.Expr]:
    """Attribution matches a step AND requires a breakdown value. Return both halves."""
    assert isinstance(condition, ast.And) and len(condition.exprs) == 2
    return condition.exprs[0], condition.exprs[1]


def _compared_fields(condition: ast.Expr) -> set[str]:
    """Field names on the left of a comparison, or of an OR of comparisons."""
    comparisons = condition.exprs if isinstance(condition, ast.Or) else [condition]
    return {
        c.left.chain[0]
        for c in comparisons
        if isinstance(c, ast.CompareOperation) and isinstance(c.left, ast.Field) and isinstance(c.left.chain[0], str)
    }


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


class TestExperimentBreakdownAttributionQueryBuilder:
    # step_0 is the exposure step; metric series events are step_1..step_N. First and last touch
    # read across every metric step, so a user who never reached the last step still gets the value
    # from their earliest or latest metric event instead of falling into the null bucket.
    @parameterized.expand(
        [
            ("first_touch", BreakdownAttributionType.FIRST_TOUCH, None, "argMinIf", {"step_1", "step_2"}),
            ("last_touch", BreakdownAttributionType.LAST_TOUCH, None, "argMaxIf", {"step_1", "step_2"}),
            ("step_series_0", BreakdownAttributionType.STEP, 0, "argMinIf", {"step_1"}),
            ("step_series_1", BreakdownAttributionType.STEP, 1, "argMinIf", {"step_2"}),
            ("default_none", None, None, "argMinIf", {"step_1", "step_2"}),
        ]
    )
    def test_optimized_attribution_modes(self, _name, attribution, value, expected_agg, expected_steps):
        metric = _funnel_metric(attribution=attribution, attribution_value=value, num_steps=2)
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        expr = _unwrap_attribution(_entity_metrics_aliases(query)["breakdown_value_1"])
        assert expr.name == expected_agg
        # Ordering on timestamp alone lets tied events be picked per column, so a user's breakdown
        # values could come from different rows. The uuid makes the pick the same for every column.
        assert expr.args[1] == ast.Tuple(exprs=[ast.Field(chain=["timestamp"]), ast.Field(chain=["uuid"])])
        steps, _ = _split_condition(expr.args[2])
        assert _compared_fields(steps) == expected_steps

    def test_unattributed_users_get_null_label_not_empty_string(self):
        # argMinIf over zero matching rows returns "", which the UI labels "None" like the null
        # label but counts as its own bucket, so it must map to the null label instead.
        metric = _funnel_metric(attribution=BreakdownAttributionType.FIRST_TOUCH, num_steps=2)
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        expr = _entity_metrics_aliases(query)["breakdown_value_1"]
        assert isinstance(expr, ast.Call) and expr.name == "if"
        null_label = expr.args[1]
        assert isinstance(null_label, ast.Constant) and null_label.value == BREAKDOWN_NULL_STRING_LABEL

    def test_unordered_any_step_attributes_across_all_steps(self):
        # For unordered funnels "Any step" (step attribution) must match a metric event at any step,
        # not just step_1, or a user who completed through a later series event lands unattributed.
        metric = _funnel_metric(
            attribution=BreakdownAttributionType.STEP,
            attribution_value=0,
            num_steps=2,
            funnel_order_type=StepOrderValue.UNORDERED,
        )
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        steps, _ = _split_condition(_unwrap_attribution(_entity_metrics_aliases(query)["breakdown_value_1"]).args[2])
        assert _compared_fields(steps) == {"step_1", "step_2"}

    @parameterized.expand([("one_breakdown", ("$browser",)), ("two_breakdowns", ("$browser", "$os"))])
    def test_attribution_skips_events_without_a_breakdown_value(self, _name, properties):
        # The property is coalesced to the null label before attribution, so without this filter an
        # event missing the property would win on timestamp and hide a later event with a real
        # value. All aliases share one condition, so a user's values come from the same event.
        metric = _funnel_metric(attribution=BreakdownAttributionType.FIRST_TOUCH, properties=properties)
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        aliases = _entity_metrics_aliases(query)
        conditions = [
            _split_condition(_unwrap_attribution(aliases[f"breakdown_value_{i + 1}"]).args[2])[1]
            for i in range(len(properties))
        ]
        assert all(c == conditions[0] for c in conditions)
        shared = conditions[0]
        assert _compared_fields(shared) == {f"breakdown_value_{i + 1}" for i in range(len(properties))}
        comparisons = shared.exprs if isinstance(shared, ast.Or) else [shared]
        assert all(
            isinstance(c, ast.CompareOperation)
            and c.op == ast.CompareOperationOp.NotEq
            and isinstance(c.right, ast.Constant)
            and c.right.value == BREAKDOWN_NULL_STRING_LABEL
            for c in comparisons
        )

    def test_breakdown_read_from_metric_event_in_base_events(self):
        metric = _funnel_metric(attribution=BreakdownAttributionType.FIRST_TOUCH)
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        assert query.ctes is not None
        base_cte = query.ctes["base_events"]
        assert isinstance(base_cte, ast.CTE) and isinstance(base_cte.expr, ast.SelectQuery)
        base_columns = {c.alias: c.expr for c in base_cte.expr.select if isinstance(c, ast.Alias)}
        assert "breakdown_value_1" in base_columns
        # A property set to "" reads as no value: the UI labels it "None" like a missing property,
        # so leaving it distinct would split the no-value users across two identical rows.
        read = base_columns["breakdown_value_1"]
        assert isinstance(read, ast.Call) and read.name == "coalesce"
        assert isinstance(read.args[0], ast.Call) and read.args[0].name == "nullIf"
        empty, fallback = read.args[0].args[1], read.args[1]
        assert isinstance(empty, ast.Constant) and empty.value == ""
        assert isinstance(fallback, ast.Constant) and fallback.value == BREAKDOWN_NULL_STRING_LABEL

    def test_breakdown_added_to_final_select_and_group_by(self):
        metric = _funnel_metric()
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

        select_aliases = [c.alias for c in query.select if isinstance(c, ast.Alias)]
        assert "breakdown_value_1" in select_aliases
        # The limit relabel groups by the output alias (the relabeled column), not the raw
        # entity_metrics column, so "Other" rows merge.
        assert query.group_by is not None
        assert ast.Field(chain=["breakdown_value_1"]) in query.group_by

    def test_final_breakdown_column_applies_top_n_other_relabel(self):
        metric = _funnel_metric(breakdown_limit=3)
        builder = _builder(metric)
        query = _optimized_query()

        builder.inject_funnel_breakdown_columns_optimized(query)

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
        # Rank only users who reach the result: a bucket of users the final SELECT or the runner
        # drops would otherwise take a top-N slot and then contribute no row.
        assert isinstance(in_top.right.where, ast.And)
        variant_present, not_multiple = in_top.right.where.exprs
        assert isinstance(variant_present, ast.Call) and variant_present.name == "notEmpty"
        assert isinstance(not_multiple, ast.CompareOperation)
        assert not_multiple.op == ast.CompareOperationOp.NotEq
        assert isinstance(not_multiple.right, ast.Constant) and not_multiple.right.value == MULTIPLE_VARIANT_KEY
        other = final_alias.expr.args[2]
        assert isinstance(other, ast.Constant)
        assert other.value == "$$_posthog_breakdown_other_$$"

    def test_step_attribution_out_of_range_raises(self):
        metric = _funnel_metric(attribution=BreakdownAttributionType.STEP, attribution_value=5, num_steps=2)
        builder = _builder(metric)
        query = _optimized_query()

        try:
            builder.inject_funnel_breakdown_columns_optimized(query)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_all_events_attribution_is_rejected(self):
        # all-events buckets a unit under every distinct breakdown value it emitted, so it needs a
        # group-array fan-out this resolver cannot express. Mapping it to first-touch would silently
        # collapse those buckets and report wrong conversion counts, so it must raise until supported.
        metric = _funnel_metric(attribution=BreakdownAttributionType.ALL_EVENTS, num_steps=2)
        builder = _builder(metric)
        query = _optimized_query()

        try:
            builder.inject_funnel_breakdown_columns_optimized(query)
            raise AssertionError("expected NotImplementedError")
        except NotImplementedError:
            pass
