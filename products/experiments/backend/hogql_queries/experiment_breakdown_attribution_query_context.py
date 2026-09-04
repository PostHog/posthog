"""
Context for experiment breakdown attribution on metric events.

This carries the breakdown configuration for a metric and resolves the pure,
AST-free decisions that attribution needs: the aggregation function and step
columns for the configured ``breakdownAttributionType``, the breakdown value
aliases, and the top-N limit.

Unlike ``BreakdownInjector`` (which attributes the breakdown from the exposure
event), this attributes the breakdown off the *metric* event, aligning
experiment funnel breakdowns with how insights funnels behave.

Scope: funnel metrics only, for now. The context and the builder replace the
old injector once every metric type migrates to metric-event breakdowns.
"""

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    StepOrderValue,
)

from posthog.hogql.constants import BREAKDOWN_VALUES_LIMIT

from posthog.dataclasses import frozen


@frozen
class AttributionResolution:
    """The aggregation function and step columns that attribution reads from.

    ``aggregation_fn`` is a ClickHouse conditional aggregate (``argMinIf`` or
    ``argMaxIf``). ``step_indexes`` are 1-based funnel step columns (``step_1``
    is the first metric step; ``step_0`` is the exposure step and is never an
    attribution target).
    """

    aggregation_fn: str
    step_indexes: list[int]


@frozen
class ExperimentBreakdownAttributionContext:
    """Breakdown configuration and pure attribution resolution for a metric.

    Holds no AST. The builder takes this context and constructs the query.
    """

    breakdowns: tuple[Breakdown, ...]
    metric: ExperimentFunnelMetric

    def has_breakdown(self) -> bool:
        return len(self.breakdowns) > 0

    def has_data_warehouse_step(self) -> bool:
        return any(isinstance(step, ExperimentDataWarehouseNode) for step in self.metric.series)

    def breakdown_aliases(self) -> list[str]:
        return [f"breakdown_value_{i + 1}" for i in range(len(self.breakdowns))]

    def breakdown_limit(self) -> int:
        """Top-N cap on breakdown values; mirrors insights' default of BREAKDOWN_VALUES_LIMIT."""
        breakdown_filter = self.metric.breakdownFilter
        limit = breakdown_filter.breakdown_limit if breakdown_filter else None
        return limit or BREAKDOWN_VALUES_LIMIT

    def resolve_attribution(self) -> AttributionResolution:
        """Resolve the aggregation function and step columns for the attribution mode.

        In experiment funnels ``step_0`` is the exposure event and the metric series
        events are ``step_1 .. step_N`` (N = len(series)). The breakdown is read off
        the metric events, so attribution targets those steps, never the exposure step.

        - first_touch: argMinIf across all metric steps (step_1..step_N), so the value comes
          from the user's earliest metric event, whichever step it matched.
        - last_touch: argMaxIf across all metric steps, so a user who drops off before the last
          step still gets the value from their latest metric event.
        - step (ordered): argMinIf from ``breakdownAttributionValue`` (0-indexed into the
          series, mapped to the corresponding step column step_{value + 1}).
        - step (unordered, "Any step"): argMinIf across all metric step columns, since an
          unordered funnel has no fixed step position and any matching step attributes.

        all_events is not a single-value attribution: it buckets a unit under every distinct
        breakdown value it emitted, so it needs a group-array fan-out this resolver cannot
        express. It is rejected until the builder supports that fan-out.
        """
        attribution = self.metric.breakdownAttributionType or BreakdownAttributionType.FIRST_TOUCH
        num_metric_steps = len(self.metric.series)
        is_unordered = self.metric.funnel_order_type == StepOrderValue.UNORDERED
        all_metric_steps = list(range(1, num_metric_steps + 1))

        if attribution == BreakdownAttributionType.ALL_EVENTS:
            raise NotImplementedError("all-events breakdown attribution is not yet supported for experiment funnels")
        if attribution == BreakdownAttributionType.LAST_TOUCH:
            return AttributionResolution(aggregation_fn="argMaxIf", step_indexes=all_metric_steps)
        if attribution == BreakdownAttributionType.STEP:
            if is_unordered:
                # "Any step": the stored index is ignored, attribute from the earliest matching step.
                return AttributionResolution(aggregation_fn="argMinIf", step_indexes=all_metric_steps)
            series_index = self.metric.breakdownAttributionValue
            if series_index is None or series_index < 0 or series_index >= num_metric_steps:
                raise ValueError(
                    f"breakdownAttributionValue must be in [0, {num_metric_steps - 1}] for step attribution, "
                    f"got {series_index}"
                )
            return AttributionResolution(aggregation_fn="argMinIf", step_indexes=[series_index + 1])
        return AttributionResolution(aggregation_fn="argMinIf", step_indexes=all_metric_steps)
