"""
Metric-events precomputation for one experiment query: whether the metric can read
from experiment_metric_events_preaggregated, and the lazy-computation builds that fill it.

The per-source build query and read CTE live in metric_source_precompute; this module
decides when they apply and runs the builds.
"""

from datetime import datetime, timedelta
from typing import Optional

import posthoganalytics
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentWarehouseNativeNode,
)

from posthog.hogql import ast

from posthog.constants import EXPERIMENTS_RATIO_METRIC_EVENTS_PREAGGREGATION_FEATURE_FLAG_KEY
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.experiments.backend.hogql_queries.base_query_utils import (
    conversion_window_to_seconds,
    experiment_window_end,
    is_session_property_metric,
)
from products.experiments.backend.hogql_queries.experiment_metric_values import get_conversion_window_seconds
from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder
from products.experiments.backend.hogql_queries.precompute_policy import (
    METRIC_EVENTS_MAX_WINDOW_EXTENSION_SECONDS,
    experiment_precompute_ttl_schedule,
)
from products.experiments.backend.models.experiment import Experiment


@frozen
class RatioPrecomputeResults:
    """The metric-events build result of each ratio side."""

    numerator: LazyComputationResult
    denominator: LazyComputationResult

    @property
    def ready(self) -> bool:
        return self.numerator.ready and self.denominator.ready

    @property
    def capacity_rejected(self) -> bool:
        return self.numerator.capacity_rejected or self.denominator.capacity_rejected


@frozen
class MetricEventsPrecompute:
    """The metric-events precompute decisions and builds for one experiment query."""

    team: Team
    experiment: Experiment
    as_of: datetime
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric
    group_type_index: Optional[int]
    has_breakdowns: bool
    cuped_enabled: bool
    is_data_warehouse_query: bool

    def ensure_precomputed(self, builder: ExperimentQueryBuilder) -> LazyComputationResult:
        """
        Ensures lazy-computed metric event data exists for this experiment.

        Stores one row per matching event in the experiment_metric_events_preaggregated
        table: funnel metrics store step indicators, mean metrics the per-event value.
        """
        query_string, placeholders = builder.get_metric_events_query_for_precomputation()
        return self._ensure_build(builder, query_string, placeholders)

    def ensure_ratio_precomputed(self, builder: ExperimentQueryBuilder) -> RatioPrecomputeResults:
        """One build per side. Each side is a mean-shaped build of its source."""
        queries = builder.get_ratio_metric_events_queries_for_precomputation()
        return RatioPrecomputeResults(
            numerator=self._ensure_build(builder, *queries.numerator),
            denominator=self._ensure_build(builder, *queries.denominator),
        )

    def _ensure_build(
        self, builder: ExperimentQueryBuilder, query_string: str, placeholders: dict[str, ast.Expr]
    ) -> LazyComputationResult:
        if not self.experiment.start_date:
            raise ValidationError("Experiment must have a start date for lazy computation")

        date_from = self.experiment.start_date
        date_to = experiment_window_end(self.experiment, self.as_of)

        # Extend the time range past the experiment end, because metric events can occur after
        # it: within the conversion window, and for retention also within the retention window
        # (a completion can land up to retention_window_end after a start event, which itself
        # can land up to conversion_window after the last exposure).
        extension_seconds = builder.get_metric_events_window_extension_seconds()
        if extension_seconds > 0:
            date_to = date_to + timedelta(seconds=extension_seconds)

        return ensure_precomputed(
            team=self.team,
            insert_query=query_string,
            time_range_start=date_from,
            time_range_end=date_to,
            ttl_seconds=experiment_precompute_ttl_schedule(self.team.timezone),
            table=LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED,
            placeholders=placeholders,
            sentinel_placeholders={"experiment_date_to"},
            end_is_data_horizon=True,
            spill_to_disk=True,
        )

    @property
    def applicable(self) -> bool:
        return self.ineligibility_reason() is None

    def ineligibility_reason(self) -> Optional[str]:
        """
        Why metric-events precompute cannot serve this metric, or None when it can.
        Supported: ordered funnels, mean metrics with numeric math (count/sum/avg/min/max)
        or ID-valued math (unique users / unique sessions), ratio metrics whose two sides
        each pass the mean rules, and retention metrics, in all cases without breakdowns,
        CUPED, or data warehouse sources.

        Tagged on the read as `experiment_metric_events_skip_reason`, the metric-events
        counterpart of `experiment_precompute_skip_reason`, so query-log analysis can split
        the not_applicable path by cause. Values are part of that reporting contract.
        """
        if self.has_breakdowns:
            return "breakdown"
        # CUPED extends the metric scan back by lookback_days for the pre-exposure covariate,
        # but the precomputed metric_events table covers only the experiment window.
        if self.cuped_enabled:
            return "cuped"
        if self.is_data_warehouse_query:
            return "data_warehouse"
        if isinstance(self.metric, ExperimentFunnelMetric):
            if (self.metric.funnel_order_type or "ordered") == "ordered":
                return None
            return "funnel_order_type"
        if isinstance(self.metric, ExperimentMeanMetric):
            return self._source_ineligibility_reason(self.metric.source)
        if isinstance(self.metric, ExperimentRatioMetric):
            if not self.ratio_flag_enabled():
                return "ratio_flag_off"
            # Each side is built and read like a mean metric on that source, so the
            # per-source rules apply to both.
            return self._source_ineligibility_reason(self.metric.numerator) or self._source_ineligibility_reason(
                self.metric.denominator
            )
        if isinstance(self.metric, ExperimentRetentionMetric):
            if not isinstance(self.metric.start_event, (EventsNode, ActionsNode)) or not isinstance(
                self.metric.completion_event, (EventsNode, ActionsNode)
            ):
                return "non_event_source"
            extension_seconds = get_conversion_window_seconds(self.metric) + conversion_window_to_seconds(
                self.metric.retention_window_end, self.metric.retention_window_unit
            )
            if extension_seconds <= METRIC_EVENTS_MAX_WINDOW_EXTENSION_SECONDS:
                return None
            return "retention_window"

    def _source_ineligibility_reason(
        self, source: EventsNode | ActionsNode | ExperimentDataWarehouseNode | ExperimentWarehouseNativeNode
    ) -> Optional[str]:
        """The per-source rules for a mean-shaped build: a mean metric's source or either ratio side."""
        if not isinstance(source, (EventsNode, ActionsNode)):
            return "non_event_source"
        # Session-property means aggregate via a per-session dedup CTE that the
        # precomputed table can't feed. Unique-group math is excluded because
        # the build INSERT can't resolve $group_N (MATERIALIZED on
        # sharded_events), and HogQL math because user expressions are arbitrary.
        if is_session_property_metric(source):
            return "session_property_math"
        math_type = getattr(source, "math", None) or ExperimentMetricMathType.TOTAL
        # Numeric math types are safe because the build query stores the same
        # coalesced per-event float regardless of math type, and the math is
        # applied at read time by build_value_aggregation_expr on both paths.
        if math_type in (
            ExperimentMetricMathType.TOTAL,
            ExperimentMetricMathType.SUM,
            ExperimentMetricMathType.AVG,
            ExperimentMetricMathType.MIN,
            ExperimentMetricMathType.MAX,
        ):
            return None
        # unique_session counts distinct session_id, which every mean build stores.
        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            return None
        # dau counts distinct entity_id, which is the person id only when the
        # experiment is person-keyed. Group experiments never reach precompute,
        # but keep the guard explicit in case that exclusion is ever lifted.
        if math_type == ExperimentMetricMathType.DAU:
            return None if self.group_type_index is None else "group_math"
        return "unsupported_math"

    def ratio_flag_enabled(self) -> bool:
        """
        Kill switch for ratio metric-events precomputation, independent of the other
        metric types. Default-off and fail-safe: an absent or unevaluable flag keeps ratio
        metric events on the direct scan while exposures and the other types keep their
        precomputed tables.
        """
        return bool(
            posthoganalytics.feature_enabled(
                EXPERIMENTS_RATIO_METRIC_EVENTS_PREAGGREGATION_FEATURE_FLAG_KEY,
                str(self.team.uuid),
                groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
                group_properties={
                    "organization": {"id": str(self.team.organization_id)},
                    "project": {"id": str(self.team.id), "uuid": str(self.team.uuid)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
