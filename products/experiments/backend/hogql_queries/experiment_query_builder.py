from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

from django.utils import timezone

from posthog.schema import (
    ActionsNode,
    Breakdown,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.breakdown_injector import BreakdownInjector
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.experiment_cuped_query_builder import CupedQueryBuilder
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureQueryBuilder
from products.experiments.backend.hogql_queries.experiment_funnel_query_builder import FunnelQueryBuilder
from products.experiments.backend.hogql_queries.experiment_mean_query_builder import MeanQueryBuilder
from products.experiments.backend.hogql_queries.experiment_metric_values import (
    build_conversion_window_predicate,
    build_conversion_window_predicate_for_events,
    build_metric_predicate,
    build_session_conversion_window_predicate,
    build_value_aggregation_expr,
    build_value_expr,
    get_conversion_window_seconds,
)
from products.experiments.backend.hogql_queries.experiment_query_context import (
    ExperimentPrecomputationContext,
    ExperimentQueryContext,
)
from products.experiments.backend.hogql_queries.experiment_ratio_query_builder import RatioQueryBuilder
from products.experiments.backend.hogql_queries.experiment_retention_query_builder import RetentionQueryBuilder
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    is_default_exposure_config,
    normalize_to_exposure_criteria,
    resolve_default_exposure_event,
)


def resolve_exposure_config_for_builder(
    exposure_config: ExperimentEventExposureConfig | ActionsNode,
    team: Team,
    start_date: Optional[datetime],
) -> ExperimentEventExposureConfig | ActionsNode:
    if isinstance(exposure_config, ExperimentEventExposureConfig) and exposure_config.event == DEFAULT_EXPOSURE_EVENT:
        return exposure_config.model_copy(update={"event": resolve_default_exposure_event(team, start_date)})
    return exposure_config


@dataclass(frozen=True, kw_only=True)
class ExposureQueryParams:
    """Exposure-related parameters required by the query builder, resolved from stored criteria."""

    exposure_config: ExperimentEventExposureConfig | ActionsNode
    activation_config: ExperimentEventExposureConfig | ActionsNode | None
    multiple_variant_handling: MultipleVariantHandling
    filter_test_accounts: bool


def get_exposure_config_params_for_builder(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
    team: Team,
    start_date: Optional[datetime],
) -> ExposureQueryParams:
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    exposure_config: ExperimentEventExposureConfig | ActionsNode
    activation_config: ExperimentEventExposureConfig | ActionsNode | None = None
    if criteria is None:
        exposure_config = ExperimentEventExposureConfig(
            event=resolve_default_exposure_event(team, start_date), properties=[]
        )
        filter_test_accounts = True
        multiple_variant_handling = MultipleVariantHandling.EXCLUDE
    else:
        if criteria.exposure_config is None:
            exposure_config = ExperimentEventExposureConfig(
                event=resolve_default_exposure_event(team, start_date), properties=[]
            )
        elif (
            isinstance(criteria.exposure_config, ExperimentEventExposureConfig)
            and criteria.exposure_config.event == DEFAULT_EXPOSURE_EVENT
        ):
            # A config naming $feature_flag_called explicitly is the default exposure, not a
            # custom one (same convention as get_exposure_event_and_property), so it follows
            # the same event resolution while keeping its property filters.
            exposure_config = resolve_exposure_config_for_builder(criteria.exposure_config, team, start_date)
        else:
            exposure_config = criteria.exposure_config
        # Activation only composes with the default exposure; a custom exposure_config
        # disables it (validation rejects the combination, but stored data predating it
        # must not silently change semantics).
        if is_default_exposure_config(criteria.exposure_config):
            activation_config = criteria.activation_config
        filter_test_accounts = bool(criteria.filterTestAccounts) if criteria.filterTestAccounts is not None else True
        multiple_variant_handling = criteria.multiple_variant_handling or MultipleVariantHandling.EXCLUDE

    return ExposureQueryParams(
        exposure_config=exposure_config,
        activation_config=activation_config,
        multiple_variant_handling=multiple_variant_handling,
        filter_test_accounts=filter_test_accounts,
    )


class ExperimentQueryBuilder:
    def __init__(
        self,
        team: Team,
        feature_flag_key: str,
        exposure_config: ExperimentEventExposureConfig | ActionsNode,
        filter_test_accounts: bool,
        multiple_variant_handling: MultipleVariantHandling,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        metric: Optional[
            ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric
        ] = None,
        breakdowns: list[Breakdown] | None = None,
        only_count_matured_users: bool = False,
        cuped_config: CupedQueryConfig | None = None,
        activation_config: ExperimentEventExposureConfig | ActionsNode | None = None,
    ):
        self.team = team
        self.metric = metric
        self.only_count_matured_users = only_count_matured_users
        self.feature_flag_key = feature_flag_key
        self.variants = variants
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.exposure_config = exposure_config
        self.activation_config = activation_config
        self.filter_test_accounts = filter_test_accounts
        self.multiple_variant_handling = multiple_variant_handling
        self.breakdowns = breakdowns or []
        self.breakdown_injector = BreakdownInjector(self.breakdowns, metric) if metric else None
        self.preaggregation_job_ids: list[str] | None = None
        self.metric_events_preaggregation_job_ids: list[str] | None = None
        self.cuped_config = cuped_config or CupedQueryConfig()
        # ponytail: funnel CUPED sources its pre-exposure covariate from the metric_events
        # scan, but activation mode forces the temporal filter that removes those rows, so
        # the covariate would silently be 0 for everyone. Disable it until the covariate
        # gets its own pre-window scan.
        if activation_config is not None and isinstance(metric, ExperimentFunnelMetric):
            self.cuped_config = CupedQueryConfig(enabled=False, lookback_days=self.cuped_config.lookback_days)

        # Frozen snapshot for builders that take a context instead of this builder,
        # such as ExposureQueryBuilder. Methods on this class read the self.* attributes,
        # so a later change to one of them does not reach the context.
        self.context = ExperimentQueryContext(
            team=self.team,
            feature_flag_key=self.feature_flag_key,
            exposure_config=self.exposure_config,
            filter_test_accounts=self.filter_test_accounts,
            multiple_variant_handling=self.multiple_variant_handling,
            variants=tuple(self.variants),
            date_range_query=self.date_range_query,
            entity_key=self.entity_key,
            breakdowns=tuple(self.breakdowns),
            only_count_matured_users=self.only_count_matured_users,
            cuped_config=self.cuped_config,
            activation_config=self.activation_config,
        )

    # Experiment queries group by (variant, breakdown_values), so the row count is
    # bounded by num_variants × num_breakdown_values. The HogQL executor injects
    # LIMIT 100 when no explicit limit is set, which silently truncates results for
    # high-cardinality breakdowns.
    QUERY_RESULT_LIMIT = MAX_SELECT_RETURNED_ROWS

    def build_query(self, precomputation_context: ExperimentPrecomputationContext | None = None) -> ast.SelectQuery:
        """
        ``precomputation_context`` carries the precomputed job IDs. They arrive here
        and not in __init__, because the same builder generates the precompute
        queries before any job IDs exist. The IDs are stored on self so the
        metric builders read them like any other builder state.
        """
        if precomputation_context is not None:
            self.preaggregation_job_ids = precomputation_context.exposure_job_ids
            self.metric_events_preaggregation_job_ids = precomputation_context.metric_events_job_ids

        assert self.metric is not None, "metric is required for build_query()"
        match self.metric:
            case ExperimentFunnelMetric():
                query = self._build_funnel_query()
            case ExperimentMeanMetric():
                query = self._build_mean_query()
            case ExperimentRatioMetric():
                query = self._build_ratio_query()
            case ExperimentRetentionMetric():
                query = self._build_retention_query()
            case _:
                raise NotImplementedError(
                    f"Only funnel, mean, ratio, and retention metrics are supported. Got {type(self.metric)}"
                )

        query.limit = ast.Constant(value=self.QUERY_RESULT_LIMIT)
        return query

    def _exposure_query_builder(self) -> ExposureQueryBuilder:
        """Built per call so it picks up the ``preaggregation_job_ids`` that build_query() sets."""
        return ExposureQueryBuilder(
            context=self.context,
            breakdown_injector=self.breakdown_injector,
            maturity_having_builder=self._build_maturity_having_clause,
            preaggregation_job_ids=self.preaggregation_job_ids,
        )

    def _funnel_query_builder(self) -> FunnelQueryBuilder:
        return FunnelQueryBuilder(self)

    def _retention_query_builder(self) -> RetentionQueryBuilder:
        return RetentionQueryBuilder(self)

    def _mean_query_builder(self) -> MeanQueryBuilder:
        return MeanQueryBuilder(self)

    def _ratio_query_builder(self) -> RatioQueryBuilder:
        return RatioQueryBuilder(self)

    def _cuped_query_builder(self) -> CupedQueryBuilder:
        return CupedQueryBuilder(self)

    def get_exposure_timeseries_query(self) -> ast.SelectQuery:
        """
        Daily exposure counts per variant. Each entity counts once, on the day of
        its first exposure. Columns: day, variant, exposed_count.
        """
        return self._exposure_query_builder().timeseries_query()

    def get_daily_exposures_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Reads from the precomputed table and aggregates into day/variant/count.
        Used by the Exposures tab in the experiment UI.
        """
        return self._exposure_query_builder().daily_exposures_from_precomputed(job_ids)

    def _get_conversion_window_seconds(self) -> int:
        """Returns 0 when the metric has no conversion window."""
        assert self.metric is not None, "metric is required for _get_conversion_window_seconds()"
        return get_conversion_window_seconds(self.metric)

    def _get_maturity_window_seconds(self) -> int:
        """
        Non-retention metrics only. Retention uses
        RetentionQueryBuilder.get_retention_maturity_seconds() and applies maturity
        in its start_events CTE, anchored on the start_event timestamp.
        """
        return self._get_conversion_window_seconds()

    def _build_maturity_having_clause(self, timestamp_expr: str = "timestamp") -> Optional[ast.Expr]:
        """
        Returns a HAVING clause expression to filter out users whose conversion window
        hasn't elapsed yet, or None if the feature is not enabled.

        Anchored on the user's first exposure (min timestamp), matching how the
        variant is assigned. Anchoring on the last exposure would keep resetting the
        window for flags re-evaluated repeatedly (e.g. backend flags), so active users
        would never mature. Callers pass an exposure-only timestamp expression.

        Retention metrics apply maturity in their own start_events CTE through
        RetentionQueryBuilder.build_retention_maturity_having_clause(), so this
        returns None for them.
        """
        if self.metric is None:
            return None
        if isinstance(self.metric, ExperimentRetentionMetric):
            return None
        if not self.only_count_matured_users:
            return None

        maturity_seconds = self._get_maturity_window_seconds()
        if maturity_seconds == 0:
            return None

        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        return parse_expr(
            f"min({timestamp_expr}) + toIntervalSecond({{maturity_seconds}}) <= toDateTime({{now}}, 'UTC')",
            placeholders={
                "maturity_seconds": ast.Constant(value=maturity_seconds),
                "now": ast.Constant(value=now),
            },
        )

    def _build_funnel_query(self) -> ast.SelectQuery:
        return self._funnel_query_builder().build_funnel_query()

    def _build_mean_query(self) -> ast.SelectQuery:
        return self._mean_query_builder().build_mean_query()

    def _build_ratio_query(self) -> ast.SelectQuery:
        return self._ratio_query_builder().build_ratio_query()

    def _build_conversion_window_predicate(self) -> ast.Expr:
        """Uses "metric_events" as the events alias."""
        return build_conversion_window_predicate(self._get_conversion_window_seconds())

    def _build_session_conversion_window_predicate(self) -> ast.Expr:
        """Uses first_event_timestamp from metric_events_by_session as the event time."""
        return build_session_conversion_window_predicate(self._get_conversion_window_seconds())

    def _build_conversion_window_predicate_for_events(self, events_alias: str) -> ast.Expr:
        return build_conversion_window_predicate_for_events(events_alias, self._get_conversion_window_seconds())

    def _build_cuped_pre_window_predicate(
        self,
        events_alias: str = "metric_events",
        exposure_alias: str = "exposures",
    ) -> ast.Expr:
        return self._cuped_query_builder().build_cuped_pre_window_predicate(events_alias, exposure_alias)

    def _build_windowed_metric_value_expr(
        self, window_predicate: ast.Expr, events_alias: str = "metric_events"
    ) -> ast.Expr:
        return self._cuped_query_builder().build_windowed_metric_value_expr(window_predicate, events_alias)

    def _inject_funnel_covariate_into_entity_metrics(
        self,
        query: ast.SelectQuery,
        *,
        events_alias: str,
        last_step_index: int,
        exposure_alias: str,
    ) -> None:
        self._cuped_query_builder().inject_funnel_covariate_into_entity_metrics(
            query,
            events_alias=events_alias,
            last_step_index=last_step_index,
            exposure_alias=exposure_alias,
        )

    def _extend_date_from_for_funnel_cuped(self, date_from: ast.Expr) -> ast.Expr:
        return self._cuped_query_builder().extend_date_from_for_funnel_cuped(date_from)

    def _build_metric_predicate(
        self,
        source=None,
        table_alias: str = "events",
        cuped_lookback_days: int | None = None,
    ) -> ast.Expr:
        """
        For ratio metrics, pass the specific source (numerator or denominator) and table_alias.
        For mean metrics, the default is self.metric.source with the "events" alias.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_metric_predicate(
            team=self.team,
            source=source,
            date_range_query=self.date_range_query,
            conversion_window_seconds=self._get_conversion_window_seconds(),
            table_alias=table_alias,
            cuped_lookback_days=cuped_lookback_days,
        )

    def _build_value_expr(self, source=None, apply_coalesce: bool = True) -> ast.Expr:
        """
        For ratio metrics, pass the specific source (numerator or denominator).
        For mean metrics, the default is self.metric.source.

        See build_value_expr() for apply_coalesce.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_value_expr(source, apply_coalesce=apply_coalesce)

    def _build_value_aggregation_expr(
        self,
        source=None,
        events_alias: str = "metric_events",
        column_name: str = "value",
        value_expr: ast.Expr | None = None,
    ) -> ast.Expr:
        """
        For ratio metrics, pass the specific source (numerator or denominator) and events_alias.
        For mean metrics, the default is self.metric.source with the "metric_events" alias.

        value_expr, when set, replaces the {events_alias}.{column_name} column.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_value_aggregation_expr(
            source,
            events_alias=events_alias,
            column_name=column_name,
            value_expr=value_expr,
        )

    def _build_variant_property(self) -> ast.Field:
        return self._exposure_query_builder().build_variant_property()

    def _build_exposure_predicate(self) -> ast.Expr:
        return self._exposure_query_builder().build_exposure_predicate()

    def _build_exposure_step_predicate(self) -> ast.Expr:
        """
        Predicate for rows that can serve as the funnel's exposure step (step_0); the
        activation predicate in activation mode, the exposure predicate otherwise.
        """
        return self._exposure_query_builder().build_exposure_step_predicate()

    def _get_exposure_query(self) -> ast.SelectQuery:
        return self._exposure_query_builder().select_query()

    def get_exposure_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        The query string uses {time_window_min} and {time_window_max} placeholders
        that the lazy computation system fills for each daily bucket. Pass the
        returned placeholders dict to ensure_precomputed().
        """
        return self._exposure_query_builder().precomputation_query()

    def get_metric_events_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the SELECT query that the lazy computation system wraps in an
        INSERT INTO experiment_metric_events_preaggregated, dispatched by metric
        type. This is the write path. It scans the events table and stores one
        row per matching event: funnel and retention metrics pack step indicators
        into an Array(UInt8), mean metrics store the per-event value in numeric_value.

        The query uses {time_window_min} and {time_window_max} placeholders filled
        by the lazy computation system for each daily bucket.
        """
        match self.metric:
            case ExperimentFunnelMetric():
                return self._funnel_query_builder().get_funnel_metric_events_query_for_precomputation()
            case ExperimentMeanMetric():
                return self._mean_query_builder().get_mean_metric_events_query_for_precomputation()
            case ExperimentRetentionMetric():
                return self._retention_query_builder().get_retention_metric_events_query_for_precomputation()
            case _:
                raise NotImplementedError(f"Metric-events precomputation is not supported for {type(self.metric)}")

    def get_metric_events_window_extension_seconds(self) -> int:
        """
        How far past the experiment end date the metric-events precompute scan must
        extend. The conversion window for funnel/mean metrics; retention adds the
        retention window on top (completions can land that much after a start event).
        """
        if isinstance(self.metric, ExperimentRetentionMetric):
            return self._retention_query_builder().get_metric_events_window_extension_seconds()
        return self._get_conversion_window_seconds()

    def _build_retention_query(self) -> ast.SelectQuery:
        return self._retention_query_builder().build_retention_query()
