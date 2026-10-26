"""Runner for the `MetricsHistogramQuery` schema node — a latency-over-time heatmap.

The heavy lifting (per-series temporality/reset handling, per-time-bucket summed bucket-count
distributions) is `MetricQueryRunner._build_histogram_query`; this runner reuses it and assembles
the response into the grid the heatmap panel draws: one column per time bucket, one row per bucket
upper bound, cell = observation count.
"""

import math
import datetime as dt
from datetime import datetime
from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import (
    CachedMetricsHistogramQueryResponse,
    DashboardFilter,
    DateRange,
    MetricsHistogramQuery,
    MetricsHistogramQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.permissions import posthog_feature_flag_enabled
from posthog.shared_link_user import SharedLinkUser

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.metrics.backend.date_range import metrics_query_date_range
from products.metrics.backend.facade.contracts import METRICS_FEATURE_FLAG, MetricFilter
from products.metrics.backend.facade.enums import AttributeScope, FilterOp
from products.metrics.backend.metric_query_runner import _INTERVAL_LADDER, _QUERY_SETTINGS, _interval_step
from products.metrics.backend.metric_samples_query_runner import build_metric_query_runner
from products.metrics.backend.query_interval import resolve_query_interval
from products.metrics.backend.variables import (
    filter_referenced_names,
    from_dashboard,
    from_query,
    referenced_names,
    substitute_filters,
    to_query,
    unresolved_message,
)

if TYPE_CHECKING:
    from posthog.models import User

# The grid materializes bounds x time columns of Python objects, so its size is
# capped up front: an authenticated user could otherwise pair a fine interval
# over a long range with many explicit histogram bounds and exhaust a query
# worker's memory.
MAX_GRID_CELLS = 250_000


def _grid_time_key(value: datetime) -> str:
    """The grid key for one bucket start. The histogram query emits datetimes
    for most intervals but bare dates for week-or-longer buckets, so both
    sides of the lookup normalize through ClickHouse's naive string form."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _round_keeping_total(values: list[float]) -> list[int]:
    """Round merged counts to whole observations without losing any.

    Merging splits a bucket over finer edges, so one observation can become four quarters. Rounding
    each alone would drop it; the largest remainders take the observations that rounding down loses.
    """
    floors = [math.floor(value) for value in values]
    missing = round(sum(values)) - sum(floors)
    by_remainder = sorted(range(len(values)), key=lambda index: floors[index] - values[index])
    for index in by_remainder[:missing]:
        floors[index] += 1
    return floors


class MetricsHistogramQueryRunner(AnalyticsQueryRunner[MetricsHistogramQueryResponse]):
    query: MetricsHistogramQuery
    cached_response: CachedMetricsHistogramQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        user_access_control.assert_access_level_for_resource("metrics", "viewer")
        if not posthog_feature_flag_enabled(
            METRICS_FEATURE_FLAG,
            str(user.distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")
        return True

    def _enforce_alpha_gate_for_anonymous_viewers(self) -> None:
        user = cast("Optional[User | SharedLinkUser]", self.user)
        if user is None or not user.is_anonymous:
            return
        if not posthog_feature_flag_enabled(
            METRICS_FEATURE_FLAG,
            str(getattr(user, "distinct_id", None) or f"shared-viewer-{self.team.pk}"),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise UserAccessControlError("metrics", "viewer")

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError(
            "MetricsHistogramQuery reuses MetricQueryRunner's histogram query; there is no single statement"
        )

    def _calculate(self) -> MetricsHistogramQueryResponse:
        self._enforce_alpha_gate_for_anonymous_viewers()
        date_range = metrics_query_date_range(self.team, self.query.dateRange)
        date_from = date_range.date_from()
        date_to = date_range.date_to()

        interval = self.query.interval or _INTERVAL_LADDER[0][0]
        # Auto-pick the finest interval that keeps the bucket count sane when not pinned.
        if self.query.interval is None:
            span = date_to - date_from
            for name, step, _ in _INTERVAL_LADDER:
                if span / step <= 100:
                    interval = name
                    break
            else:
                interval = _INTERVAL_LADDER[-1][0]

        substitution = substitute_filters(self.query.filters, from_query(self.query.variables))
        if substitution.unresolved:
            raise ExposedHogQLError(unresolved_message(substitution.unresolved))
        filters = tuple(
            MetricFilter(
                key=f.key,
                op=FilterOp(f.op.value),
                value=f.value,
                scope=AttributeScope(f.scope.value) if f.scope is not None else AttributeScope.AUTO,
            )
            for f in substitution.filters
        )

        try:
            runner = build_metric_query_runner(
                team=self.team,
                metric_name=self.query.metricName,
                aggregation="histogram_quantile",
                date_from=date_from,
                date_to=date_to,
                filters=filters,
                interval=resolve_query_interval(interval, from_query(self.query.variables), date_from, date_to),
                quantile=0.5,  # unused by the grid query; required by the constructor
                # One metric name can hold series of more than one OTel type; the
                # heatmap must grid only the distribution the viewer picked.
                metric_type=self.query.metricType.value if self.query.metricType else None,
            )
        except ValueError as exc:
            # The runner signals user errors (inverted range, too-wide span, unknown
            # interval, too many buckets) with ValueError; /query only exposes typed
            # errors, so a bare ValueError would surface as a 500 instead of a 400.
            raise ExposedHogQLError(str(exc)) from exc

        # Reuse the per-bucket distribution query directly rather than the quantile post-processing.
        query = runner._build_histogram_query()
        response = execute_hogql_query(
            query_type="MetricsHistogramQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=_QUERY_SETTINGS,
        )
        try:
            runner._raise_on_truncation(response.results)
        except ValueError as exc:
            raise ExposedHogQLError(str(exc)) from exc

        # The runner floors date_from onto the bucket grid in the team timezone and returns
        # tz-aware bucket starts; rebuild the same grid so response rows land on columns exactly.
        grid_start = runner.date_from
        # The runner may coarsen the interval to stay within its bucket limit, so read its step.
        step = _interval_step(runner.interval)

        # Series can use different bucket layouts, so every time bucket merges onto the union of
        # the edges. The grid then has one stable y axis.
        bounds = runner.histogram_edges(response.results)

        # Assemble the grid: column per time bucket, row per bound, zero-filled.
        # `runner.date_to` is exclusive, so the last column is the bucket whose
        # start is strictly before it — a date_to that lands exactly on a bucket
        # boundary adds no trailing zero column. Bucket starts key the columns in
        # ClickHouse's naive string form because weekly rows come back as dates.
        grid_times: list[str] = []
        cursor = grid_start
        while cursor < runner.date_to:
            grid_times.append(cursor.isoformat())
            cursor = cursor + step
        time_index = {_grid_time_key(grid_start + i * step): i for i in range(len(grid_times))}

        if len(bounds) * len(grid_times) > MAX_GRID_CELLS:
            raise ExposedHogQLError(
                f"heatmap grid would hold {len(bounds)} rows x {len(grid_times)} columns; "
                "use a coarser interval, a narrower range, or fewer histogram bounds"
            )
        # Merge only after the size check: every merged time bucket holds the whole union of edges.
        distributions = runner.merged_distributions(response.results, edges=bounds)

        counts = [[0 for _ in grid_times] for _ in bounds]
        for (time_val, *_), merged in distributions.items():
            if isinstance(time_val, datetime):
                time_key = _grid_time_key(time_val.astimezone(grid_start.tzinfo))
            else:
                # Week-or-longer buckets come back as bare dates.
                time_key = dt.datetime.combine(time_val, dt.time.min).strftime("%Y-%m-%d %H:%M:%S")
            column = time_index.get(time_key)
            if column is None:
                continue
            for bound_idx, count in enumerate(_round_keeping_total(merged.counts[: len(bounds)])):
                counts[bound_idx][column] += count

        # The base response requires `results`; the heatmap grid lives in times/bounds/counts,
        # so `results` is returned as null.
        return MetricsHistogramQueryResponse(
            results=None, times=grid_times, bounds=[float(b) for b in bounds], counts=counts
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> None:
        if dashboard_filter.date_from or dashboard_filter.date_to:
            self.query.dateRange = DateRange(
                date_from=dashboard_filter.date_from,
                date_to=dashboard_filter.date_to,
            )
        if dashboard_filter.metricVariables:
            # The values go into the query, so each selection has its own cache entry and reaches the async worker.
            self.query.variables = (
                to_query(
                    from_dashboard(dashboard_filter.metricVariables),
                    [*referenced_names(self.query.interval), *filter_referenced_names(self.query.filters)],
                )
                or None
            )
