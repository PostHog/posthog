import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import time_machine
from posthog.test.base import BaseTest, QueryMatchingTest

from parameterized import param, parameterized

from posthog.schema import (
    ActionsNode,
    Breakdown,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentExposureNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentMetricOutlierHandling,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    IntervalType,
    MultipleVariantHandling,
    StartHandling,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.actions.backend.models.action import Action
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationQuery,
    LazyComputationTable,
    compute_query_hash,
)
from products.experiments.backend.hogql_queries.base_query_utils import analysis_window
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder
from products.experiments.backend.hogql_queries.experiment_query_context import ExperimentPrecomputationContext

NOW = datetime(2024, 1, 20, 12, 0, 0, tzinfo=UTC)
EXPERIMENT_START = datetime(2024, 1, 1, tzinfo=UTC)

EXPOSURE_JOB_IDS = ["00000000-0000-0000-0000-0000000000e1", "00000000-0000-0000-0000-0000000000e2"]
METRIC_EVENTS_JOB_IDS = ["00000000-0000-0000-0000-0000000000a1"]

EXPOSURES_TABLE = LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED.value
METRIC_EVENTS_TABLE = LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED.value
BOTH_TABLES = frozenset({EXPOSURES_TABLE, METRIC_EVENTS_TABLE})

Output = Literal["query", "exposure_timeseries", "daily_exposures", "exposures_write", "metric_events_write"]
Metric = ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric

PURCHASE = EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
PAGEVIEW = EventsNode(event="$pageview")
REVENUE_TABLE = ExperimentDataWarehouseNode(
    table_name="revenue",
    timestamp_field="ds",
    events_join_key="properties.$user_id",
    data_warehouse_join_key="userid",
    math=ExperimentMetricMathType.SUM,
    math_property="amount",
)
SEVEN_DAYS: dict[str, Any] = {"conversion_window": 7, "conversion_window_unit": FunnelConversionWindowTimeUnit.DAY}
RETENTION_WINDOW: dict[str, Any] = {
    "retention_window_start": 1,
    "retention_window_end": 7,
    "retention_window_unit": FunnelConversionWindowTimeUnit.DAY,
    "start_handling": StartHandling.FIRST_SEEN,
}
BROWSER = [Breakdown(property="$browser")]


def _mean_on_action(team: Team) -> ExperimentMeanMetric:
    action = Action.objects.create(team=team, name="purchase", steps_json=[{"event": "purchase"}])
    return ExperimentMeanMetric(source=ActionsNode(id=action.id))


def _funnel(**kwargs: Any) -> ExperimentFunnelMetric:
    return ExperimentFunnelMetric(series=[PAGEVIEW, EventsNode(event="purchase")], **kwargs)


def _retention(start_event: EventsNode | ExperimentExposureNode = PAGEVIEW, **kwargs: Any) -> ExperimentRetentionMetric:
    return ExperimentRetentionMetric(
        start_event=start_event, completion_event=EventsNode(event="purchase"), **RETENTION_WINDOW, **kwargs
    )


CASES = [
    param("mean_events", metric=ExperimentMeanMetric(source=PURCHASE)),
    param("mean_action", metric=_mean_on_action),
    param(
        "mean_session_property",
        metric=ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.SUM,
                math_property="$session_duration",
                math_property_type="session_properties",
            )
        ),
    ),
    param("mean_data_warehouse", metric=ExperimentMeanMetric(source=REVENUE_TABLE)),
    param(
        "mean_winsorized",
        metric=ExperimentMeanMetric(
            source=PURCHASE, lower_bound_percentile=0.05, upper_bound_percentile=0.95, ignore_zeros=True
        ),
    ),
    param("mean_threshold", metric=ExperimentMeanMetric(source=PURCHASE, threshold=100)),
    param("mean_cuped", metric=ExperimentMeanMetric(source=PURCHASE, **SEVEN_DAYS), cuped=True),
    param("mean_breakdown", metric=ExperimentMeanMetric(source=PURCHASE), breakdowns=BROWSER),
    param(
        "mean_breakdown_ignores_exposure_job_ids",
        metric=ExperimentMeanMetric(source=PURCHASE),
        breakdowns=BROWSER,
        exposure_job_ids=EXPOSURE_JOB_IDS,
    ),
    param("mean_group_aggregation", metric=ExperimentMeanMetric(source=PURCHASE), entity_key="$group_0"),
    param("mean_maturity", metric=ExperimentMeanMetric(source=PURCHASE, **SEVEN_DAYS), matured=True),
    param(
        "mean_maturity_precomputed_exposures",
        metric=ExperimentMeanMetric(source=PURCHASE, **SEVEN_DAYS),
        matured=True,
        exposure_job_ids=EXPOSURE_JOB_IDS,
        reads=frozenset({EXPOSURES_TABLE}),
    ),
    param(
        "mean_precomputed",
        metric=ExperimentMeanMetric(source=PURCHASE, **SEVEN_DAYS),
        exposure_job_ids=EXPOSURE_JOB_IDS,
        metric_events_job_ids=METRIC_EVENTS_JOB_IDS,
        reads=BOTH_TABLES,
    ),
    param("ratio_events", metric=ExperimentRatioMetric(numerator=PURCHASE, denominator=PAGEVIEW)),
    param(
        "ratio_data_warehouse_numerator", metric=ExperimentRatioMetric(numerator=REVENUE_TABLE, denominator=PAGEVIEW)
    ),
    param(
        "ratio_winsorized",
        metric=ExperimentRatioMetric(
            numerator=PURCHASE,
            denominator=PAGEVIEW,
            numerator_outlier_handling=ExperimentMetricOutlierHandling(upper_bound_percentile=0.99),
        ),
    ),
    param(
        "ratio_breakdown",
        metric=ExperimentRatioMetric(numerator=PURCHASE, denominator=PAGEVIEW),
        breakdowns=BROWSER,
    ),
    param("funnel_ordered", metric=_funnel()),
    param("funnel_unordered", metric=_funnel(funnel_order_type=StepOrderValue.UNORDERED)),
    param(
        "funnel_first_seen_variant",
        metric=_funnel(),
        multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN,
    ),
    param("funnel_cuped", metric=_funnel(), cuped=True),
    param("funnel_activation_drops_cuped", metric=_funnel(), activation=True, cuped=True),
    param("funnel_data_warehouse_steps", metric=ExperimentFunnelMetric(series=[PAGEVIEW, REVENUE_TABLE])),
    param("funnel_maturity", metric=_funnel(**SEVEN_DAYS), matured=True),
    param(
        "funnel_precomputed_exposures",
        metric=_funnel(**SEVEN_DAYS),
        exposure_job_ids=EXPOSURE_JOB_IDS,
        reads=frozenset({EXPOSURES_TABLE}),
    ),
    param(
        "funnel_precomputed",
        metric=_funnel(**SEVEN_DAYS),
        exposure_job_ids=EXPOSURE_JOB_IDS,
        metric_events_job_ids=METRIC_EVENTS_JOB_IDS,
        reads=BOTH_TABLES,
    ),
    param(
        "funnel_metric_events_job_ids_without_exposure_job_ids",
        metric=_funnel(**SEVEN_DAYS),
        metric_events_job_ids=METRIC_EVENTS_JOB_IDS,
    ),
    param("retention_events", metric=_retention()),
    param("retention_exposure_start", metric=_retention(start_event=ExperimentExposureNode())),
    param("retention_maturity", metric=_retention(**SEVEN_DAYS), matured=True),
    param(
        "retention_exposure_start_maturity",
        metric=_retention(start_event=ExperimentExposureNode()),
        matured=True,
    ),
    param("retention_breakdown", metric=_retention(), breakdowns=BROWSER),
    param(
        "retention_precomputed",
        metric=_retention(**SEVEN_DAYS),
        exposure_job_ids=EXPOSURE_JOB_IDS,
        metric_events_job_ids=METRIC_EVENTS_JOB_IDS,
        reads=BOTH_TABLES,
    ),
    param("exposure_timeseries", output="exposure_timeseries"),
    param("exposure_timeseries_activation", output="exposure_timeseries", activation=True),
    param("daily_exposures_from_precomputed", output="daily_exposures", reads=frozenset({EXPOSURES_TABLE})),
    param("exposures_precompute_write", output="exposures_write"),
    param("funnel_precompute_write", metric=_funnel(**SEVEN_DAYS), output="metric_events_write"),
    param(
        "mean_precompute_write",
        metric=ExperimentMeanMetric(source=PURCHASE, **SEVEN_DAYS),
        output="metric_events_write",
    ),
    param("retention_precompute_write", metric=_retention(**SEVEN_DAYS), output="metric_events_write"),
]


class TestExperimentQueryBuilderSnapshots(BaseTest, QueryMatchingTest):
    def _builder(
        self,
        metric: Metric | None,
        *,
        breakdowns: list[Breakdown] | None,
        matured: bool,
        cuped: bool,
        activation: bool,
        entity_key: str,
        multiple_variant_handling: MultipleVariantHandling,
    ) -> ExperimentQueryBuilder:
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key="checkout-redesign",
            exposure_config=ExperimentEventExposureConfig(event="$feature_flag_called", properties=[]),
            filter_test_accounts=True,
            multiple_variant_handling=multiple_variant_handling,
            variants=["control", "test"],
            date_range_query=QueryDateRange(
                date_range=analysis_window(EXPERIMENT_START, None, self.team, NOW),
                team=self.team,
                interval=IntervalType.DAY,
                now=NOW,
            ),
            entity_key=entity_key,
            metric=metric,
            breakdowns=breakdowns,
            only_count_matured_users=matured,
            cuped_config=CupedQueryConfig(enabled=True, lookback_days=14) if cuped else None,
            activation_config=ExperimentEventExposureConfig(event="signed_up", properties=[]) if activation else None,
        )

    def _precompute_write_query(self, query_string: str, placeholders: dict[str, ast.Expr]) -> ast.SelectQuery:
        # The same sentinels that ensure_precomputed substitutes before it hashes a job, so the snapshot shows
        # the exact hash input. Keep them in sync with ensure_precomputed.
        query = parse_select(
            query_string,
            placeholders={
                **placeholders,
                "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
                "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
                "experiment_date_to": ast.Constant(value="__EXPERIMENT_DATE_TO__"),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    @parameterized.expand(CASES, name_func=lambda func, _num, p: f"{func.__name__}_{p.args[0]}")
    @time_machine.travel(NOW, tick=False)
    def test_built_query_matches_snapshot(
        self,
        _name: str,
        metric: Metric | Callable[[Team], Metric] | None = None,
        output: Output = "query",
        exposure_job_ids: list[str] | None = None,
        metric_events_job_ids: list[str] | None = None,
        reads: frozenset[str] = frozenset(),
        breakdowns: list[Breakdown] | None = None,
        matured: bool = False,
        cuped: bool = False,
        activation: bool = False,
        entity_key: str = "person_id",
        multiple_variant_handling: MultipleVariantHandling = MultipleVariantHandling.EXCLUDE,
    ) -> None:
        if metric is not None and not isinstance(metric, Metric):
            metric = metric(self.team)
        builder = self._builder(
            metric,
            breakdowns=breakdowns,
            matured=matured,
            cuped=cuped,
            activation=activation,
            entity_key=entity_key,
            multiple_variant_handling=multiple_variant_handling,
        )

        job_table: LazyComputationTable | None = None
        query: ast.SelectQuery
        if output == "query":
            query = builder.build_query(
                ExperimentPrecomputationContext(
                    exposure_job_ids=exposure_job_ids, metric_events_job_ids=metric_events_job_ids
                )
            )
        elif output == "exposure_timeseries":
            query = builder.get_exposure_timeseries_query()
        elif output == "daily_exposures":
            query = builder.get_daily_exposures_from_precomputed(EXPOSURE_JOB_IDS)
        elif output == "exposures_write":
            query = self._precompute_write_query(*builder.get_exposure_query_for_precomputation())
            job_table = LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED
        else:
            query = self._precompute_write_query(*builder.get_metric_events_query_for_precomputation())
            job_table = LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED

        printed = query.to_hogql()

        # A job id that does not reach its builder makes the query scan events instead. The results stay the same,
        # so only the tables that the query reads show the regression.
        assert set(re.findall(r"experiment_\w+_preaggregated", printed)) == reads
        self.assertQueryMatchesSnapshot(printed)
        if job_table is not None:
            # The job hash includes the parser source position of each node. Re-indenting a write template changes
            # the hash but not the printed HogQL, and then no cached precompute job matches the query.
            job_hash = compute_query_hash(
                LazyComputationQuery(query=query, table=job_table, timezone=self.team.timezone)
            )
            assert job_hash == self.snapshot
