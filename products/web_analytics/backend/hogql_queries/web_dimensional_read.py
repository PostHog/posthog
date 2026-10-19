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

from posthog.hogql import ast

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

    start = runner.query_date_range.date_from()
    if runner.query_compare_to_date_range:
        start = min(start, runner.query_compare_to_date_range.date_from())
    # The buckets are whole UTC hours. A half-hour offset puts each project-local day boundary
    # inside a bucket, so the read would drop or add part of an hour at both ends. The offset
    # can change with DST inside the range, so every bound gets the check.
    if not all(_is_whole_hour_offset(bound) for bound in (start, runner.query_date_range.date_to())):
        return None

    # A range can end after now, for example at the end of the current day in the project
    # timezone. No rows exist past now, and the writer does not build the next UTC day yet.
    end = min(runner.query_date_range.date_to(), timezone.now())
    try:
        return dimensional_job_ids(runner.team, start.astimezone(UTC), end.astimezone(UTC))
    except Exception:
        logger.exception("web_dimensional_job_ids_lookup_failed", team_id=runner.team.pk)
        return None


def _is_whole_hour_offset(moment: datetime) -> bool:
    offset = moment.utcoffset() or timedelta(0)
    return offset % timedelta(hours=1) == timedelta(0)


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
