"""Serve web overview and stats table queries from the dimensional precompute tables.

The dimensional tables have the same columns as the legacy pre-aggregated tables, so the
legacy query builders run unchanged against them. Two differences need the subclasses here:
the table names, and a `job_id IN (...)` filter. A recent window can hold several job
generations at once, and without the filter `sumMerge`/`uniqMerge` would count each
generation.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Union

from django.utils import timezone

import structlog
from dateutil.relativedelta import relativedelta

from posthog.schema import WebStatsBreakdown

from posthog.hogql import ast

from posthog.models.team.event_retention import events_retention_months_for_team

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WebAnalyticsPreAggregatedQueryBuilder,
)
from products.web_analytics.backend.hogql_queries.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    DimensionalJobIds,
    dimensional_job_ids,
)
from products.web_analytics.backend.hogql_queries.web_overview_pre_aggregated import (
    WebOverviewPreAggregatedQueryBuilder,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
    from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)


def ready_dimensional_job_ids(
    runner: Union["WebStatsTableQueryRunner", "WebOverviewQueryRunner"],
) -> DimensionalJobIds | None:
    """The job ids to read when the query opted in and both tables cover its
    whole range, including the compare period. None means the caller uses its next path."""
    web_query_modifiers = runner.query.webQueryModifiers
    if not (web_query_modifiers and web_query_modifiers.useDimensionalTables):
        return None
    # The tables are built without a user, so they cannot honor per-user property restrictions.
    if team_has_property_access_rules(team_id=runner.team.pk):
        return None
    # The writer builds all traffic, so the rows cannot exclude the team's test accounts.
    if runner._test_account_filters:
        return None

    # The channel breakdown and filter use the built-in channel rules, because the stored dimensions
    # cannot evaluate custom rules that match on the entry URL.
    if runner.modifiers.customChannelTypeRules and _reads_channel_type(runner):
        return None

    periods = [runner.query_date_range]
    if runner.query_compare_to_date_range:
        periods.append(runner.query_compare_to_date_range)
    if not all(_fits_whole_hour_buckets(period.date_from(), period.date_to()) for period in periods):
        return None

    start = min(period.date_from() for period in periods)
    if _crosses_events_retention_floor(runner, start):
        return None

    # A range can end after now, for example at the end of the current day in the project
    # timezone. No rows exist past now, and the writer does not build the next UTC day yet.
    end = min(runner.query_date_range.date_to(), timezone.now())
    try:
        return dimensional_job_ids(runner.team, start.astimezone(UTC), end.astimezone(UTC))
    except Exception:
        logger.exception("web_dimensional_job_ids_lookup_failed", team_id=runner.team.pk)
        return None


def _reads_channel_type(runner: Union["WebStatsTableQueryRunner", "WebOverviewQueryRunner"]) -> bool:
    if getattr(runner.query, "breakdownBy", None) == WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
        return True
    return any(getattr(prop, "key", None) == "$channel_type" for prop in runner.query.properties)


def _fits_whole_hour_buckets(date_from: datetime, date_to: datetime) -> bool:
    """Whether `period_bucket >= date_from AND period_bucket <= date_to` selects exactly the
    events in the range. Each bucket holds one UTC hour, so the start must be an hour boundary
    and the inclusive end must be the last microsecond of an hour. An end after now is also
    exact, because the bucket of the current hour holds only events up to now."""
    if not _is_utc_hour_boundary(date_from):
        return False
    return _is_utc_hour_boundary(date_to + timedelta(microseconds=1)) or date_to >= timezone.now()


def _is_utc_hour_boundary(moment: datetime) -> bool:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0) == moment


def _crosses_events_retention_floor(
    runner: Union["WebStatsTableQueryRunner", "WebOverviewQueryRunner"], start: datetime
) -> bool:
    # READY jobs outlive the retention window. The live path floors events at
    # `timestamp > now() - retention`, so a range that starts at or before that floor
    # would show older traffic here than live does.
    retention_months = events_retention_months_for_team(runner.team, runner.team.pk)
    if retention_months is None:
        return False
    return start <= timezone.now() - relativedelta(months=retention_months)


class _DimensionalTablesMixin(WebAnalyticsPreAggregatedQueryBuilder):
    job_ids: DimensionalJobIds

    @property
    def stats_table(self) -> str:
        return WEB_STATS_DIMENSIONAL_READ_TABLE

    @property
    def bounces_table(self) -> str:
        return WEB_BOUNCES_DIMENSIONAL_READ_TABLE

    def _get_filters(self, table_name: str, exclude_pathname: bool = False) -> ast.And:
        filters = super()._get_filters(table_name, exclude_pathname=exclude_pathname)
        job_ids = self.job_ids.stats if table_name == WEB_STATS_DIMENSIONAL_READ_TABLE else self.job_ids.bounces
        job_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=[table_name, "job_id"]),
            right=ast.Constant(value=[str(job_id) for job_id in job_ids]),
        )
        return ast.And(exprs=[*filters.exprs, job_id_filter])


class DimensionalStatsTableQueryBuilder(_DimensionalTablesMixin, StatsTablePreAggregatedQueryBuilder):
    def __init__(self, runner: "WebStatsTableQueryRunner", job_ids: DimensionalJobIds) -> None:
        super().__init__(runner)
        self.job_ids = job_ids


class DimensionalWebOverviewQueryBuilder(_DimensionalTablesMixin, WebOverviewPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebOverviewQueryRunner", job_ids: DimensionalJobIds) -> None:
        super().__init__(runner)
        self.job_ids = job_ids
